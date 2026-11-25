"""Project-scoped Tier 3 experiments. Outputs are retained separately from live evaluations."""

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import replace
from html import escape
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, IPvAnyAddress, model_validator

from skillevaluator.provider_config import resolve_embedding_provider, resolve_llm_provider
from skillevaluator.reporting.external_metrics import import_external_metrics
from skillevaluator.tier3.evals_config import encode_environment_kwarg

from . import live_job
from .jobs import JobDefinition, Outcome
from .live_job import Agent, Controls, Model, Positive
from .providers import worker_environment
from .workspace import WorkspaceError


def relative(value):
    if (
        len(value) > 1024
        or not value.isprintable()
        or "\\" in value
        or any(p.lower() in {"", ".", "..", ".git"} for p in value.split("/"))
    ):
        raise ValueError("Choose a repository-relative path.")
    return value


Relative = Annotated[str, AfterValidator(relative)]


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Observations(Settings):
    source: Relative


def metrics(ctx, options):
    output = ctx.artifacts / "observations"
    try:
        import_external_metrics(ctx.input_file(options.source), output)
    except ValueError as exc:
        raise WorkspaceError("Invalid external observations. Check the engine JSON contract.") from exc
    return Outcome(
        "neutral", 0, (output / "external_metrics.json").read_text(), (output / "external_metrics.md").read_text()
    )


METRICS = JobDefinition("external-metrics-v1", Observations, metrics)


Directory = Annotated[str, AfterValidator(lambda value: value if value == "." else relative(value))]


class DecoyControls(Settings):
    catalog: Relative
    catalog_root: Directory
    count: Annotated[int, Field(ge=1, le=1000)] = 4
    exclude: tuple[Relative, ...] = ()
    model: Model | None = None


class Profile(Settings):
    profile_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    provider: str
    profile_model: str
    endpoint: str


class Decoys(DecoyControls, Profile):
    pass


def profile_dir(workspace, project_id):
    return workspace.data_dir / "experiment-profiles" / project_id


def freeze(workspace, project_id, role, controls, option_type):
    try:
        env = worker_environment(workspace, project_id, role)
        resolver = resolve_embedding_provider if role == "embeddings" else resolve_llm_provider
        config = resolver(env)
    except ValueError as exc:
        raise WorkspaceError(f"Configure a project {role} provider first.") from exc
    if not config.api_key or config.api_key in controls.model_dump_json():
        raise WorkspaceError("Use a key-backed provider and keep credentials out of experiment settings.")
    prefix = "SKILL_EVAL_EMBEDDING_" if role == "embeddings" else "SKILL_EVAL_LLM_"
    env[prefix + "MODEL"] = config.model
    ident = uuid4().hex
    folder = profile_dir(workspace, project_id)
    folder.mkdir(mode=0o700, exist_ok=True, parents=True)
    (folder / ident).write_bytes(workspace.cipher.encrypt(json.dumps(env).encode()))
    return option_type(
        **controls.model_dump(),
        profile_id=ident,
        provider=config.provider,
        profile_model=config.model,
        endpoint=config.base_url or "",
    )


def environment(ctx, options, base):
    path = profile_dir(ctx.workspace, ctx.project_id) / options.profile_id
    creds = json.loads(ctx.workspace.cipher.decrypt(path.read_bytes()))
    home = base / "home"
    home.mkdir()
    return {
        **creds,
        **{k: os.environ[k] for k in ("SSL_CERT_FILE",) if k in os.environ},
        "HOME": str(home),
        "PATH": f"{Path(sys.executable).parent}:/usr/local/bin:/usr/bin:/bin",
        "TMPDIR": str(base),
        "PYTHON_DOTENV_DISABLED": "1",
        "LANG": "C.UTF-8",
    }


def directory(ctx, value):
    path = ctx.root if value == "." else ctx.root / relative(value)
    if path != path.resolve() or not path.is_dir():
        raise WorkspaceError("Selected directory is absent or linked at this commit.")
    return path


def select(ctx, options):
    root = directory(ctx, options.catalog_root)
    if not (root.is_relative_to(ctx.skill.parent) or ctx.skill.parent.is_relative_to(root)):
        raise WorkspaceError("Use a catalog root under or containing the skill collection for a portable manifest.")
    manifest = ctx.artifacts / "decoys.json"
    args = [
        "tier3",
        "select-decoys",
        str(ctx.skill),
        "--catalog",
        str(ctx.input_file(options.catalog)),
        "--catalog-root",
        str(root),
        "--count",
        str(options.count),
        "--output",
        str(manifest),
    ]
    for value in options.exclude:
        args += ["--exclude", value]
    if options.model:
        args += ["--model", options.model]
    with tempfile.TemporaryDirectory(dir=ctx.root.parent) as temp:
        base = Path(temp)
        ctx.progress("Ranking catalog neighbors")
        code = subprocess.run(
            [sys.executable, "-I", "-c", "from skillevaluator.cli import cli; cli()", *args],
            cwd=base,
            env=environment(ctx, options, base),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=180,
        ).returncode
    if code:
        raise WorkspaceError("Decoy selection failed. Check catalog identity, provider, eligible count and exclusions.")
    text = manifest.read_text()
    names = "\n".join("- " + s["path"] for s in json.loads(text)["selected"])
    return Outcome("neutral", 0, text, "# Selected decoys\n\n" + names + "\n")


DECOYS = JobDefinition("select-decoys-v1", Decoys, select)


