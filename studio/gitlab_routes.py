"""Project-scoped GitLab connection settings; tokens are write-only."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, SecretStr

from .frontend_routes import document
from .gitlab import instance
from .project_api import failure, get_project
from .workspace import WorkspaceError

router = APIRouter()
PAGE = "/projects/{project_id}/gitlab"
API = "/api/v1" + PAGE


class Access(BaseModel):
    root: str
    namespace: str
    web_url: str


class Token(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_token: SecretStr


class Notice(BaseModel):
    notice: str


def settings(request, project_id):
    ws = request.app.state.workspace
    lab = instance(ws, get_project(ws, project_id))
    if not lab:
        raise failure(404, "gitlab_not_configured", "No configured GitLab project.")
    return lab


@router.get(PAGE, name="gitlab_access", include_in_schema=False)
def access(request: Request, project_id: str):
    settings(request, project_id)
    return document(request, "gitlab.html")


@router.get(API)
def coordinates(request: Request, project_id: str) -> Access:
    lab = settings(request, project_id)
    return Access(root=lab.root, namespace=lab.namespace, web_url=lab.web_url)


@router.post(API + "/token")
def token(request: Request, project_id: str, form: Token) -> Notice:
    lab = settings(request, project_id)
    try:
        lab.set_token(form.api_token.get_secret_value())
    except WorkspaceError as exc:
        raise failure(422, "invalid_token", str(exc)) from exc
    return Notice(notice="API token saved." if form.api_token.get_secret_value() else "API token removed.")


@router.post(API + "/check")
def check(request: Request, project_id: str) -> Notice:
    lab = settings(request, project_id)
    try:
        result = lab.request("GET")
        if not isinstance(result, dict) or result.get("path_with_namespace") != lab.namespace:
            raise WorkspaceError("GitLab did not confirm the configured project.")
    except WorkspaceError as exc:
        raise failure(422, "gitlab_check_failed", str(exc)) from exc
    return Notice(notice="Project API read access confirmed. Write access was not tested.")
