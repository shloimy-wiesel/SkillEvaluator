"""Inspect the installed CLI without accepting command lines or environment names."""

import subprocess
import sys
from functools import lru_cache
from typing import Annotated

from fastapi import Form, Request

from skillevaluator.cli import cli

from .changed_files import CHANGED, ChangedOptions, changed_paths
from .expert import choices_at
from .frontend_routes import document
from .project_api import failure
from .run_routes import feature, queued, redirect, register
from .runs import project_for
from .workspace import WorkspaceError

browser, api = feature("installation")


def command_paths(command, path=()):
    yield " ".join(path) or "root", path
    for name, child in getattr(command, "commands", {}).items():
        yield from command_paths(child, (*path, name))


TOPICS = dict(command_paths(cli))


def quality_configs(request, project):
    _, files = choices_at(request, project, project.revision, "quality-check")
    return files


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


@browser.get("", name="installation")
def form_page(request: Request, project_id: str):
    project_for(request, project_id)
    return document(request, "installation.html")


@api.get("")
def installation(request: Request, project_id: str, topic: str = "root"):
    project = project_for(request, project_id)
    if topic not in TOPICS:
        raise failure(422, "invalid_topic", "Choose a listed help topic.")
    diagnostics = []

    def inspect(section, operation, fallback):
        try:
            return operation()
        except subprocess.TimeoutExpired:
            message = "Inspection timed out."
        except (subprocess.CalledProcessError, OSError, WorkspaceError):
            message = "Inspection failed."
        diagnostics.append({"section": section, "message": message})
        return fallback

    return {
        "project": project,
        "version": inspect("version", lambda: installed_output(("--version",)), "Unavailable"),
        "python": sys.version.split()[0],
        "changed": inspect("changed", lambda: changed_paths(request.app.state.workspace, project), []),
        "configs": inspect("configs", lambda: quality_configs(request, project), []),
        "topic": topic,
        "topics": list(TOPICS),
        "help": inspect("help", lambda: installed_output((*TOPICS[topic], "--help")), "Help unavailable."),
        "diagnostics": diagnostics,
    }


class ChangedSubmission(ChangedOptions):
    sha: str


@api.post("", status_code=201)
def start(request: Request, project_id: str, body: ChangedSubmission):
    project = project_for(request, project_id)
    if body.sha != project.revision:
        raise failure(409, "stale_commit", "The project revision changed. Reopen the changed-file list.")
    try:
        options = ChangedOptions(**body.model_dump(exclude={"sha"}))
        if set(options.paths) - set(changed_paths(request.app.state.workspace, project)):
            raise ValueError
        if options.quality_config and (
            options.check != "quality" or options.quality_config not in quality_configs(request, project)
        ):
            raise ValueError
    except ValueError as exc:
        raise failure(
            422, "invalid_inputs", "Choose listed changed paths and settings for the selected check."
        ) from exc
    run = request.app.state.jobs.enqueue(project, body.sha, CHANGED, options)
    return queued(request, project_id, run)


@browser.post("")
def queue_changed(request: Request, project_id: str, body: Annotated[ChangedSubmission, Form()]):
    return redirect(start(request, project_id, body))


router = register(browser, api)
