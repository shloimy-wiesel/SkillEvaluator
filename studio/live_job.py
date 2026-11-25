"""Run the installed Tier 3 CLI with a frozen chat profile and isolated task inputs."""

import json
import mmap
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from html import escape
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from skillevaluator.provider_config import resolve_llm_provider
from skillevaluator.source_identity import normalized_evaluated_source
from skillevaluator.tier3.dataset_utils import DATASET_EXTENSIONS, find_eval_file

from .jobs import JobContext, JobDefinition, Outcome
from .native_location import bounded_directory, native_directory
from .providers import worker_environment
from .worker_deadline import bounded_worker, run_evaluator
from .workspace import WorkspaceError

Positive = Annotated[int, Field(gt=0)]
Budget = Annotated[int, Field(ge=0)]
Agent = Literal["codex", "opencode", "claude-code"]
Model = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_.:/@+-]{1,256}$")]


class Controls(BaseModel):
    harbor_keep_jobs: bool = False
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    workflow: Literal["evaluate", "direct", "alias"] = "evaluate"
    env_mode: Literal["docker", "kata"] = "docker"
    grading_mode: Literal["default", "default_plus_custom", "custom_only"] | None = None
    arms: Literal["paired", "skill", "baseline"] = "paired"
    agents: tuple[Agent, ...] = ()
    model: Model | None = None
    codex_model: Model | None = None
    opencode_model: Model | None = None
    claude_code_model: Model | None = None
    reuse_baseline: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")] | None = None
    compare_to: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")] | None = None
    dataset: str | None = None
    price_file: str | None = None
    n_attempts: Positive | None = None
    n_concurrent: Positive | None = None
    max_agents: Positive | None = None
    max_cases: Positive | None = None
    max_agent_tokens: Budget | None = None
    max_judge_calls: Budget | None = None
    max_attempts_total: Budget | None = None
    max_cost_usd: Annotated[float, Field(ge=0)] | None = None
    pass_threshold: Annotated[float, Field(ge=0, le=1)] | None = None
    timeout_multiplier: Annotated[float, Field(gt=0)] | None = None
    override_cpus: Positive | None = None
    override_memory_mb: Positive | None = None
    override_storage_mb: Positive | None = None
    stop_on_pass: bool | None = None
    agent_runtime_preflight: bool | None = None
    tolerate_baseline_timeouts: bool | None = None
    autopilot: bool = False
    sandbox_grader_consent: bool = False

    @model_validator(mode="after")
    def combinations(self):
        for value in (self.dataset, self.price_file):
            if value and (
                any(p.lower() in {"", ".", "..", ".git"} for p in value.split("/"))
                or "\\" in value
                or not value.isprintable()
                or len(value) > 1024
            ):
                raise ValueError("Choose a project-relative file.")
        if self.dataset and Path(self.dataset).suffix not in DATASET_EXTENSIONS:
            raise ValueError("Choose a JSON, JSONL or YAML dataset.")
        if self.max_cost_usd is not None and not self.price_file:
            raise ValueError("The USD budget requires a project price file.")
        if self.stop_on_pass and self.n_attempts == 1:
            raise ValueError("Stop on pass needs multiple attempts.")
        if (self.reuse_baseline and self.arms != "paired") or (self.compare_to and self.arms == "baseline"):
            raise ValueError("Selected comparison conflicts with the requested arms.")
        for agent, _ in self.model_overrides():
            if agent not in self.agents:
                raise ValueError("Select each agent with a model override.")
        return self

    def model_overrides(self):
        return [
            (agent, model)
            for agent, model in (
                ("codex", self.codex_model),
                ("opencode", self.opencode_model),
                ("claude-code", self.claude_code_model),
            )
            if model
        ]


class LiveOptions(Controls):
    profile_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    provider: str
    judge_model: str
    endpoint: str
    source_repository: str | None = None
    evaluator_revision: str | None = None


