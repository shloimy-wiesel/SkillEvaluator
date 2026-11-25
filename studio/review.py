"""Inspect retained evaluation evidence within a project."""

import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field

from skillevaluator.reporting.dashboard_data import comparison_rows, parse_dashboard_report, rows_csv
from skillevaluator.utils.redaction import redact_sensitive_data

from . import review_uploads
from .feedback import ask, conversation
from .frontend_routes import document
from .result_routes import route_pair
from .retained import compare, inventory, native_dashboard, native_results, preview, report_preview, scrubber
from .runs import project_for, record_for

pages, api = route_pair("/projects/{project_id}/results")
DIMENSIONS = ("skill", "model", "harness", "features", "condition", "status")
METRICS = {
    "quality": ("score", "pass_rate"),
    "tokens": ("prompt_tokens", "completion_tokens", "cached_tokens", "total_tokens"),
    "duration": ("duration_seconds",),
    "cost": ("cost_usd",),
}


@pages.get("", name="results_dashboard")
@api.get("")
def dashboard(
    request: Request,
    project_id: str,
    *,
    display: Literal["performance", "comparison"] = "performance",
    metrics: Literal["quality", "tokens", "duration", "cost", "all"] = "quality",
    csv: bool = False,
    evidence: Literal["report", "native"] = "report",
):
    project = project_for(request, project_id)
    history = [r for r in request.app.state.jobs.history(project_id) if r["kind"] == "tier3-live-v1"]
    chosen = request.query_params.getlist("run")
    workspace = request.app.state.workspace
    imported = review_uploads.uploads(workspace, project_id)
    if set(chosen) - imported.keys() - {r["id"] for r in history}:
        raise HTTPException(404, "Unknown run")
    if not csv and not request.url.path.startswith("/api/v1/"):
        return document(request, "dashboard.html")
    scrub = scrubber(workspace, project_id)
    rows, warnings = [], []

    def collect(data):
        for row in data.rows:
            for key in DIMENSIONS:
                row[key] = scrub(row[key])
            rows.append(row)
        warnings.extend(map(scrub, data.warnings))

    if evidence == "report":
        for source, encrypted in imported.items():
            if not chosen or source in chosen:
                collect(parse_dashboard_report(json.loads(workspace.cipher.decrypt(encrypted)), source))
    for entry in history:
        if entry["status"] in {"queued", "running"} or (chosen and entry["id"] not in chosen):
            continue
        run = record_for(request, project_id, entry["id"])
        if evidence == "native" or not run["report"]:
            data = native_dashboard(workspace.data_dir / "artifacts" / project_id / run["id"] / "tier3", run)
            if not run["report"] and data.rows:
                warnings.append(f"{run['id']}: saved report missing; showing retained measurements.")
        else:
            data = parse_dashboard_report(json.loads(run["report"]), run["id"])
        collect(data)
    choices = {key: sorted({r[key] for r in rows}) for key in DIMENSIONS}
    filters = {key: request.query_params.getlist(key) for key in DIMENSIONS}
    columns = ["source", "run_id", "skill", "model", "harness", "features"]
    measures = METRICS.get(metrics) or sum(METRICS.values(), ())
    for field, values in filters.items():
        if values and not (display == "comparison" and field in ("condition", "status")):
            rows = [r for r in rows if r[field] in values]
    if display == "comparison":
        rows = comparison_rows(rows)
        columns += ["coverage", "comparison_status", "comparison_reason"]
        for m in measures:
            columns += ["with_" + m, "without_" + m, m + "_delta"]
            if m not in METRICS["quality"]:
                columns.append(m + "_percent")
    else:
        columns += ["condition", "status", "trials", "coverage", *measures]
        columns += [m + "_per_trial" for m in measures if m in {"total_tokens", "duration_seconds", "cost_usd"}]
    visible = [
        {k: scrub(v) if isinstance(v := r.get(k), str) else redact_sensitive_data(v) for k in columns} for r in rows
    ]
    if csv:
        return Response(
            rows_csv(visible, tuple(columns)),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="skill-{display}.csv"',
                "Cache-Control": "no-store",
            },
        )
    return {
        "project": project,
        "rows": visible,
        "history": [dict(r) for r in history],
        "imported": list(imported),
        "chosen": chosen,
        "choices": choices,
        "filters": filters,
        "warnings": warnings,
        "display": display,
        "metrics": metrics,
        "evidence": evidence,
        "columns": columns,
        "metric_sets": [*METRICS, "all"],
    }


@api.post("/uploads")
@pages.post("/uploads", name="import_dashboard_report")
async def import_dashboard_report(request: Request, project_id: str):
    project_for(request, project_id)
    source = await review_uploads.import_report(request, request.app.state.workspace, project_id)
    return {"location": f"{request.url_for('results_dashboard', project_id=project_id)}?run={source}"}