class InteractionControls(Settings):
    skills: Annotated[tuple[Directory, ...], Field(min_length=2, max_length=32)]
    eval_source: Directory
    agents: tuple[Agent, ...] = ()
    model: Model | None = None
    env_mode: Literal["docker", "kata"] = "docker"
    kata_runtime: Literal["kata", "kata-qemu", "kata-clh"] | None = None
    kata_dns: tuple[IPvAnyAddress, ...] = ()
    harbor_keep_jobs: bool = False
    metric: Literal["goal_accuracy", "accuracy", "overall"] = "goal_accuracy"
    n_attempts: Positive = 1
    n_concurrent: Positive | None = None

    @model_validator(mode="after")
    def validate_backend(self):
        if self.env_mode != "kata" and (self.kata_runtime or self.kata_dns):
            raise ValueError("Kata settings require the Kata backend.")
        if any("%" in str(server) for server in self.kata_dns):
            raise ValueError("Choose unscoped DNS addresses.")
        return self


class Interaction(InteractionControls, Profile):
    pass


def interact(ctx, options):
    from skillevaluator.tier3.decoy_identity import decoy_source_copy_ignore
    from skillevaluator.tier3.harbor.secure_copy import copytree_secure
    from skillevaluator.utils.path_security import find_git_repo_root

    selected = [directory(ctx, item) for item in options.skills]
    source = directory(ctx, options.eval_source)
    for path in {*selected, source}:
        if not (path / "SKILL.md").is_file() or any(p.is_symlink() for p in path.rglob("*")):
            raise WorkspaceError("Each experiment folder must contain a skill and be free of symbolic links.")
    if len({p.name.casefold() for p in selected}) != len(selected) or any(
        parent in selected for p in selected for parent in p.parents
    ):
        raise WorkspaceError("Select distinct, non-overlapping skill folders.")
    output = ctx.artifacts / "interactions"
    # Unlike live evaluate, interact creates additional private skill roots
    # under TMPDIR. Git discovery there must fall back to each member's own
    # directory, never to an unrelated checkout containing the Studio volume.
    scratch = ctx.root.parent if find_git_repo_root(ctx.root.parent) is None else None
    with tempfile.TemporaryDirectory(dir=scratch) as temp:
        base = Path(temp)
        if find_git_repo_root(base) is not None:
            raise WorkspaceError("Interaction trials require a temporary directory outside any Git checkout.")
        suite = live_job.stage(replace(ctx, skill=source), base, Controls())
        members = base / "members"
        members.mkdir()
        for path in selected:
            copytree_secure(path, members / path.name, allowed_root=path, ignore=decoy_source_copy_ignore(path))
        args = [
            "tier3",
            "interact",
            *(str(members / p.name) for p in selected),
            "--eval-source",
            str(suite),
            "--results-dir",
            str(output),
            "--env-mode",
            options.env_mode,
            "--metric",
            options.metric,
            "--n-attempts",
            str(options.n_attempts),
        ]
        if options.n_concurrent is not None:
            args += ["--n-concurrent", str(options.n_concurrent)]
        if options.kata_runtime:
            args += ["--environment-kwarg", encode_environment_kwarg("kata_runtime", options.kata_runtime)]
        if options.kata_dns:
            args += ["--environment-kwarg", encode_environment_kwarg("kata_dns", list(map(str, options.kata_dns)))]
        if options.harbor_keep_jobs:
            args.append("--harbor-keep-jobs")
        if options.model:
            args += ["--model", options.model]
        if options.agents:
            args += ["--agents", ",".join(options.agents)]
        env = environment(ctx, options, base)
        env.update(
            {k: os.environ[k] for k in ("DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH") if k in os.environ}
        )
        env["SKILLEVALUATOR_OUTPUT_PROVENANCE_KEY_FILE"] = str(ctx.workspace.data_dir / "tier3-output.key")
        secrets = {
            s.encode()
            for k, v in env.items()
            if k.endswith("_API_KEY") and v
            for s in (v, json.dumps(v)[1:-1], escape(v))
        }
        ctx.progress("Running baseline, individual skills and combined configuration")
        try:
            code = live_job.invoke_engine(args, base, env)
        finally:
            for file in output.rglob("*"):
                if not file.is_symlink() and file.is_file():
                    live_job.redact_file(file, secrets)
    reports = [p for p in output.glob("interaction_*/interaction.json") if p.resolve() == p and p.is_file()]
    if len(reports) != 1:
        raise WorkspaceError(
            "No interaction report was produced. Verify the fixed suite, metric, selected skills and sandbox."
        )
    text = reports[0].read_text()
    report = json.loads(text)
    summary = f"# Skill interaction · {report['status']}\n\nMetric: {options.metric}\n"
    if options.harbor_keep_jobs:
        native = reports[0].parent
        retained = sorted(
            p.relative_to(native).as_posix() for p in native.glob("*/*/_harbor-jobs") if p.resolve() == p and p.is_dir()
        )
        summary += "\nRetained Harbor job directories (relative to the interaction report):\n"
        summary += "\n".join("- " + path for path in retained) or "None produced."
        summary += "\n"
    for reason in report.get("reasons", []):
        summary += "\n- " + reason
    for name, agent in report.get("agents", {}).items():
        summary += f"\n- {name}: {agent.get('classification', agent['status'])}"
        if agent.get("interaction") is not None:
            summary += f" ({agent['interaction']:+.4f})"
    return Outcome("neutral" if code == 0 and report["status"] == "complete" else "incomplete", code, text, summary)


INTERACTION = JobDefinition("skill-interaction-v1", Interaction, interact)
