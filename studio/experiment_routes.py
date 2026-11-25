from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from .experiment_jobs import DECOYS, INTERACTION, METRICS, DecoyControls, InteractionControls, freeze
from .runs import project_for
from .workspace import WorkspaceError

router = APIRouter(prefix="/projects/{project_id}/experiments")
ACTIONS = {"metrics": METRICS, "decoys": DECOYS, "interaction": INTERACTION}


def render(request, project, error=None):
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="experiments.html",
        context={"project": project, "error": error},
        status_code=422 if error else 200,
    )


@router.get("", name="experiments")
def index(request: Request, project_id: str):
    return render(request, project_for(request, project_id))


@router.post("/{action}", name="queue_experiment")
async def queue(request: Request, project_id: str, action: str):
    project = project_for(request, project_id)
    if action not in ACTIONS:
        raise HTTPException(404)
    definition = ACTIONS[action]
    form = await request.form()
    if any(not isinstance(value, str) for _, value in form.multi_items()):
        return render(request, project, "Choose committed project inputs by path.")
    data = {k: v for k, v in form.items() if k != "sha" and v != ""}
    try:
        if definition is DECOYS:
            if "exclude" in data:
                data["exclude"] = data["exclude"].splitlines()
            controls = DecoyControls.model_validate(data)
            options = freeze(request.app.state.workspace, project_id, "embeddings", controls, definition.options)
        elif definition is INTERACTION:
            data["skills"] = data.get("skills", "").splitlines()
            data["agents"] = form.getlist("agents")
            if "kata_dns" in data:
                data["kata_dns"] = data["kata_dns"].splitlines()
            controls = InteractionControls.model_validate(data)
            options = freeze(request.app.state.workspace, project_id, "chat", controls, definition.options)
        else:
            options = definition.options.model_validate(data)
        run = request.app.state.jobs.enqueue(project, form.get("sha", ""), definition, options)
    except ValidationError:
        return render(request, project, "Check repository paths and experiment settings.")
    except WorkspaceError as exc:
        return render(request, project, str(exc))
    return RedirectResponse(request.url_for("run_detail", project_id=project_id, run_id=run), 303)