@api.post("/uploads/{source}/remove")
@pages.post("/uploads/{source}/remove", name="remove_dashboard_report")
def remove_dashboard_report(request: Request, project_id: str, source: str):
    project_for(request, project_id)
    review_uploads.remove(request.app.state.workspace, project_id, source)
    if request.url.path.startswith("/api/v1/"):
        return {"removed": source}
    return RedirectResponse(request.url_for("results_dashboard", project_id=project_id), 303)


def reviewed_run(request, project_id, run_id):
    run = record_for(request, project_id, run_id)
    if run["kind"] != "tier3-live-v1" or run["status"] in {"running", "queued"}:
        raise HTTPException(404, "No retained evaluation")
    return run


@api.get("/{run_id}")
@pages.get("/{run_id}", name="review_run")
def review(
    request: Request,
    project_id: str,
    run_id: str,
    *,
    q: str = "",
    file: str = "",
    agents: bool = False,
    latest: bool = False,
    harbor: bool = False,
    job: str = "",
    source: str = "",
    report: bool = False,
    download: bool = False,
):
    run = reviewed_run(request, project_id, run_id)
    workspace = request.app.state.workspace
    root = workspace.data_dir / "artifacts" / project_id / run_id / "tier3"
    files = inventory(root)
    if not run["report"] and not native_results(root, files.values()):
        raise HTTPException(404, "No retained evaluation")
    scrub = scrubber(workspace, project_id)
    if file and file not in files:
        raise HTTPException(404, "Unknown artifact")
    labels = {key: scrub(path.relative_to(root).as_posix()) for key, path in files.items()}
    jobs = {}
    if harbor:
        for key, path in files.items():
            parts = path.relative_to(root).parts
            if "_harbor-jobs" in parts[:-2]:
                jobs[key] = scrub(parts[parts.index("_harbor-jobs") + 1])
        if job and job not in jobs.values():
            raise HTTPException(404, "Unknown Harbor job")
        labels = {k: labels[k] for k in jobs if not job or jobs[k] == job}
        if file and file not in labels:
            raise HTTPException(404, "Unknown job artifact")
    if download:
        if not file:
            raise HTTPException(422, "Choose a retained file to download.")
        path = files[file]
        return Response(
            preview(path, scrub),
            media_type="text/plain",
            headers={
                "Content-Disposition": f'attachment; filename="{path.name}.txt"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    if not request.url.path.startswith("/api/v1/"):
        return document(request, "review.html")
    text = preview(files[file], scrub) if file else None
    sections = None
    if report and not file:
        sections = report_preview(root, run, files.values(), scrub)
    steps, sources = None, []
    if file and files[file].name == "trajectory.json":
        trajectory = json.loads(text)
        if isinstance(trajectory, dict) and isinstance(trajectory.get("steps"), list):
            steps = [step for step in trajectory["steps"] if isinstance(step, dict)]
            sources = sorted({step["source"] for step in steps if isinstance(step.get("source"), str)})
            if source:
                steps = [step for step in steps if step.get("source") == source]
    comparison = None
    if agents or latest:
        roots = [root]
        if latest:
            roots = []
            for entry in request.app.state.jobs.history(project_id):
                if entry["kind"] != run["kind"] or entry["status"] in {"running", "queued"}:
                    continue
                candidate = record_for(request, project_id, entry["id"])
                if candidate["folder"] == run["folder"]:
                    roots.append(root.parent.parent / entry["id"] / "tier3")
        comparison = compare(roots, Path(run["folder"]), scrub)
    return {
        "project": project_for(request, project_id),
        "run": {k: run[k] for k in ("id", "folder", "sha")},
        "q": q,
        "files": {key: label for key, label in labels.items() if q.casefold() in label.casefold()},
        "preview": text,
        "sections": sections,
        "harbor": harbor,
        "jobs": sorted(set(jobs.values())),
        "job": job,
        "steps": steps,
        "sources": sources,
        "source": source,
        "file": file,
        "comparison": comparison,
        "conversation": conversation(workspace, run),
        "can_ask": bool(json.loads(run["report"] or "{}").get("tier3")),
    }


@pages.post("/{run_id}/feedback", name="ask_feedback")
def feedback(request: Request, project_id: str, run_id: str, question: str = Form(min_length=1, max_length=4000)):
    run = reviewed_run(request, project_id, run_id)
    ask(request.app.state.workspace, run, question)
    return RedirectResponse(request.url_for("review_run", project_id=project_id, run_id=run_id), 303)


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


@api.post("/{run_id}/feedback")
def feedback_turn(request: Request, project_id: str, run_id: str, body: Question):
    run = reviewed_run(request, project_id, run_id)
    workspace = request.app.state.workspace
    ask(workspace, run, body.question)
    return {"conversation": conversation(workspace, run)}


router = APIRouter()
router.include_router(pages)
router.include_router(api)
