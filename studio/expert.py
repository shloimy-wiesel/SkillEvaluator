"""Run the installed evaluator with command-scoped, frozen form settings."""

import html
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, create_model

from . import expert_catalog, expert_profiles, live_job
from .expert_options import ACTIONS, ALIASES, CHECKS, FIELDS, FILES, HARNESSES, MULTI, REPORTS, ExpertOptions
from .frontend_routes import document
from .jobs import JobDefinition, Outcome
from .operator_env import operator_env
from .project_api import failure, get_project
from .runs import project_for, record_for
from .worker_deadline import WorkerTimeout, bounded_worker, run_evaluator
from .workspace import WorkspaceError

router = APIRouter()
BASE = "/projects/{project_id}/expert"
API = "/api/v1" + BASE
SUFFIXES = {".sarif.json": "SARIF", ".junit.xml": "JUnit", ".json": "JSON", ".md": "Markdown", ".html": "HTML"}


@bounded_worker
def evaluate(ctx, options):
    ctx.progress(ACTIONS[options.action])
    chat = expert_profiles.environment(ctx, options.chat)
    embeddings = expert_profiles.environment(ctx, options.embeddings)
    with tempfile.TemporaryDirectory(dir=ctx.root.parent) as tmp:
        work = Path(tmp)
        output = work / "reports"
        output.mkdir()
        target = replace(ctx, artifacts=output)
        runtime = {}
        reason = None
        members = {}
        starters = []
        if options.live:
            target, members, starters = expert_catalog.prepare(target, work, options)
            home = work / "home"
            home.mkdir()
            runtime = {
                **{
                    k: os.environ[k]
                    for k in ("DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH")
                    if k in os.environ
                },
                "HOME": str(home),
                "TMPDIR": str(work),
                "PYTHON_DOTENV_DISABLED": "1",
                "PATH": f"{Path(sys.executable).parent}:/usr/local/bin:/usr/bin:/bin",
                "SKILLEVALUATOR_OUTPUT_PROVENANCE_KEY_FILE": str(ctx.workspace.data_dir / "tier3-output.key"),
            }
        args = options.arguments(target)
        if options.live:
            args += ["--results-dir", str(ctx.artifacts / "tier3")]
            if not options.include_revision:
                args += ["--evaluated-source-revision", ctx.revision]
            try:
                if any(error is None for error in members.values()):
                    live_job.sandbox_preflight(work, runtime)
            except WorkerTimeout:
                raise
            except WorkspaceError as exc:
                reason = str(exc)
        try:
            outcome = invoke(
                ctx,
                args,
                work,
                output,
                chat=chat,
                embeddings=embeddings,
                runtime=runtime,
                reason=reason,
                members=members,
            )
        finally:
            if options.live:
                secrets = {
                    text.encode()
                    for k, v in (*chat.items(), *embeddings.items())
                    if k.endswith("_KEY") and v
                    for text in (v, json.dumps(v)[1:-1], html.escape(v))
                }
                for path in (ctx.artifacts / "tier3").rglob("*"):
                    if not path.is_symlink() and path.is_file():
                        live_job.redact_file(path, secrets)
        return expert_catalog.retain(ctx.workspace, starters, outcome) if starters else outcome


