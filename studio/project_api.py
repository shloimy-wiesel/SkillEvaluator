"""Versioned workspace endpoints. Never serialize credentials or a checkout path."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, SecretStr

from .gitlab import instance
from .navigation import task_groups
from .workspace import Project, WorkspaceError

router = APIRouter(prefix="/api/v1/projects")


class Connection(BaseModel):
    remote: str = Field(max_length=8192)
    folder: str = Field(default=".", max_length=4096)
    username: str = Field(default="", max_length=1024)
    token: SecretStr = Field(default=SecretStr(""), max_length=16384)
    gitlab_root: str = Field(default="", max_length=8192)
    ca_pem: str = Field(default="", max_length=262144)


class Action(BaseModel):
    label: str
    href: str


class Group(BaseModel):
    title: str
    hint: str
    actions: list[Action]


class Overview(BaseModel):
    project: Project
    groups: list[Group]
    gitlab: bool


def failure(status, code, message):
    return HTTPException(status, {"code": code, "message": message})


def get_project(workspace, project_id):
    project = workspace.get(project_id)
    if not project:
        raise failure(404, "unknown_project", "Unknown project.")
    return project


@router.get("")
def projects(request: Request) -> list[Project]:
    return request.app.state.workspace.projects()


@router.post("", status_code=201)
def connect(request: Request, body: Connection) -> Project:
    workspace = request.app.state.workspace
    try:
        project_id = workspace.connect(
            body.remote,
            body.folder,
            body.username,
            body.token.get_secret_value(),
            gitlab_root=body.gitlab_root,
            ca_pem=body.ca_pem,
        )
    except WorkspaceError as exc:
        raise failure(422, "connection_failed", str(exc)) from exc
    return get_project(workspace, project_id)


@router.get("/{project_id}")
def overview(request: Request, project_id: str) -> Overview:
    workspace = request.app.state.workspace
    project = get_project(workspace, project_id)
    groups = [
        Group(
            title=title,
            hint=hint,
            actions=[
                Action(label=label, href=str(request.app.url_path_for(route, project_id=project_id)) + fragment)
                for label, route, fragment in entries
            ],
        )
        for title, hint, entries in task_groups(request.app.state.project_links)
    ]
    return Overview(project=project, groups=groups, gitlab=bool(instance(workspace, project)))


@router.post("/{project_id}/check")
def check(request: Request, project_id: str) -> dict[str, str]:
    workspace = request.app.state.workspace
    project = get_project(workspace, project_id)
    try:
        workspace.git(project, ["ls-remote", "--exit-code", "--", project.remote, "HEAD"], authenticated=True)
    except WorkspaceError as exc:
        raise failure(422, "remote_access_failed", str(exc)) from exc
    return {"message": "Remote access confirmed."}
