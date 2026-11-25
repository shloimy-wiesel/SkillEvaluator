"""Queue a project-scoped live evaluation."""

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from .live_job import LIVE, Controls, snapshot
from .runs import project_for
from .workspace import WorkspaceError

router = APIRouter(prefix="/projects/{project_id}/live")


def render(request, project, error=None):
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="live/index.html",
        context={"project": project, "error": error},
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
        options = snapshot(request.app.state.workspace, project_id, controls)
        run_id = request.app.state.jobs.enqueue(project, form.get("sha", ""), LIVE, options)
    except ValidationError:
        return render(request, project, "Check live settings, project paths, trial counts and budget prerequisites.")
    except WorkspaceError as exc:
        return render(request, project, str(exc))
    except ValueError:
        return render(request, project, "Configure a chat provider before queuing live trials.")
    return RedirectResponse(request.url_for("run_detail", project_id=project_id, run_id=run_id), 303)
