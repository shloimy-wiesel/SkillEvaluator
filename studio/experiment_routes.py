"""Pinned experiment views and project-scoped JSON mutations."""

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ValidationError

from .experiment_jobs import DECOYS, INTERACTION, METRICS, DecoyControls, InteractionControls, Observations, freeze
from .frontend_routes import document
from .project_api import failure, get_project
from .workspace import WorkspaceError

router = APIRouter()
BASE = "/projects/{project_id}/experiments"
API = "/api/v1" + BASE


class ExperimentView(BaseModel):
    folder: str
    revision: str


class QueuedExperiment(BaseModel):
    run_id: str


class MetricsRequest(Observations):
    sha: str


class DecoysRequest(DecoyControls):
    sha: str


class InteractionRequest(InteractionControls):
    sha: str


@router.get(BASE, name="experiments")
def index(request: Request, project_id: str):
    get_project(request.app.state.workspace, project_id)
    return document(request, "experiments.html")


@router.get(API)
def experiment_view(request: Request, project_id: str) -> ExperimentView:
    project = get_project(request.app.state.workspace, project_id)
    return ExperimentView(folder=project.folder, revision=project.revision)


def enqueue(request, project_id, body, definition, controls_type, role=None):
    workspace = request.app.state.workspace
    project = get_project(workspace, project_id)
    controls = controls_type.model_validate(body.model_dump(exclude={"sha"}, mode="json"))
    try:
        options = freeze(workspace, project_id, role, controls, definition.options) if role else controls
        run = request.app.state.jobs.enqueue(project, body.sha, definition, options)
    except WorkspaceError as exc:
        raise failure(422, "invalid_experiment", str(exc)) from exc
    return QueuedExperiment(run_id=run)


@router.post(API + "/metrics", status_code=201)
def metrics(request: Request, project_id: str, body: MetricsRequest) -> QueuedExperiment:
    return enqueue(request, project_id, body, METRICS, Observations)


@router.post(API + "/decoys", status_code=201)
def decoys(request: Request, project_id: str, body: DecoysRequest) -> QueuedExperiment:
    return enqueue(request, project_id, body, DECOYS, DecoyControls, "embeddings")


@router.post(API + "/interaction", status_code=201)
def interaction(request: Request, project_id: str, body: InteractionRequest) -> QueuedExperiment:
    return enqueue(request, project_id, body, INTERACTION, InteractionControls, "chat")


@router.post(BASE + "/{action}", name="queue_experiment")
async def queue(request: Request, project_id: str, action: str):
    actions = {
        "metrics": (MetricsRequest, metrics),
        "decoys": (DecoysRequest, decoys),
        "interaction": (InteractionRequest, interaction),
    }
    if action not in actions:
        raise failure(404, "unknown_action", "Unknown experiment.")
    form = await request.form()
    data = {k: v for k, v in form.items() if v != ""}
    for key in ("skills", "exclude", "kata_dns"):
        if isinstance(data.get(key), str):
            data[key] = data[key].splitlines()
    if "agents" in data:
        data["agents"] = form.getlist("agents")
    model, handler = actions[action]
    try:
        body = model.model_validate(data)
    except ValidationError as exc:
        raise failure(422, "invalid_experiment", "Check repository paths and experiment settings.") from exc
    run = handler(request, project_id, body)
    return RedirectResponse(request.url_for("run_detail", project_id=project_id, run_id=run.run_id), 303)
