"""Run the installed Tier 3 CLI with a frozen chat profile and isolated task inputs."""

import json
import mmap
import os
import shutil
import subprocess
import sys
import tempfile
from html import escape
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from skillevaluator.provider_config import resolve_llm_provider
from skillevaluator.tier3.dataset_utils import DATASET_EXTENSIONS, find_eval_file

from .jobs import JobContext, JobDefinition, Outcome
from .providers import worker_environment
from .workspace import WorkspaceError

Positive = Annotated[int, Field(gt=0)]
Budget = Annotated[int, Field(ge=0)]
Agent = Literal["codex", "opencode", "claude-code"]
Model = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_.:/@+-]{1,256}$")]


class Controls(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    workflow: Literal["evaluate", "direct"] = "evaluate"
    env_mode: Literal["docker", "kata"] = "docker"
    grading_mode: Literal["default", "default_plus_custom", "custom_only"] | None = None
    arms: Literal["paired", "skill", "baseline"] = "paired"
    agents: tuple[Agent, ...] = ()
    model: Model | None = None
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
    stop_on_pass: bool | None = None
    agent_runtime_preflight: bool | None = None
    tolerate_baseline_timeouts: bool | None = None
    autopilot: bool = False

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
        return self


class LiveOptions(Controls):
    profile_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    provider: str
    judge_model: str
    endpoint: str


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
    (private / profile_id).write_bytes(workspace.cipher.encrypt(json.dumps(env).encode()))
    return LiveOptions(
        **controls.model_dump(),
        provider=config.provider,
        judge_model=config.model,
        endpoint=config.base_url or "",
        profile_id=profile_id,
    )


def invoke_engine(args, cwd, env):
    """No shell, repo cwd, stdin, ambient providers, or repository Python path."""
    if os.environ.get("STUDIO_LIVE_ENABLED") != "1":
        raise WorkspaceError("Live runtime is disabled. Configure the Studio live image and sandbox daemon.")
    for command, message in [
        (["harbor", "--version"], "Install the Tier 3 extra (Harbor 0.25)."),
        (["docker", "compose", "version"], "Install the Docker CLI and Compose plugin."),
        (["docker", "info"], "The sandbox Docker daemon is unavailable."),
    ]:
        try:
            subprocess.run(
                command,
                env=env,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise WorkspaceError(message) from exc
    return subprocess.run(
        [sys.executable, "-I", "-c", "from skillevaluator.cli import cli; cli()", *args],
        env=env,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode


def stage(ctx, base, options):
    """Only generated Harbor tasks; no repository-authored launchers or native environments."""
    from skillevaluator.tier3.evals_config import load_evals_config

    source = ctx.skill
    if any((source / "evals" / name).exists() for name in ("environment", "harbor")):
        raise WorkspaceError("This preset needs a dataset and a generated task environment.")
    config, config_path = load_evals_config(source)
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
    skill = base / "inputs" / source.name
    shutil.copytree(
        source, skill, ignore=lambda root, _names: {".git", "eval", "evals"} if Path(root) == source else {".git"}
    )
    evals = skill / "evals"
    evals.mkdir()
    if config_path:
        shutil.copyfile(config_path, evals / config_path.name)
    for name in ("grader.py", "grader.sh"):
        if (grader := source / "evals" / name).is_file():
            shutil.copy2(grader, evals / name)
    if (fixtures := source / "evals/files").is_dir():
        shutil.copytree(fixtures, evals / "files")
    if (guide := source / "evals/EVAL.md").is_file():
        shutil.copyfile(guide, evals / guide.name)
    dataset = ctx.input_file(options.dataset) if options.dataset else find_eval_file(source)
    if dataset:
        shutil.copyfile(dataset, evals / ("evals" + dataset.suffix))
    elif options.workflow == "evaluate" and not options.autopilot:
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


def evaluate(ctx: JobContext, options: LiveOptions) -> Outcome:
    workspace = ctx.workspace
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
            "tier3",
            *(["evaluate"] if options.workflow == "evaluate" else []),
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
        if options.agents:
            args += ["--agents", ",".join(options.agents)]
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
            code = invoke_engine(args, base, env)
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
    paths = [path for path in output.glob("*/result.json") if path.resolve() == path and path.is_file()]
    if len(paths) != 1:
        raise WorkspaceError(
            "No canonical Tier 3 result. Check dataset, provider/agent compatibility and sandbox readiness."
        )
    from skillevaluator.evaluation.tier3_report import agent_eval_result_from_directory
    from skillevaluator.reporting.json_reporter import JSONReporter
    from skillevaluator.tier3.harbor.run_budget import budget_fully_denied

    payload = json.loads(paths[0].read_text())
    result = agent_eval_result_from_directory(
        ctx.skill,
        paths[0].parent,
        env_mode=options.env_mode,
        engine_result=payload,
        evaluated_source={"commit": ctx.revision},
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
    benchmark = paths[0].with_name("tier3-benchmark.md")
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