def operator_revision():
    revision = os.getenv("STUDIO_EVALUATOR_CONTAINER_REVISION") or None
    if revision and not (
        normalized_evaluated_source({"evaluator_container_revision": revision})
        and ("@sha256:" in revision or normalized_evaluated_source({"commit": revision}))
    ):
        raise WorkspaceError("Configure an immutable evaluator revision: an image digest or full Git SHA.")
    return revision


def snapshot(workspace, project_id, controls):
    env = worker_environment(workspace, project_id, "chat")
    config = resolve_llm_provider(env)
    if config.provider == "bedrock":
        raise WorkspaceError("Choose a key-backed chat provider for Studio live evaluations.")
    env["SKILL_EVAL_LLM_MODEL"] = config.model
    # Never allow the current saved credential to be submitted as a model or path.
    if config.api_key and config.api_key in controls.model_dump_json():
        raise WorkspaceError("Keep credentials out of live settings.")
    profile_id = uuid4().hex
    private = workspace.data_dir / "live-profiles" / project_id
    private.mkdir(parents=True, mode=0o700, exist_ok=True)
    project = workspace.get(project_id)
    repository = urlsplit(project.remote).path.strip("/").removesuffix(".git")
    identity = normalized_evaluated_source({"repository": repository}) or {}
    options = LiveOptions(
        source_repository=identity.get("repository"),
        evaluator_revision=operator_revision(),
        **controls.model_dump(),
        provider=config.provider,
        judge_model=config.model,
        endpoint=config.base_url or "",
        profile_id=profile_id,
    )
    retained_sources(workspace, project_id, project.folder, options)
    (private / profile_id).write_bytes(workspace.cipher.encrypt(json.dumps(env).encode()))
    return options


COMPLETED = {"passed", "failed", "neutral"}


def retained_sources(workspace, project_id, folder, options):
    """Authorize immutable job IDs before queueing and again when running/replaying."""
    selected = {}
    for key in ("reuse_baseline", "compare_to"):
        if not (run_id := getattr(options, key)):
            continue
        with closing(sqlite3.connect(workspace.db_path)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                "SELECT * FROM runs WHERE id=? AND project_id=? AND folder=? AND kind=?",
                (run_id, project_id, folder, LIVE.kind),
            ).fetchone()
        if not row or row["status"] not in COMPLETED:
            raise WorkspaceError("Choose a completed live run from this project and skill.")
        saved = LiveOptions.model_validate_json(row["options"])
        if (options.provider, options.endpoint, options.judge_model) != (
            saved.provider,
            saved.endpoint,
            saved.judge_model,
        ):
            raise WorkspaceError("The selected prior run used a different provider, endpoint or judge model.")
        if options.evaluator_revision != saved.evaluator_revision:
            raise WorkspaceError("Prior run used a different evaluator revision.")
        root = workspace.data_dir / "artifacts" / project_id / run_id / "tier3"
        try:
            native = bounded_directory(root)
            config = json.loads((native / "run_config.json").read_text())
            result = json.loads((native / "result.json").read_text())
            identity = config["evaluated_source"]
            valid = (
                result["run_id"] == native.name
                and result["execution_status"] == "succeeded"
                and identity["commit"] == row["sha"]
                and identity.get("repository") == saved.source_repository
                and identity.get("evaluator_container_revision") == saved.evaluator_revision
            )
        except (OSError, ValueError, TypeError, AttributeError, KeyError):
            valid = False
        if not valid:
            raise WorkspaceError("Prior evidence does not match the saved run provenance.")
        selected[key] = native
    return selected