def invoke(ctx, args, work, output, *, chat, embeddings, runtime, reason, members=None):
    log = work / "console.txt"
    with log.open("wb") as console:
        done = run_evaluator(
            [sys.executable, "-I", str(Path(__file__).with_name("expert_worker.py")), *args],
            cwd=work,
            env={
                "LANG": "C.UTF-8",
                "PATH": "/usr/bin:/bin",
                "SKILLEVALUATOR_RUNTIME_DIR": "/",
                # Native static scanning can use an installed pinned scanner.
                # External model transports cannot inherit a Studio chat key.
                **({"SKILLEVALUATOR_SKILLSPECTOR_PATH": "/nonexistent"} if chat else {}),
                "HOME": "/nonexistent",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_NOSYSTEM": "1",
                **runtime,
                **chat,
                **operator_env("SSL_CERT_FILE"),
            },
            stdout=console,
            stderr=subprocess.DEVNULL,
            sandbox=bool(runtime),
            limit=None if runtime else 180,
            input=json.dumps(
                {"embeddings": embeddings, "live": bool(runtime), "preflight_error": reason, "members": members or {}}
            ).encode(),
        )
    if done.returncode not in (0, 1):
        raise WorkspaceError("Evaluator rejected the selected settings or could not finish.")

    def sanitized(data):
        for name, value in (*chat.items(), *embeddings.items()):
            if name.endswith("_KEY") and value:
                for text in (json.dumps(value)[1:-1], html.escape(value), value):
                    data = data.replace(text.encode(), b"[redacted]")
        return data.replace((str(ctx.root) + "/").encode(), b"").replace(str(work).encode(), b"run")

    native = {}
    captured = work / "studio-result.json"
    is_catalog = (output / "catalog-summary.json").is_file()
    report = json.loads(sanitized(captured.read_bytes())) if captured.exists() and not is_catalog else {}
    for path in sorted(output.rglob("*")):
        if path.is_file() and not path.is_symlink():
            for suffix, label in SUFFIXES.items():
                if path.name.endswith(suffix):
                    rel = path.relative_to(output)
                    display = "Benchmark" if path.name == "BENCHMARK.md" else label
                    catalog = rel.as_posix() == "catalog-summary.json"
                    native[str(rel)] = ("Catalog summary" if catalog else display) + (
                        f" · {rel.parent}" if rel.parent.parts else ""
                    )
                    data = sanitized(path.read_bytes())
                    dest = ctx.artifacts / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
                    if label == "JSON" and not rel.parent.parts:
                        report = json.loads(data)
                    break
    terminal = sanitized(log.read_bytes()).decode(errors="replace")
    if done.returncode and not captured.exists() and "catalog-summary.json" not in native:
        raise WorkspaceError(
            "Evaluator could not produce a result. Check configuration file contents and runtime prerequisites."
        )
    report.update(native=native, terminal=terminal)
    report.setdefault("results", [])
    status = report.get("overall_status", "failed" if done.returncode else "passed")
    md = work / "studio-result.md"
    return Outcome(
        status,
        done.returncode,
        json.dumps(report),
        sanitized(md.read_bytes()).decode() if md.exists() and not is_catalog else terminal,
    )


EXPERT = JobDefinition("expert-check-v1", ExpertOptions, evaluate)


def known_action(action):
    if action not in ACTIONS:
        raise failure(404, "unknown_action", "Unknown expert check.")


@router.get(BASE + "/{action}", name="expert_form")
def form(request: Request, project_id: str, action: str):
    project_for(request, project_id)
    known_action(action)
    return document(request, "expert.html")


def choices_at(request, project, sha, action):
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", sha):
        raise WorkspaceError("Choose a full commit SHA in this project.")
    tree = request.app.state.workspace.git(project, ["ls-tree", "-rlz", sha])
    dirs, skills, blocked, files = set(), set(), set(), []
    for entry in tree.split("\0"):
        if not entry:
            continue
        header, name = entry.split("\t", 1)
        path = Path(name)
        if not header.startswith(("100644 ", "100755 ")) or not name.isprintable():
            blocked.update(path.parents)
            continue
        dirs.update(path.parents)
        if path.name == "SKILL.md":
            skills.add(path.parent)
        if int(header.split()[3]) <= 1024 * 1024 and path.suffix.lower() in (".yaml", ".yml", ".json"):
            files.append(name)
    allowed = skills if action in ("tier1", "tier1-validate") else dirs
    return sorted(str(p) for p in allowed - blocked), sorted(files)


class ExpertView(BaseModel):
    action: str
    label: str
    sha: str
    folder: str
    fields: list[str]
    directories: list[str]
    choices: list[str]
    file_labels: dict[str, str]
    checks: tuple[str, ...]
    reports: tuple[str, ...]
    harnesses: tuple[str, ...]


