"""Author-facing job history and retained reports."""

import json
from typing import Literal

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from .expert_options import ACTIONS
from .static_job import STATIC, StaticOptions
from .workspace import WorkspaceError

router = APIRouter(prefix="/projects/{project_id}/runs")


def project_for(request, project_id):
    project = request.app.state.workspace.get(project_id)
    if project is None:
        raise HTTPException(404, "Unknown project")
    return project


def record_for(request, project_id, run_id):
    run = request.app.state.jobs.get(project_id, run_id)
    if run is None:
        raise HTTPException(404, "Unknown run")
    return run


@router.get("", name="runs_index")
def index(request: Request, project_id: str):
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="runs/index.html",
        context={
            "project": project_for(request, project_id),
            "runs": request.app.state.jobs.history(project_id),
            "actions": ACTIONS,
        },
    )


@router.post("")
def queue(
    request: Request, project_id: str, sha: str = Form(), checks: Literal["both", "schema", "unicode"] = Form("both")
):
    project = project_for(request, project_id)
    options = StaticOptions() if checks == "both" else StaticOptions(checks=(checks,))
    try:
        run_id = request.app.state.jobs.enqueue(project, sha, STATIC, options)
    except WorkspaceError as exc:
        return request.app.state.templates.TemplateResponse(
            request=request,
            name="runs/index.html",
            status_code=422,
            context={
                "project": project,
                "runs": request.app.state.jobs.history(project_id),
                "error": str(exc),
                "sha": sha,
                "checks": checks,
                "actions": ACTIONS,
            },
        )
    return RedirectResponse(request.url_for("run_detail", project_id=project_id, run_id=run_id), 303)


@router.get("/{run_id}", name="run_detail")
def detail(request: Request, project_id: str, run_id: str):
    run = record_for(request, project_id, run_id)
    report = json.loads(run["report"] or "{}")
    models = None
    if run["kind"] == "tier3-live-v1":
        from .live_job import LiveOptions, display_models

        models = display_models(LiveOptions.model_validate_json(run["options"]), report)
    response = request.app.state.templates.TemplateResponse(
        request=request,
        name="runs/detail.html",
        context={
            "project": project_for(request, project_id),
            "run": run,
            "report": report,
            "models": models,
        },
    )
    if run["status"] in {"queued", "running"}:
        response.headers["Refresh"] = "1"
    return response


@router.get("/{run_id}/exports/{kind}", name="run_export")
def export(request: Request, project_id: str, run_id: str, kind: str):
    run = record_for(request, project_id, run_id)
    if kind not in ("json", "md") or run["report"] is None:
        raise HTTPException(404, "Unknown export")
    return Response(
        run["report" if kind == "json" else "markdown"],
        media_type="application/json" if kind == "json" else "text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{run_id}.{kind}"', "X-Content-Type-Options": "nosniff"},
    )


@router.post("/{run_id}/rerun", name="run_again")
def rerun(request: Request, project_id: str, run_id: str):
    project = project_for(request, project_id)
    record_for(request, project_id, run_id)
    try:
        new_id = request.app.state.jobs.rerun(project, run_id)
    except WorkspaceError as exc:
        raise HTTPException(422, str(exc)) from exc
    return RedirectResponse(request.url_for("run_detail", project_id=project_id, run_id=new_id), 303)
