from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from .gitlab import instance
from .workspace import WorkspaceError

router = APIRouter(prefix="/projects/{project_id}/gitlab")


def settings(request, project_id):
    ws = request.app.state.workspace
    project = ws.get(project_id)
    lab = project and instance(ws, project)
    if not lab:
        raise HTTPException(404, "No configured GitLab project.")
    return project, lab


def render(request, project, lab, **context):
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="gitlab.html",
        context={"project": project, "lab": lab, **context},
        status_code=422 if "error" in context else 200,
    )


@router.get("", name="gitlab_access")
def access(request: Request, project_id: str):
    return render(request, *settings(request, project_id))


@router.post("/token")
def token(request: Request, project_id: str, api_token: str = Form("")):
    project, lab = settings(request, project_id)
    try:
        lab.set_token(api_token)
    except WorkspaceError as exc:
        return render(request, project, lab, error=str(exc))
    return RedirectResponse(request.url_for("gitlab_access", project_id=project_id), 303)


@router.post("/check")
def check(request: Request, project_id: str):
    project, lab = settings(request, project_id)
    try:
        result = lab.request("GET")
        if not isinstance(result, dict) or result.get("path_with_namespace") != lab.namespace:
            raise WorkspaceError("GitLab did not confirm the configured project.")
    except WorkspaceError as exc:
        return render(request, project, lab, error=str(exc))
    return render(request, project, lab, notice="Project API read access confirmed. Write access was not tested.")
