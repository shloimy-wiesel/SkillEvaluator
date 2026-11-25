from difflib import unified_diff

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from .editing import Conflict, branches, commit_changes, open_branch, read_file, require_base
from .frontend_routes import document
from .project_api import failure, get_project
from .workspace import Project, WorkspaceError

router = APIRouter()
path = "/projects/{project_id}/edit"
api = "/api/v1" + path


class EditorView(BaseModel):
    project: Project
    text: str | None = None
    heads: dict[str, str] = {}
    error: str | None = None


def _project(request, project_id):
    ws = request.app.state.workspace
    p = ws.get(project_id)
    if p is None:
        raise HTTPException(404, "Unknown project")
    return ws, p


def _render(request, p, error=None, **context):
    try:
        heads = branches(request.app.state.workspace, p)
    except WorkspaceError as exc:
        heads, error = [], error or exc
    if "text" not in context:
        try:
            context["text"] = _text(request.app.state.workspace, p)
        except WorkspaceError as exc:
            error = error or exc
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="editor/index.html",
        context=dict(project=p, heads=heads, error=error, **context),
        status_code=409 if isinstance(error, Conflict) else 422 if error else 200,
    )


@router.get(path, name="skill_editor", include_in_schema=False)
def editor(request: Request, project_id: str):
    _project(request, project_id)
    return document(request, "edit.html")


@router.get(api)
def editor_view(request: Request, project_id: str) -> EditorView:
    ws = request.app.state.workspace
    p = get_project(ws, project_id)
    view = EditorView(project=p)
    try:
        view.heads = branches(ws, p)
    except WorkspaceError as exc:
        view.error = str(exc)
    try:
        view.text = _text(ws, p)
    except WorkspaceError as exc:
        view.error = view.error or str(exc)
    return view


def _text(ws, p):
    content = read_file(ws, p, "SKILL.md")
    if content is None:
        raise WorkspaceError("SKILL.md is missing on this branch.")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkspaceError("SKILL.md must be UTF-8 text.") from exc


def _api_error(exc):
    return failure(409, "conflict", str(exc)) if isinstance(exc, Conflict) else failure(422, "edit_failed", str(exc))


@router.post(api + "/changes", name="api_skill_changes", response_model=dict[str, str])
@router.post(path + "/changes")
def skill_changes(
    request: Request,
    project_id: str,
    *,
    branch: str = Form(),
    revision: str = Form(),
    text: str = Form(""),
    action: str = Form(),
):
    versioned = request.url.path.startswith("/api/v1/")
    ws = request.app.state.workspace
    p = get_project(ws, project_id)
    text = text.replace("\r\n", "\n")
    try:
        require_base(p, branch, revision)
        original = _text(ws, p)
        if action == "preview":
            lines = unified_diff(
                original.replace("\r\n", "\n").splitlines(keepends=True),
                text.splitlines(keepends=True),
                fromfile="saved/SKILL.md",
                tofile="draft/SKILL.md",
            )
            diff = "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in lines)
            if versioned:
                return {"diff": diff}
            return _render(request, p, text=text, diff=diff)
        if action != "save":
            raise WorkspaceError("Choose preview or save.")
        data = text.replace("\n", "\r\n") if "\r\n" in original and "\n" not in original.replace("\r\n", "") else text
        sha = commit_changes(ws, p, {"SKILL.md": data.encode()}, "Update SKILL.md")
    except WorkspaceError as exc:
        if versioned:
            raise _api_error(exc) from exc
        return _render(request, p, exc, text=text, draft_branch=branch, draft_revision=revision)
    if versioned:
        return {"revision": sha}
    return RedirectResponse(str(request.url_for("skill_editor", project_id=p.id)) + "?pushed=" + sha, 303)


@router.post(api + "/branch", name="api_select_branch", response_model=dict[str, str])
@router.post(path + "/branch")
def select_branch(
    request: Request,
    project_id: str,
    *,
    source: str = Form(),
    new: str | None = Form(None),
    branch: str = Form(),
    revision: str = Form(),
    action: str = Form(),
):
    versioned = request.url.path.startswith("/api/v1/")
    ws = request.app.state.workspace
    p = get_project(ws, project_id)
    try:
        require_base(p, branch, revision)
        if action not in ("switch", "create"):
            raise WorkspaceError("Choose switch or create.")
        expected, _, name = source.partition(" ")
        open_branch(ws, p, name, expected, (new or "") if action == "create" else None)
    except WorkspaceError as exc:
        if versioned:
            raise _api_error(exc) from exc
        return _render(request, p, exc)
    if versioned:
        return {"branch": new if action == "create" else name}
    return RedirectResponse(request.url_for("skill_editor", project_id=p.id), 303)
