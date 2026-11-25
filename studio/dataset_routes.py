import shutil

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from .dataset_drafts import Draft
from .dataset_tools import tools_action
from .dataset_traces import review_document, traces
from .editing import Conflict, commit_changes, project_lock, require_base
from .workspace import WorkspaceError

router = APIRouter(prefix="/projects/{project_id}/datasets")


def context(request, project_id):
    ws = request.app.state.workspace
    p = ws.get(project_id)
    if not p:
        raise HTTPException(404, "Unknown project")
    return ws, p


def render(request, p, draft=None, error=None, **extra):
    doc = None
    if draft:
        try:
            doc = draft.document()
            if (
                isinstance(doc, dict)
                and "evals" in doc
                and (not isinstance(doc["evals"], list) or not all(isinstance(c, dict) for c in doc["evals"]))
            ):
                doc = None
                raise ValueError("The evals field must contain a list of case objects.")
        except (ValueError, TypeError) as exc:
            error = error or exc
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="datasets.html",
        context=dict(
            project=p, draft=draft, doc=doc, error=error, review=review_document(draft) if draft else None, **extra
        ),
        status_code=409 if isinstance(error, Conflict) else 422 if error else 200,
    )


@router.get("", name="datasets")
def datasets(request: Request, project_id: str, pushed: str = "", draft: str = ""):
    ws, p = context(request, project_id)
    if draft:
        with project_lock(ws, p.id):
            try:
                active = Draft(ws, p, draft)
            except (OSError, ValueError) as exc:
                raise HTTPException(404, "Unknown draft") from exc
            try:
                require_base(p, active.state["branch"], active.state["revision"])
            except Conflict as exc:
                return render(request, p, active, exc)
            return render(request, p, active)
    return render(request, p, pushed=pushed == p.revision)


@router.post("")
async def dataset_action(request: Request, project_id: str):
    async with request.form(max_files=1, max_part_size=2 * 1024**2) as form:
        return await run_in_threadpool(handle, request, project_id, form)


def handle(request, project_id, form):
    ws, p = context(request, project_id)
    draft = None
    extra = {}
    with project_lock(ws, p.id):
        try:
            if form["action"] == "open":
                require_base(p, form["branch"], form["revision"])
                draft = Draft.create(ws, p)
                return RedirectResponse(
                    str(request.url_for("datasets", project_id=p.id)) + "?draft=" + draft.token, 303
                )
            draft = Draft(ws, p, form["draft"])
            if form["action"] == "discard":
                shutil.rmtree(draft.root)
                return RedirectResponse(request.url_for("datasets", project_id=p.id), 303)
            require_base(p, draft.state["branch"], draft.state["revision"])
            if str(draft.state["version"]) != form["version"]:
                raise Conflict("The draft changed in another form. Review the current draft before retrying.")
            action = form["action"]
            if action in ("add", "update", "remove"):
                draft.case(form, action)
            elif action in ("create", "identity", "switch"):
                draft.manage(form)
            elif action == "delete":
                draft.path.unlink(missing_ok=True)
                draft.stage(draft.state["path"])
            elif action == "preview":
                extra["diff"] = draft.diff()
            elif action in {"import", "preview_accept", "accept"}:
                extra.update(traces(draft, form))
                draft.stage()
            elif action == "commit":
                sha = commit_changes(ws, p, draft.changes(), "Update evaluation dataset")
                shutil.rmtree(draft.root)
                return RedirectResponse(str(request.url_for("datasets", project_id=p.id)) + "?pushed=" + sha, 303)
            else:
                extra.update(tools_action(draft, form))
                if action == "generate":
                    draft.stage()
        except (WorkspaceError, ValueError, KeyError, OSError, TypeError) as exc:
            error = exc if not isinstance(exc, OSError) else "Draft files unavailable."
            if draft and not isinstance(exc, Conflict):
                error = str(error).replace(str(draft.root), "draft")
            return render(request, p, draft, error, submitted=form, **extra)
        return render(request, p, draft, **extra)
