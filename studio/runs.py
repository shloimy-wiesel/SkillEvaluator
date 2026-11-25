"""Author-facing job history and immutable retained reports."""

import json
from typing import Annotated, Literal

from fastapi import Form, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict

from .expert_options import ACTIONS
from .frontend_routes import document
from .project_api import failure, get_project
from .run_display import RunDisplay, RunStatus, configuration
from .run_routes import feature, queued, redirect, register
from .static_job import STATIC, StaticOptions
from .workspace import WorkspaceError

browser, api = feature("runs")


def project_for(request, project_id):
    return get_project(request.app.state.workspace, project_id)


def record_for(request, project_id, run_id):
    run = request.app.state.jobs.get(project_id, run_id)
    if run is None:
        raise failure(404, "unknown_run", "Unknown run.")
    return run


@browser.get("", name="runs_index")
def index(request: Request, project_id: str):
    project_for(request, project_id)
    return document(request, "runs.html")


@api.get("")
def history(request: Request, project_id: str):
    return {
        "project": project_for(request, project_id),
        "runs": [dict(row) for row in request.app.state.jobs.history(project_id)],
        "actions": ACTIONS,
    }


class StaticSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sha: str
    checks: Literal["both", "schema", "unicode"] = "both"


@api.post("", status_code=201)
def start(request: Request, project_id: str, body: StaticSubmission):
    project = project_for(request, project_id)
    options = StaticOptions() if body.checks == "both" else StaticOptions(checks=(body.checks,))
    try:
        run_id = request.app.state.jobs.enqueue(project, body.sha, STATIC, options)
    except WorkspaceError as exc:
        raise failure(422, "invalid_inputs", str(exc)) from exc
    return queued(request, project_id, run_id)


@browser.post("")
def queue(request: Request, project_id: str, form: Annotated[StaticSubmission, Form()]):
    return redirect(start(request, project_id, form))


@browser.get("/{run_id}", name="run_detail")
def detail(request: Request, project_id: str, run_id: str):
    record_for(request, project_id, run_id)
    return document(request, "run-status.html")


@api.get("/{run_id}", response_model=RunStatus)
def status(request: Request, project_id: str, run_id: str):
    project = project_for(request, project_id)
    run = record_for(request, project_id, run_id)
    report = json.loads(run["report"] or "null")
    options = json.loads(run["options"])
    models = None
    if run["kind"] == "tier3-live-v1":
        from .live_job import LiveOptions, display_models

        models = display_models(LiveOptions.model_validate(options), report or {})
    definition = request.app.state.jobs.definitions.get(run["kind"])
    display = RunDisplay(
        **{key: run[key] for key in RunDisplay.model_fields if key != "options"},
        options=configuration(run["kind"], options, definition.public_options if definition else ()),
    )
    return {"project": project, "run": display, "report": report, "models": models}


@browser.get("/{run_id}/exports/{kind}", name="run_export")
def export(request: Request, project_id: str, run_id: str, kind: str):
    run = record_for(request, project_id, run_id)
    if kind not in ("json", "md") or run["report"] is None:
        raise HTTPException(404, "Unknown export")
    return Response(
        run["report" if kind == "json" else "markdown"],
        media_type="application/json" if kind == "json" else "text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{run_id}.{kind}"', "X-Content-Type-Options": "nosniff"},
    )


@api.post("/{run_id}/rerun", status_code=201)
def again(request: Request, project_id: str, run_id: str):
    project = project_for(request, project_id)
    record_for(request, project_id, run_id)
    try:
        new_id = request.app.state.jobs.rerun(project, run_id)
    except WorkspaceError as exc:
        raise failure(422, "invalid_inputs", str(exc)) from exc
    return queued(request, project_id, new_id)


@browser.post("/{run_id}/rerun", name="run_again")
def rerun(request: Request, project_id: str, run_id: str):
    return redirect(again(request, project_id, run_id))


router = register(browser, api)
