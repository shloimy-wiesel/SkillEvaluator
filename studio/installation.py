"""Inspect the installed CLI without accepting command lines or environment names."""

import subprocess
import sys
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from skillevaluator.cli import cli

from .changed_files import CHANGED, ChangedOptions, changed_paths
from .expert import choices_at
from .runs import project_for

router = APIRouter(prefix="/projects/{project_id}/installation")


def command_paths(command, path=()):
    yield " ".join(path) or "root", path
    for name, child in getattr(command, "commands", {}).items():
        yield from command_paths(child, (*path, name))


TOPICS = dict(command_paths(cli))


@lru_cache(maxsize=128)
def installed_output(args):
    return subprocess.check_output(
        [sys.executable, "-I", "-c", "from skillevaluator.cli import cli; cli()", *args],
        cwd="/",
        env={"LANG": "C.UTF-8", "NO_COLOR": "1", "TERM": "dumb"},
        stderr=subprocess.DEVNULL,
        timeout=20,
        text=True,
    ).strip()


@router.get("", name="installation")
def installation(request: Request, project_id: str, topic: str = "root"):
    project = project_for(request, project_id)
    if topic not in TOPICS:
        raise HTTPException(422, "Choose a listed help topic.")
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="installation.html",
        context={
            "project": project,
            "version": installed_output(("--version",)),
            "python": sys.version.split()[0],
            "changed": changed_paths(request.app.state.workspace, project),
            "configs": choices_at(request, project, project.revision),
            "topic": topic,
            "topics": TOPICS,
            "help": installed_output((*TOPICS[topic], "--help")),
        },
    )


@router.post("")
async def queue_changed(request: Request, project_id: str):
    project = project_for(request, project_id)
    data = await request.form()
    if data.get("sha") != project.revision:
        raise HTTPException(409, "The project revision changed. Reopen the changed-file list.")
    try:
        options = ChangedOptions(
            verbose=data.get("verbose", False),
            check=data.get("check"),
            paths=data.getlist("paths"),
            min_score=data.get("min_score") or 70,
            quality_config=data.get("quality_config") or None,
        )
        if set(options.paths) - set(changed_paths(request.app.state.workspace, project)):
            raise ValueError
        if options.quality_config and (
            options.check != "quality" or options.quality_config not in choices_at(request, project, project.revision)
        ):
            raise ValueError
    except ValueError as exc:
        raise HTTPException(422, "Choose listed changed paths and settings for the selected check.") from exc
    run = request.app.state.jobs.enqueue(project, project.revision, CHANGED, options)
    return RedirectResponse(request.url_for("run_detail", project_id=project_id, run_id=run), 303)
