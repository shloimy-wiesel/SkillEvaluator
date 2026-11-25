"""Serve only explicitly registered browser documents from the Next export."""

import os
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def document(request, filename):
    path = request.app.state.frontend / filename
    if not path.is_file():
        raise HTTPException(503, "Studio frontend is not built. Run the web build or set STUDIO_FRONTEND_DIR.")
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


def mount_frontend(app):
    root = app.state.frontend = Path(
        os.environ.get("STUDIO_FRONTEND_DIR", Path(__file__).parent / "frontend/apps/web/out")
    )
    if (root / "_next").is_dir():
        app.mount("/_next", StaticFiles(directory=root / "_next"), name="next_assets")

    @app.get("/", include_in_schema=False)
    def index(request: Request):
        return document(request, "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon(request: Request):
        return document(request, "favicon.ico")

    @app.get("/projects/{project_id}", name="project", include_in_schema=False)
    def project(request: Request, project_id: str):
        if not request.app.state.workspace.get(project_id):
            raise HTTPException(404, "Unknown project")
        return document(request, "project.html")
