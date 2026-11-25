"""Queue a project-scoped live evaluation."""

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from skillevaluator.provider_config import resolve_llm_provider

from .live_job import COMPLETED, LIVE, Controls, snapshot
from .providers import worker_environment
from .runs import project_for
from .sandbox_profiles import LABELS, availability
from .workspace import WorkspaceError

router = APIRouter(prefix="/projects/{project_id}/live")


def render(request, project, error=None, selected="generated"):
    try:
        judge = resolve_llm_provider(worker_environment(request.app.state.workspace, project.id, "chat")).model
    except ValueError:
        judge = None
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="live/index.html",
        context={
            "project": project,
            "error": error,
            "selected": selected,
            "judge": judge,
            "profiles": [
                (key, label, availability(project.id, project.folder, project.revision, key))
                for key, label in LABELS.items()
            ],
            "prior": [
                row
                for row in request.app.state.jobs.history(project.id)
                if row["kind"] == LIVE.kind and row["status"] in COMPLETED and row["folder"] == project.folder
            ],
        },
        status_code=422 if error else 200,
    )


@router.get("", name="live_index")
def index(request: Request, project_id: str):
    return render(request, project_for(request, project_id))


@router.post("")
async def queue(request: Request, project_id: str):
    project = project_for(request, project_id)
    form = await request.form()
    data = {k: v for k, v in form.items() if k not in {"sha", "agents"} and v != ""}
    try:
        controls = Controls.model_validate({**data, "agents": form.getlist("agents")})
        if controls.grading_mode not in (None, "default") and not controls.sandbox_grader_consent:
            raise WorkspaceError("Repository grading requires explicit sandbox consent.")
        options = snapshot(request.app.state.workspace, project_id, controls, form.get("sha", ""))
        run_id = request.app.state.jobs.enqueue(project, form.get("sha", ""), LIVE, options)
    except ValidationError:
        return render(
            request,
            project,
            "Check live settings, project paths, trial counts and budget prerequisites.",
            form.get("sandbox_profile"),
        )
    except WorkspaceError as exc:
        return render(request, project, str(exc), form.get("sandbox_profile"))
    except ValueError:
        return render(
            request, project, "Configure a chat provider before queuing live trials.", form.get("sandbox_profile")
        )
    return RedirectResponse(request.url_for("run_detail", project_id=project_id, run_id=run_id), 303)
