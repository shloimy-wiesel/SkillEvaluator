from difflib import unified_diff

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from .editing import Conflict, branches, commit_changes, open_branch, read_file, require_base
from .workspace import WorkspaceError

router = APIRouter(prefix="/projects/{project_id}/edit")


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


@router.get("", name="skill_editor")
def editor(request: Request, project_id: str, pushed: str = ""):
    _, p = _project(request, project_id)
    return _render(request, p, pushed=pushed == p.revision)


def _text(ws, p):
    content = read_file(ws, p, "SKILL.md")
    if content is None:
        raise WorkspaceError("SKILL.md is missing on this branch.")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkspaceError("SKILL.md must be UTF-8 text.") from exc


@router.post("/changes")
def skill_changes(
    request: Request,
    project_id: str,
    *,
    branch: str = Form(),
    revision: str = Form(),
    text: str = Form(""),
    action: str = Form(),
):
    ws, p = _project(request, project_id)
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
            return _render(request, p, text=text, diff=diff)
        if action != "save":
            raise WorkspaceError("Choose preview or save.")
        data = text.replace("\n", "\r\n") if "\r\n" in original and "\n" not in original.replace("\r\n", "") else text
        sha = commit_changes(ws, p, {"SKILL.md": data.encode()}, "Update SKILL.md")
    except WorkspaceError as exc:
        return _render(request, p, exc, text=text, draft_branch=branch, draft_revision=revision)
    return RedirectResponse(str(request.url_for("skill_editor", project_id=p.id)) + "?pushed=" + sha, 303)


@router.post("/branch")
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
    ws, p = _project(request, project_id)
    try:
        require_base(p, branch, revision)
        expected, _, name = source.partition(" ")
        open_branch(ws, p, name, expected, (new or "") if action == "create" else None)
    except WorkspaceError as exc:
        return _render(request, p, exc)
    return RedirectResponse(request.url_for("skill_editor", project_id=p.id), 303)
