from difflib import unified_diff

from fastapi import APIRouter, Form, HTTPException, Request
from pydantic import BaseModel

from .diff_preview import MAX_DIFF_LINES, MAX_PREVIEW_BYTES
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


@router.get(path, name="skill_editor", include_in_schema=False)
def editor(request: Request, project_id: str):
    if request.app.state.workspace.get(project_id) is None:
        raise HTTPException(404, "Unknown project")
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


def _preview(original, draft):
    for side in (original, draft):
        if len(side) > MAX_PREVIEW_BYTES or len(side.encode()) > MAX_PREVIEW_BYTES:
            return "Diff omitted: the saved file or draft exceeds the 32 KiB preview limit."
    before = original.replace("\r\n", "\n").splitlines(keepends=True)
    after = draft.splitlines(keepends=True)
    if len(before) + len(after) > MAX_DIFF_LINES:
        return f"Diff omitted: the saved file and draft exceed {MAX_DIFF_LINES:,} combined lines."
    lines = unified_diff(before, after, fromfile="saved/SKILL.md", tofile="draft/SKILL.md")
    return "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in lines)


@router.post(api + "/changes", name="api_skill_changes", response_model=dict[str, str])
def skill_changes(
    request: Request,
    project_id: str,
    *,
    branch: str = Form(),
    revision: str = Form(),
    text: str = Form(""),
    action: str = Form(),
):
    ws = request.app.state.workspace
    p = get_project(ws, project_id)
    text = text.replace("\r\n", "\n")
    try:
        require_base(p, branch, revision)
        original = _text(ws, p)
        if action == "preview":
            return {"diff": _preview(original, text)}
        if action != "save":
            raise WorkspaceError("Choose preview or save.")
        data = text.replace("\n", "\r\n") if "\r\n" in original and "\n" not in original.replace("\r\n", "") else text
        sha = commit_changes(ws, p, {"SKILL.md": data.encode()}, "Update SKILL.md")
    except WorkspaceError as exc:
        raise _api_error(exc) from exc
    return {"revision": sha}


@router.post(api + "/branch", name="api_select_branch", response_model=dict[str, str])
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
    ws = request.app.state.workspace
    p = get_project(ws, project_id)
    try:
        require_base(p, branch, revision)
        if action not in ("switch", "create"):
            raise WorkspaceError("Choose switch or create.")
        expected, _, name = source.partition(" ")
        open_branch(ws, p, name, expected, (new or "") if action == "create" else None)
    except WorkspaceError as exc:
        raise _api_error(exc) from exc
    return {"branch": new if action == "create" else name}
