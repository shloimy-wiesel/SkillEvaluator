"""Queue a project-scoped live evaluation."""

from typing import Annotated

from fastapi import Form, Request

from skillevaluator.provider_config import resolve_llm_provider

from .frontend_routes import document
from .live_job import COMPLETED, LIVE, Controls, snapshot
from .project_api import failure
from .providers import worker_environment
from .run_routes import feature, queued, redirect, register
from .runs import project_for
from .sandbox_profiles import LABELS, availability
from .workspace import WorkspaceError

browser, api = feature("live")


@browser.get("", name="live_index")
def index(request: Request, project_id: str):
    project_for(request, project_id)
    return document(request, "live.html")


@api.get("")
def settings(request: Request, project_id: str):
    project = project_for(request, project_id)
    try:
        judge = resolve_llm_provider(worker_environment(request.app.state.workspace, project.id, "chat")).model
    except ValueError:
        judge = None
    return {
        "project": project,
        "judge": judge,
        "profiles": [
            {"key": key, "label": label, "reason": availability(project.id, project.folder, project.revision, key)}
            for key, label in LABELS.items()
        ],
        "prior": [
            dict(row)
            for row in request.app.state.jobs.history(project.id)
            if row["kind"] == LIVE.kind and row["status"] in COMPLETED and row["folder"] == project.folder
        ],
    }


class Submission(Controls):
    sha: str


@api.post("", status_code=201)
def start(request: Request, project_id: str, body: Submission):
    project = project_for(request, project_id)
    controls = Controls(**body.model_dump(exclude={"sha"}))
    try:
        if controls.grading_mode not in (None, "default") and not controls.sandbox_grader_consent:
            raise WorkspaceError("Repository grading requires explicit sandbox consent.")
        options = snapshot(request.app.state.workspace, project_id, controls, body.sha)
        run_id = request.app.state.jobs.enqueue(project, body.sha, LIVE, options)
    except WorkspaceError as exc:
        raise failure(422, "invalid_inputs", str(exc)) from exc
    except ValueError as exc:
        raise failure(422, "missing_provider", "Configure a chat provider before queuing live trials.") from exc
    return queued(request, project_id, run_id)


@browser.post("")
def queue(request: Request, project_id: str, body: Annotated[Submission, Form()]):
    return redirect(start(request, project_id, body))


router = register(browser, api)
