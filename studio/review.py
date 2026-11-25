"""Inspect retained evaluation evidence within a project."""

import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from skillevaluator.reporting.dashboard_data import comparison_rows, parse_dashboard_report
from skillevaluator.utils.redaction import redact_sensitive_data

from .feedback import ask, conversation
from .retained import compare, inventory, native_dashboard, preview, report_preview, scrubber
from .runs import project_for, record_for

router = APIRouter(prefix="/projects/{project_id}/results")
DIMENSIONS = ("skill", "model", "harness", "features", "condition", "status")
METRICS = {
    "quality": ("score", "pass_rate"),
    "tokens": ("prompt_tokens", "completion_tokens", "cached_tokens", "total_tokens"),
    "duration": ("duration_seconds",),
    "cost": ("cost_usd",),
}


@router.get("", name="results_dashboard")
def dashboard(
    request: Request,
    project_id: str,
    display: Literal["performance", "comparison"] = "performance",
    metrics: Literal["quality", "tokens", "duration", "cost", "all"] = "quality",
    evidence: Literal["report", "native"] = "report",
):
    project = project_for(request, project_id)
    scrub = scrubber(request.app.state.workspace, project_id)
    history = [r for r in request.app.state.jobs.history(project_id) if r["kind"] == "tier3-live-v1"]
    chosen = request.query_params.getlist("run")
    if set(chosen) - {r["id"] for r in history}:
        raise HTTPException(404, "Unknown run")
    rows, warnings = [], []
    for entry in history:
        if chosen and entry["id"] not in chosen:
            continue
        run = record_for(request, project_id, entry["id"])
        if run["report"]:
            data = (
                native_dashboard(
                    request.app.state.workspace.data_dir / "artifacts" / project_id / run["id"] / "tier3", run
                )
                if evidence == "native"
                else parse_dashboard_report(json.loads(run["report"]), run["id"])
            )
            for row in data.rows:
                for key in DIMENSIONS:
                    row[key] = scrub(row[key])
                rows.append(row)
            warnings.extend(map(scrub, data.warnings))
    choices = {key: sorted({r[key] for r in rows}) for key in DIMENSIONS}
    filters = {key: request.query_params.getlist(key) for key in DIMENSIONS}
    columns = ["source", "skill", "model", "harness", "features"]
    measures = METRICS.get(metrics) or sum(METRICS.values(), ())
    for field, values in filters.items():
        if values and not (display == "comparison" and field in ("condition", "status")):
            rows = [r for r in rows if r[field] in values]
    if display == "comparison":
        rows = comparison_rows(rows)
        columns += ["coverage", "comparison_status", "comparison_reason", *(m + "_delta" for m in measures)]
    else:
        columns += ["condition", "status", "trials", *measures]
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="review/dashboard.html",
        context={
            "project": project,
            "rows": [{k: redact_sensitive_data(r.get(k)) for k in columns} for r in rows],
            "history": history,
            "chosen": chosen,
            "choices": choices,
            "filters": filters,
            "warnings": warnings,
            "display": display,
            "metrics": metrics,
            "evidence": evidence,
            "columns": columns,
            "metric_sets": [*METRICS, "all"],
        },
    )


def reviewed_run(request, project_id, run_id):
    run = record_for(request, project_id, run_id)
    if run["kind"] != "tier3-live-v1" or not run["report"] or run["status"] in {"running", "queued"}:
        raise HTTPException(404, "No retained evaluation")
    return run


@router.get("/{run_id}", name="review_run")
def review(
    request: Request,
    project_id: str,
    run_id: str,
    q: str = "",
    file: str = "",
    agents: bool = False,
    source: str = "",
    report: bool = False,
):
    run = reviewed_run(request, project_id, run_id)
    workspace = request.app.state.workspace
    root = workspace.data_dir / "artifacts" / project_id / run_id / "tier3"
    files = inventory(root)
    scrub = scrubber(workspace, project_id)
    if file and file not in files:
        raise HTTPException(404, "Unknown artifact")
    labels = {key: scrub(path.relative_to(root).as_posix()) for key, path in files.items()}
    text = preview(files[file], scrub) if file else None
    if report and not file:
        text = report_preview(root, run, files.values(), scrub)
    steps, sources = None, []
    if file and files[file].name == "trajectory.json":
        document = json.loads(text)
        if isinstance(document, dict) and isinstance(document.get("steps"), list):
            steps = [step for step in document["steps"] if isinstance(step, dict)]
            sources = sorted({step["source"] for step in steps if isinstance(step.get("source"), str)})
            if source:
                steps = [step for step in steps if step.get("source") == source]
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="review/run.html",
        context={
            "project": project_for(request, project_id),
            "run": run,
            "q": q,
            "files": {key: label for key, label in labels.items() if q.casefold() in label.casefold()},
            "preview": text,
            "steps": steps,
            "sources": sources,
            "source": source,
            "file": file,
            "comparison": compare(root, Path(run["folder"]), scrub) if agents else None,
            "conversation": conversation(workspace, run),
            "can_ask": bool(json.loads(run["report"]).get("tier3")),
        },
    )


@router.post("/{run_id}/feedback", name="ask_feedback")
def feedback(request: Request, project_id: str, run_id: str, question: str = Form(min_length=1, max_length=4000)):
    run = reviewed_run(request, project_id, run_id)
    ask(request.app.state.workspace, run, question)
    return RedirectResponse(request.url_for("review_run", project_id=project_id, run_id=run_id), 303)
