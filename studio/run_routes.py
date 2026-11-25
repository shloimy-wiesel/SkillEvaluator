"""Join a job feature's versioned API with its canonical browser routes."""

from fastapi import APIRouter
from fastapi.responses import RedirectResponse


def feature(path):
    prefix = "/projects/{project_id}/" + path
    return APIRouter(prefix=prefix), APIRouter(prefix="/api/v1" + prefix)


def register(browser, api):
    router = APIRouter()
    router.include_router(browser)
    router.include_router(api)
    return router


def queued(request, project_id, run_id):
    return {"id": run_id, "href": str(request.app.url_path_for("run_detail", project_id=project_id, run_id=run_id))}


def redirect(result):
    return RedirectResponse(result["href"], 303)
