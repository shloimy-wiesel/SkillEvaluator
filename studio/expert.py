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

from . import expert_profiles
from .expert_options import ACTIONS, CHECKS, FIELDS, FILES, HARNESSES, MULTI, REPORTS, ExpertOptions
from .jobs import JobDefinition, Outcome
from .runs import project_for, record_for
from .workspace import WorkspaceError

router = APIRouter(prefix="/projects/{project_id}/expert")
SUFFIXES = {".sarif.json": "SARIF", ".junit.xml": "JUnit", ".json": "JSON", ".md": "Markdown", ".html": "HTML"}


def evaluate(ctx, options):
    ctx.progress(ACTIONS[options.action])
    chat = expert_profiles.environment(ctx, options.chat)
    embeddings = expert_profiles.environment(ctx, options.embeddings)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        output = work / "reports"
        output.mkdir()
        args = options.arguments(replace(ctx, artifacts=output))
        return invoke(ctx, args, work, output, chat, embeddings)


def invoke(ctx, args, work, output, chat, embeddings):
    log = work / "console.txt"
    with log.open("wb") as console:
        done = subprocess.run(
            [sys.executable, "-I", str(Path(__file__).with_name("expert_worker.py")), *args],
            cwd=work,
            env={
                "LANG": "C.UTF-8",
                "PATH": "/usr/bin:/bin",
                "SKILLEVALUATOR_RUNTIME_DIR": "/",
                "SKILLEVALUATOR_SKILLSPECTOR_PATH": "/nonexistent",
                "HOME": "/nonexistent",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_NOSYSTEM": "1",
                **chat,
                **{k: os.environ[k] for k in ("SSL_CERT_FILE",) if k in os.environ},
            },
            stdout=console,
            stderr=subprocess.DEVNULL,
            timeout=180,
            input=json.dumps(embeddings).encode(),
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
    report = json.loads(sanitized(captured.read_bytes())) if captured.exists() else {}
    for path in sorted(output.iterdir()):
        if path.is_file() and not path.is_symlink():
            for suffix, label in SUFFIXES.items():
                if path.name.endswith(suffix):
                    native[path.name] = "Benchmark" if path.name == "BENCHMARK.md" else label
                    data = sanitized(path.read_bytes())
                    (ctx.artifacts / path.name).write_bytes(data)
                    if label == "JSON":
                        report = json.loads(data)
                    break
    terminal = sanitized(log.read_bytes()).decode(errors="replace")
    if done.returncode and not captured.exists():
        raise WorkspaceError(
            "Evaluator could not produce a result. Check configuration file contents and runtime prerequisites."
        )
    report.update(native=native, terminal=terminal)
    report.setdefault("results", [])
    status = report.get("overall_status", "failed" if done.returncode else "passed")
    md = work / "studio-result.md"
    return Outcome(
        status, done.returncode, json.dumps(report), sanitized(md.read_bytes()).decode() if md.exists() else terminal
    )


EXPERT = JobDefinition("expert-check-v1", ExpertOptions, evaluate)


@router.get("/{action}", name="expert_form")
def form(request: Request, project_id: str, action: str, sha: str = ""):
    if action not in ACTIONS:
        raise HTTPException(404)
    project = project_for(request, project_id)
    sha = sha or project.revision
    try:
        choices = choices_at(request, project, sha)
    except WorkspaceError as exc:
        return render(request, project, action, project.revision, [], error=str(exc))
    return render(request, project, action, sha, choices)


def choices_at(request, project, sha):
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", sha):
        raise WorkspaceError("Choose a full commit SHA in this project.")
    tree = request.app.state.workspace.git(project, ["ls-tree", "-rlz", sha])
    return sorted(
        name
        for entry in tree.split("\0")
        if entry.startswith(("100644 ", "100755 "))
        for header, name in [entry.split("\t", 1)]
        if int(header.split()[3]) <= 1024 * 1024
        and name.isprintable()
        and name.lower().endswith((".yaml", ".yml", ".json"))
    )


def render(request, project, action, sha, choices, error=None):
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="runs/expert.html",
        status_code=422 if error else 200,
        context={
            "project": project,
            "action": action,
            "label": ACTIONS[action],
            "formats": REPORTS,
            "checks": CHECKS,
            "fields": FIELDS[action],
            "files": FILES,
            "choices": choices,
            "harnesses": HARNESSES,
            "sha": sha,
            "error": error,
        },
    )


@router.post("/{action}")
async def queue(request: Request, project_id: str, action: str):
    project = project_for(request, project_id)
    if action not in ACTIONS:
        raise HTTPException(404)
    data = await request.form()
    sha = data.get("sha", "")
    choices = []
    try:
        choices = choices_at(request, project, sha)
        versions = {f"version_{h}" for h in HARNESSES} if action == "harness-check" else set()
        if set(data) - (FIELDS[action] - {"harness_versions"}) - {"sha"} - versions:
            raise ValueError
        options = ExpertOptions(
            action=action,
            harness_versions=tuple(f"{h}={data['version_' + h]}" for h in HARNESSES if data.get("version_" + h)),
            **{
                key: data.getlist(key) if key in MULTI else data[key]
                for key in data
                if key != "sha" and key not in versions and data[key]
            },
        )
        if any(path not in choices for key in FILES if (path := getattr(options, key))):
            raise WorkspaceError("Choose a configuration file listed at this commit.")
        options = expert_profiles.snapshot(request.app.state.workspace, project.id, options)
        run_id = request.app.state.jobs.enqueue(project, sha, EXPERT, options)
    except (ValueError, WorkspaceError) as exc:
        return render(
            request,
            project,
            action,
            sha if isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", sha) else project.revision,
            choices,
            error=str(exc)
            if isinstance(exc, WorkspaceError)
            else "Invalid settings for this check and tier selection.",
        )
    return RedirectResponse(request.url_for("run_detail", project_id=project_id, run_id=run_id), 303)


@router.get("/artifacts/{run_id}/{name}", name="expert_artifact")
def artifact(request: Request, project_id: str, run_id: str, name: str):
    row = record_for(request, project_id, run_id)
    if (
        row["kind"] != EXPERT.kind
        or name != Path(name).name
        or name not in json.loads(row["report"] or "{}").get("native", {})
    ):
        raise HTTPException(404)
    path = request.app.state.workspace.data_dir / "artifacts" / project_id / run_id / name
    return FileResponse(
        path, filename=name, media_type="application/octet-stream", headers={"X-Content-Type-Options": "nosniff"}
    )