@router.get(API + "/{action}")
def expert_view(request: Request, project_id: str, action: str, sha: str = "") -> ExpertView:
    project = get_project(request.app.state.workspace, project_id)
    known_action(action)
    sha = sha or project.revision
    try:
        directories, files = choices_at(request, project, sha, action)
    except WorkspaceError as exc:
        raise failure(422, "invalid_revision", str(exc)) from exc
    return ExpertView(
        action=ALIASES.get(action, action),
        label=ACTIONS[action],
        sha=sha,
        folder=project.folder,
        fields=sorted(FIELDS[action]),
        directories=directories,
        choices=files,
        file_labels=FILES,
        checks=CHECKS,
        reports=REPORTS,
        harnesses=HARNESSES,
    )


# Reuse the evaluator's public field types without exposing frozen service-only inputs.
ExpertSubmission = create_model(
    "ExpertSubmission",
    __config__=ConfigDict(extra="forbid"),
    sha=(str, ...),
    **{
        key: (field.annotation, field)
        for key, field in ExpertOptions.model_fields.items()
        if key in set.union(*FIELDS.values())
    },
)


class QueuedCheck(BaseModel):
    run_id: str


@router.post(API + "/{action}", status_code=201)
def queue_json(request: Request, project_id: str, action: str, body: ExpertSubmission) -> QueuedCheck:
    project = get_project(request.app.state.workspace, project_id)
    known_action(action)
    data = body.model_dump(exclude_unset=True, exclude={"sha"})
    try:
        if data.keys() - FIELDS[action]:
            raise ValueError
        options = ExpertOptions(action=action, **data)
        dirs, files = choices_at(request, project, body.sha, action)
        if any(path not in dirs for path in (options.target, options.catalog_root) if path):
            raise WorkspaceError("Choose an unlinked directory listed at this commit.")
        if options.catalog_root and not Path(options.target or project.folder).is_relative_to(options.catalog_root):
            raise WorkspaceError("Catalog root must contain the target.")
        if any(path not in files for key in FILES if (path := getattr(options, key))):
            raise WorkspaceError("Choose a configuration file listed at this commit.")
        options = expert_profiles.snapshot(request.app.state.workspace, project.id, options)
        run = request.app.state.jobs.enqueue(project, body.sha, EXPERT, options)
    except (ValueError, WorkspaceError) as exc:
        message = str(exc) if isinstance(exc, WorkspaceError) else "Invalid settings for this check and tier selection."
        raise failure(422, "invalid_check", message) from exc
    return QueuedCheck(run_id=run)


@router.post(BASE + "/{action}")
async def queue(request: Request, project_id: str, action: str):
    known_action(action)
    form = await request.form()
    versions = {f"version_{h}" for h in HARNESSES} if action == "harness-check" else set()
    if set(form) - (FIELDS[action] - {"harness_versions"}) - {"sha"} - versions:
        raise failure(422, "invalid_check", "Invalid settings for this check.")
    data = {k: form.getlist(k) if k in MULTI else v for k, v in form.items() if v and k not in versions}
    if versions:
        data["harness_versions"] = [f"{k[8:]}={form[k]}" for k in versions if form.get(k)]
    try:
        body = ExpertSubmission.model_validate(data)
    except ValueError as exc:
        raise failure(422, "invalid_check", "Invalid settings for this check.") from exc
    queued = queue_json(request, project_id, action, body)
    return RedirectResponse(request.url_for("run_detail", project_id=project_id, run_id=queued.run_id), 303)


@router.get(BASE + "/artifacts/{run_id}/{name:path}", name="expert_artifact")
def artifact(request: Request, project_id: str, run_id: str, name: str):
    row = record_for(request, project_id, run_id)
    if (
        row["kind"] != EXPERT.kind
        or Path(name).is_absolute()
        or ".." in Path(name).parts
        or name not in json.loads(row["report"] or "{}").get("native", {})
    ):
        raise HTTPException(404)
    path = request.app.state.workspace.data_dir / "artifacts" / project_id / run_id / name
    if not path.is_file() or path.is_symlink():
        raise HTTPException(404)
    return FileResponse(
        path, filename=name, media_type="application/octet-stream", headers={"X-Content-Type-Options": "nosniff"}
    )
