import shutil
from contextlib import contextmanager

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as FormError

from .dataset_collection import collect, refine_collected
from .dataset_drafts import Draft
from .dataset_tools import tools_action
from .dataset_traces import review_document, traces
from .editing import Conflict, commit_changes, project_lock, require_base
from .frontend_routes import document
from .project_api import failure, get_project
from .workspace import WorkspaceError

router = APIRouter()
PATH = "/projects/{project_id}/datasets"
API = "/api/v1" + PATH


@contextmanager
def locked_project(request, project_id):
    ws = request.app.state.workspace
    get_project(ws, project_id)  # Only allocate locks for known projects.
    with project_lock(ws, project_id):
        yield ws, get_project(ws, project_id)


def view(p, draft=None, error=None, **extra):
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
    payload = {
        "project": {"id": p.id, "name": p.name, "branch": p.branch, "revision": p.revision},
        "draft": {**draft.state, "token": draft.token, "choices": draft.choices()} if draft else None,
        "editable": doc if isinstance(doc, dict) and "evals" in doc else None,
        "review": review_document(draft) if draft else None,
        **extra,
    }
    if error:
        conflict = isinstance(error, Conflict)
        payload["detail"] = {"code": "conflict" if conflict else "invalid_dataset", "message": str(error)}
        return JSONResponse(payload, 409 if conflict else 422)
    return payload


@router.get(PATH, name="datasets", include_in_schema=False)
def datasets(request: Request, project_id: str):
    get_project(request.app.state.workspace, project_id)
    return document(request, "datasets.html")


def load_draft(ws, p, token):
    try:
        return Draft(ws, p, token)
    except (OSError, ValueError) as exc:
        raise failure(404, "unknown_draft", "Unknown draft.") from exc


@router.get(API)
def dataset_view(request: Request, project_id: str, pushed: str = "", draft: str = ""):
    if draft:
        with locked_project(request, project_id) as (ws, p):
            active = load_draft(ws, p, draft)
            try:
                require_base(p, active.state["branch"], active.state["revision"])
            except Conflict as exc:
                return view(p, active, exc)
            return view(p, active)
    p = get_project(request.app.state.workspace, project_id)
    return view(p, pushed=pushed == p.revision)


@router.post(API)
async def dataset_action(request: Request, project_id: str):
    try:
        async with request.form(max_files=1, max_part_size=2 * 1024**2) as form:
            if any(not isinstance(value, str) and key != "export" for key, value in form.multi_items()):
                raise failure(422, "invalid_dataset", "Use the trace export field for file uploads.")
            return await run_in_threadpool(handle, request, project_id, form)
    except FormError as exc:
        if exc.status_code == 400:
            raise failure(422, "invalid_dataset", "Invalid or oversized dataset form.") from exc
        raise


def handle(request, project_id, form):
    draft = None
    extra = {}
    with locked_project(request, project_id) as (ws, p):
        try:
            if form["action"] == "open":
                require_base(p, form["branch"], form["revision"])
                draft = Draft.create(ws, p)
                return {
                    "location": str(request.app.url_path_for("datasets", project_id=p.id)) + "?draft=" + draft.token
                }
            draft = load_draft(ws, p, form["draft"])
            if str(draft.state["version"]) != form["version"]:
                raise Conflict("The draft changed in another form. Review the current draft before retrying.")
            if form["action"] == "discard":
                shutil.rmtree(draft.root)
                return {"location": str(request.app.url_path_for("datasets", project_id=p.id))}
            require_base(p, draft.state["branch"], draft.state["revision"])
            action = form["action"]
            if action == "collect":
                run = collect(draft, request.app.state.jobs, form.get("sandbox_consent") == "on")
                return {"location": str(request.app.url_path_for("run_detail", project_id=p.id, run_id=run))}
            if action == "refine_collected":
                extra.update(refine_collected(draft, request.app.state.jobs))
            elif action in ("add", "update", "remove"):
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
                return {"location": str(request.app.url_path_for("datasets", project_id=p.id)) + "?pushed=" + sha}
            else:
                extra.update(tools_action(draft, form))
                if action == "generate":
                    draft.stage()
        except (WorkspaceError, ValueError, KeyError, OSError, TypeError) as exc:
            error = exc if not isinstance(exc, OSError) else "Draft files unavailable."
            if draft and not isinstance(exc, Conflict):
                error = str(error).replace(str(draft.root), "draft")
            return view(p, draft, error, **extra)
        return view(p, draft, **extra)
