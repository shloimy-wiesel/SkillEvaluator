"""Project-scoped native history, trends and version comparison downloads."""

import json
import subprocess
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response

from skillevaluator.tier3.history import export_history

from .comparison_evidence import retained_catalog
from .runs import project_for

router = APIRouter(prefix="/projects/{project_id}/results")


@router.get("/history", name="skill_history")
def history(
    request: Request,
    project_id: str,
    *,
    agent: str = "",
    current: str = "latest",
    prior: str = "latest",
    scope: Annotated[list[str] | None, Query()] = None,
    download: str = "",
):
    scope = scope or []
    project = project_for(request, project_id)
    with request.app.state.jobs.connection() as db:
        choices = db.execute(
            """SELECT id, sha, created FROM runs WHERE project_id=? AND folder=?
            AND kind='tier3-live-v1' AND report IS NOT NULL AND status IN
            ('neutral','passed','failed','incomplete','not_run','skipped') ORDER BY rowid DESC""",
            (project.id, project.folder),
        ).fetchall()
    ids = {r["id"] for r in choices}
    if not set(scope) <= ids or not {current, prior} <= ids | {"latest"}:
        raise HTTPException(422, "Choose retained evaluations from this project and skill.")
    if download not in ("", "json", "csv", "md", "comparison"):
        raise HTTPException(422, "Unknown results format.")
    selected = set(scope) or ids
    runs = [(r["id"], r["sha"]) for r in choices if r["id"] in selected]
    skill = Path(project.folder).name or project.name
    args = request.app.state.workspace.data_dir, project.id, runs, skill
    try:
        trend = retained_catalog(*args, action="history", agent=agent or None) if download != "comparison" else None
        comparison = (
            retained_catalog(*args, action="compare", current=current, prior=prior)
            if download in ("", "comparison")
            else None
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise HTTPException(503, "Retained evidence could not be read within inspection limits.") from exc
    if download:
        fmt = "json" if download == "comparison" else download
        body = (
            json.dumps(comparison, indent=2, allow_nan=False)
            if comparison is not None
            else export_history(trend, "." + fmt)
        )
        return Response(
            body,
            media_type={"json": "application/json", "csv": "text/csv", "md": "text/markdown"}[fmt],
            headers={
                "Content-Disposition": f'attachment; filename="{"comparison" if comparison is not None else "history"}.{fmt}"'
            },
        )
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="history.html",
        context={
            "project": project,
            "choices": choices,
            "scope": scope,
            "agent": agent,
            "prior": prior,
            "current": current,
            "trend": trend,
            "comparison": comparison,
        },
    )