def sandbox_preflight(cwd, env):
    if os.environ.get("STUDIO_LIVE_ENABLED") != "1":
        raise WorkspaceError("Live runtime is disabled. Configure the Studio live image and sandbox daemon.")
    for command, message in [
        (["harbor", "--version"], "Install the Tier 3 extra (Harbor 0.25)."),
        (["docker", "compose", "version"], "Install the Docker CLI and Compose plugin."),
        (["docker", "info"], "The sandbox Docker daemon is unavailable."),
    ]:
        try:
            probe = run_evaluator(
                command,
                env=env,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                limit=30,
                sandbox=False,
            )
            probe.check_returncode()
        except (OSError, subprocess.SubprocessError) as exc:
            raise WorkspaceError(message) from exc


@bounded_worker
def invoke_engine(args, cwd, env, *, retained=None):
    sandbox_preflight(cwd, env)
    launch = ["from skillevaluator.cli import cli; cli()"]
    if retained:
        launch = [
            "import sys,json; from pathlib import Path; from skillevaluator.cli import cli; "
            "from skillevaluator.tier3.retained_sources import authorized_sources; "
            "sources={k:Path(v) for k,v in json.loads(sys.argv.pop(1)).items()};\n"
            "with authorized_sources(sources): cli()",
            json.dumps({key: str(path) for key, path in retained.items()}),
        ]
    return run_evaluator(
        [sys.executable, "-I", "-c", *launch, *args],
        env=env,
        cwd=cwd,
        sandbox=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode


def check_stage_policy(source, options):
    """Only generated Harbor tasks; no repository-authored launchers or native environments."""
    from skillevaluator.tier3.evals_config import load_evals_config

    if any((source / "evals" / name).exists() for name in ("environment", "harbor")):
        raise WorkspaceError("This preset needs a dataset and a generated task environment.")
    config, config_path = load_evals_config(source)
    effective_mode = options.grading_mode or config.get("grading", {}).get("mode", "default")
    if effective_mode != "default" and not options.sandbox_grader_consent:
        raise WorkspaceError("Repository grading requires explicit sandbox consent.")
    if (
        config.get("harbor", {}).get("task_source") == "native_harbor"
        or set(config) - {"harbor", "schema_version", "grading"}
        or set(config.get("harbor", {}))
        - {
            "task_source",
            "agents",
            "resources",
            "max_cases",
            "max_agents",
            "n_attempts",
            "n_concurrent",
            "pass_threshold",
            "timeout_multiplier",
            "stop_on_pass",
            "agent_runtime_preflight",
            "tolerate_baseline_timeouts",
            "max_agent_tokens",
            "max_judge_calls",
            "max_attempts_total",
        }
    ):
        raise WorkspaceError("The pinned run policy contains settings outside this Studio preset.")
    return config_path, effective_mode


def copy_skill(source, skill, exclude):
    shutil.copytree(source, skill, ignore=lambda root, _names: {".git", *exclude} if Path(root) == source else {".git"})


def init_projection(root, base):
    # Bind linked-file discovery to this input projection even when the Studio
    # volume itself is nested in an unrelated developer checkout.
    subprocess.run(
        ["git", "init", "--quiet", "--template=", str(root)],
        env={"PATH": "/usr/bin:/bin", "HOME": str(base), "GIT_CONFIG_NOSYSTEM": "1"},
        cwd=base,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def stage_skill(source, base, exclude):
    skill = base / "inputs" / source.name
    copy_skill(source, skill, exclude)
    init_projection(skill.parent, base)
    return skill


def stage(ctx, base, options):
    source = ctx.skill
    config_path, effective_mode = check_stage_policy(source, options)
    skill = stage_skill(source, base, {"eval", "evals"})
    evals = skill / "evals"
    evals.mkdir()
    if config_path:
        shutil.copyfile(config_path, evals / config_path.name)
    for name in ("grader.py", "grader.sh"):
        if effective_mode != "default" and (grader := source / "evals" / name).is_file():
            shutil.copy2(grader, evals / name)
    if (fixtures := source / "evals/files").is_dir():
        shutil.copytree(fixtures, evals / "files")
    if (guide := source / "evals/EVAL.md").is_file():
        shutil.copyfile(guide, evals / guide.name)
    dataset = ctx.input_file(options.dataset) if options.dataset else find_eval_file(source)
    if dataset:
        shutil.copyfile(dataset, evals / ("evals" + dataset.suffix))
    elif options.workflow != "direct" and not options.autopilot:
        raise WorkspaceError("Evaluate requires an existing dataset; use the direct workflow to prepare one.")
    return skill


def redact_file(path, secrets):
    """Scrub echoed credentials without reading a large clean report into memory."""
    if path.stat().st_nlink != 1:
        raise WorkspaceError("Unsupported linked evidence.")
    if not path.stat().st_size:
        return
    with path.open("rb") as file, mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as data:
        if not any(data.find(value) >= 0 for value in secrets):
            return
        if len(data) > 64 * 1024**2:
            path.unlink()
            raise WorkspaceError("A large artifact contained a credential and was discarded.")
        clean = data[:]
    for value in secrets:
        clean = clean.replace(value, b"[REDACTED]")
    path.write_bytes(clean)


@bounded_worker
def evaluate(ctx: JobContext, options: LiveOptions) -> Outcome:
    workspace = ctx.workspace
    if options.evaluator_revision != operator_revision():
        raise WorkspaceError("The worker evaluator revision changed; queue a new run.")
    profile = workspace.data_dir / "live-profiles" / ctx.project_id / options.profile_id
    chat = json.loads(workspace.cipher.decrypt(profile.read_bytes()))
    secrets = {
        encoded.encode()
        for key, value in chat.items()
        if key.endswith("_API_KEY") and value
        for encoded in (value, json.dumps(value)[1:-1], escape(value))
    }
    output = ctx.artifacts / "tier3"
    # An empty trusted working directory is separate from the staged skill and home.
    with tempfile.TemporaryDirectory(dir=ctx.root.parent) as temp:
        base = Path(temp)
        skill = stage(ctx, base, options)
        missing = find_eval_file(skill) is None
        saved_dataset = profile.with_suffix(".dataset")
        if missing and saved_dataset.is_file():
            shutil.copyfile(saved_dataset, skill / "evals/evals.json")
        home = base / "home"
        home.mkdir()
        args = [
            *({"direct": ["tier3"], "alias": ["evaluate"], "evaluate": ["tier3", "evaluate"]}[options.workflow]),
            str(skill),
            "--backend",
            "harbor",
            "--env-mode",
            options.env_mode,
            "--skill-workspace-mode",
            "isolated",
            "--results-dir",
            str(output),
            "--evaluated-source-revision",
            ctx.revision,
            "--progress",
            "off",
        ]
        retained = retained_sources(workspace, ctx.project_id, ctx.skill.relative_to(ctx.root).as_posix(), options)
        for key, native in retained.items():
            args += ["--" + key.replace("_", "-"), native.name]
        if options.source_repository:
            args += ["--evaluated-source-repository", options.source_repository]
        if options.evaluator_revision:
            args += ["--evaluator-container-revision", options.evaluator_revision]
        if options.agents:
            args += ["--agents", ",".join(options.agents)]
        for agent, model in options.model_overrides():
            args += ["--agent-model", f"{agent}={model}"]
        if options.grading_mode:
            args += ["--grading-mode", options.grading_mode]
        for name in (
            "model",
            "n_attempts",
            "n_concurrent",
            "max_agents",
            "max_cases",
            "max_agent_tokens",
            "max_judge_calls",
            "max_attempts_total",
            "max_cost_usd",
            "pass_threshold",
            "timeout_multiplier",
            "override_cpus",
            "override_memory_mb",
            "override_storage_mb",
        ):
            if (value := getattr(options, name)) is not None:
                args += ["--" + name.replace("_", "-"), str(value)]
        if options.price_file:
            args += ["--price-file", str(ctx.input_file(options.price_file))]
        if options.arms != "paired":
            args += ["--skip-baseline" if options.arms == "skill" else "--skip-with-skill"]
        for name in ("agent_runtime_preflight", "stop_on_pass", "tolerate_baseline_timeouts"):
            if (enabled := getattr(options, name)) is not None:
                args.append(("--" if enabled else "--no-") + name.replace("_", "-"))
        if options.autopilot:
            args.append("--autopilot")
        if options.harbor_keep_jobs:
            args.append("--harbor-keep-jobs")
        env = {
            k: os.environ[k]
            for k in ("DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH", "SSL_CERT_FILE")
            if k in os.environ
        }
        env.update(
            chat,
            PATH=f"{Path(sys.executable).parent}:/usr/local/bin:/usr/bin:/bin",
            HOME=str(home),
            TMPDIR=str(base),
            LANG="C.UTF-8",
            PYTHON_DOTENV_DISABLED="1",
            SKILLEVALUATOR_OUTPUT_PROVENANCE_KEY_FILE=str(workspace.data_dir / "tier3-output.key"),
        )
        ctx.progress("Checking sandbox prerequisites and running Harbor trials")
        try:
            code = invoke_engine(args, base, env, **({"retained": retained} if retained else {}))
        finally:
            for path in output.rglob("*"):
                if not path.is_symlink() and path.is_file():
                    redact_file(path, secrets)
        if dataset := find_eval_file(skill):
            redact_file(dataset, secrets)
            shutil.copyfile(dataset, ctx.artifacts / ("dataset" + dataset.suffix))
            if missing and not saved_dataset.exists():
                # Publish generated cases atomically for every later rerun of this snapshot.
                temporary = saved_dataset.with_suffix(".part")
                shutil.copyfile(dataset, temporary)
                temporary.replace(saved_dataset)

    try:
        result_path = native_directory(output) / "result.json"
    except (ValueError, OSError, RuntimeError) as exc:
        raise WorkspaceError(
            "No canonical Tier 3 result. Check dataset, provider/agent compatibility and sandbox readiness."
        ) from exc
    from skillevaluator.evaluation.tier3_report import agent_eval_result_from_directory
    from skillevaluator.reporting.json_reporter import JSONReporter
    from skillevaluator.tier3.harbor.run_budget import budget_fully_denied

    payload = json.loads(result_path.read_text())
    result = agent_eval_result_from_directory(
        ctx.skill,
        result_path.parent,
        env_mode=options.env_mode,
        engine_result=payload,
        evaluated_source=normalized_evaluated_source(
            {
                "commit": ctx.revision,
                "repository": options.source_repository,
                "evaluator_container_revision": options.evaluator_revision,
            }
        ),
        use_llm_judge=False,
    )
    canonical = result.metadata["agent_eval"] if result else {}
    verdict = str(payload.get("verdict") or canonical.get("verdict") or "").lower()
    status = "incomplete"
    if budget_fully_denied(payload.get("budget")):
        status = "not_run"
    elif code == 0 and payload.get("execution_status") == "succeeded" and result:
        status = {"neutral": "neutral", "fail": "failed", "pass": "passed", "inconclusive": "neutral"}.get(
            verdict, "incomplete"
        )
        if canonical.get("mode") == "baseline_only" and canonical.get("execution_status") == "succeeded":
            status = "neutral"
    benchmark = result_path.with_name("tier3-benchmark.md")
    markdown = (
        benchmark.read_text() if benchmark.is_file() and benchmark.resolve() == benchmark else f"# Tier 3: {status}\n"
    )
    report = (
        JSONReporter(explicit_skill_name=ctx.skill.name).render_all([result])
        if result
        else json.dumps(
            {
                "results": [],
                "execution_status": payload.get("execution_status"),
                "execution_errors": payload.get("execution_errors"),
            }
        )
    )
    return Outcome(status, code, report, markdown)


LIVE = JobDefinition("tier3-live-v1", LiveOptions, evaluate)
