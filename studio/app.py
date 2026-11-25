"""Studio ASGI application factory."""

import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .extensions import JOB_DEFINITIONS, PROJECT_LINKS, ROUTERS
from .gitlab import instance
from .gitlab_routes import router as gitlab_router
from .jobs import Jobs
from .navigation import task_groups
from .workspace import Workspace, WorkspaceError

PACKAGE = Path(__file__).parent
HOSTNAME = r"(?:[a-zA-Z0-9.-]+|\[[0-9a-fA-F:]+\])"


def create_app(data_dir=None, *, routers=(), job_definitions=()):
    trusted = {"localhost", "127.0.0.1", "[::1]"}
    for name in os.environ.get("STUDIO_TRUSTED_HOSTS", "").split(","):
        if name := name.strip().lower():
            if not re.fullmatch(HOSTNAME, name):
                raise ValueError("STUDIO_TRUSTED_HOSTS requires comma-separated hostnames without ports.")
            trusted.add(name)

    @asynccontextmanager
    async def lifespan(app):
        app.state.jobs = Jobs(app.state.workspace, (*JOB_DEFINITIONS, *job_definitions))
        try:
            yield
        finally:
            app.state.jobs.pool.shutdown(cancel_futures=True)

    app = FastAPI(title="SkillEvaluator Studio", lifespan=lifespan)
    workspace = app.state.workspace = Workspace(data_dir or os.environ.get("STUDIO_DATA_DIR", "/data"))
    templates = app.state.templates = Jinja2Templates(directory=PACKAGE / "templates")
    templates.env.globals["project_links"] = PROJECT_LINKS
    templates.env.filters["task_groups"] = task_groups
    app.mount("/static", StaticFiles(directory=PACKAGE / "static"), name="static")

    @app.middleware("http")
    async def trusted_request(request: Request, call_next):
        hosts = request.headers.getlist("host")
        authority = re.fullmatch(rf"({HOSTNAME})(?::[0-9]{{1,5}})?", hosts[0]) if len(hosts) == 1 else None
        if not authority or authority[1].lower() not in trusted:
            return PlainTextResponse("Unrecognized Studio host.", status_code=400)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if (origin and origin != str(request.base_url).rstrip("/")) or request.headers.get(
                "sec-fetch-site"
            ) == "cross-site":
                return PlainTextResponse("Submit this form from Studio.", status_code=403)
        return await call_next(request)

    def home(request, error=None, folder="."):
        return templates.TemplateResponse(
            request=request,
            name="workspace/home.html",
            context={"projects": workspace.projects(), "error": error, "folder": folder},
            status_code=422 if error else 200,
        )

    @app.get("/")
    def index(request: Request):
        return home(request)

    @app.post("/projects")
    def connect(
        request: Request,
        *,
        remote: str = Form(),
        folder: str = Form("."),
        username: str = Form(""),
        token: str = Form(""),
        gitlab_root: str = Form(""),
        ca_pem: str = Form(""),
    ):
        try:
            project_id = workspace.connect(remote, folder, username, token, gitlab_root=gitlab_root, ca_pem=ca_pem)
        except WorkspaceError as e:
            # Invalid URLs may themselves contain credentials.
            return home(request, str(e), folder=folder)
        return RedirectResponse(f"/projects/{project_id}", 303)

    @app.get("/projects/{project_id}", name="project")
    def project_detail(request: Request, project_id: str):
        project = workspace.get(project_id)
        if project is None:
            raise HTTPException(404, "Unknown project")
        return templates.TemplateResponse(request=request, name="workspace/project.html", context={"project": project})

    @app.post("/projects/{project_id}/check")
    def check_access(request: Request, project_id: str):
        project = workspace.get(project_id)
        if project is None:
            raise HTTPException(404, "Unknown project")
        try:
            workspace.git(project, ["ls-remote", "--exit-code", "--", project.remote, "HEAD"], authenticated=True)
        except WorkspaceError as exc:
            return templates.TemplateResponse(
                request=request,
                name="workspace/project.html",
                context={"project": project, "error": str(exc)},
                status_code=422,
            )
        return templates.TemplateResponse(
            request=request,
            name="workspace/project.html",
            context={"project": project, "notice": "Remote access confirmed."},
        )

    templates.env.globals["gitlab_instance"] = lambda project: instance(workspace, project)
    for router in (gitlab_router, *ROUTERS, *routers):
        app.include_router(router)
    return app
