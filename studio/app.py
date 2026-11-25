"""Studio ASGI application factory."""

import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .extensions import JOB_DEFINITIONS, PROJECT_LINKS, ROUTERS
from .frontend_routes import mount_frontend
from .gitlab_routes import router as gitlab_router
from .jobs import Jobs
from .project_api import router as project_api
from .workspace import Workspace

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
    app.state.workspace = Workspace(data_dir or os.environ.get("STUDIO_DATA_DIR", "/data"))
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

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        if request.url.path.startswith("/api/v1/"):
            # Pydantic diagnostics may contain raw input, including write-only keys.
            return JSONResponse({"detail": {"code": "invalid_request", "message": "Check the submitted fields."}}, 422)
        return await request_validation_exception_handler(request, exc)

    app.state.project_links = PROJECT_LINKS
    mount_frontend(app)
    app.include_router(project_api)
    for router in (gitlab_router, *ROUTERS, *routers):
        app.include_router(router)
    return app
