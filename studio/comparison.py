"""Read-only inspection of two saved revisions of a project's skill."""

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

from fastapi import APIRouter, Request

from .comparison_evidence import retained_evidence
from .runs import project_for
from .workspace import WorkspaceError

router = APIRouter(prefix="/projects/{project_id}/compare")
SHA = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
MAX_DIFF_LINES = 2000


def saved_refs(ws, project):
    refs = {}
    for prefix in ("refs/remotes/origin/", "refs/heads/"):
        lines = ws.git(project, ["for-each-ref", "--format=%(refname) %(objectname)", prefix])
        for line in lines.splitlines():
            name, sha = line.split()
            if name != prefix + "HEAD":
                refs[name.removeprefix(prefix)] = sha
    return refs


def resolve(ws, project, refs, value):
    sha = value if SHA.fullmatch(value) else refs.get(value, "")
    if not SHA.fullmatch(sha) or ws.git(project, ["cat-file", "-t", sha]) != "commit":
        raise WorkspaceError("Choose a saved branch or a full commit SHA in this project.")
    return sha


def preview(ws, project, mode, oid):
    if mode == b"000000":
        return "File absent"
    if mode not in (b"100644", b"100755"):
        return "Linked file or submodule • content not displayed"
    blob = oid.decode("ascii")
    if int(ws.git(project, ["cat-file", "-s", blob])) > 32 * 1024:
        return "Large file • preview limit 32 KiB"
    data = ws.git(project, ["cat-file", "blob", blob], raw=True)
    try:
        if b"\0" not in data:
            return data.decode() if data else "Empty file"
    except UnicodeDecodeError:
        pass
    return "Binary file • no text preview"


def changed_files(ws, project, left, right):
    data = ws.git(
        project,
        [
            "--literal-pathspecs",
            "diff-tree",
            "-r",
            "-z",
            "--no-renames",
            "--no-abbrev",
            left,
            right,
            "--",
            project.folder,
        ],
        raw=True,
    )
    parts = data.split(b"\0")[:-1]
    files = []
    for header, filename in zip(parts[:40:2], parts[1:40:2], strict=True):
        old_mode, new_mode, old, new, change = header[1:].split()
        a = preview(ws, project, old_mode, old).splitlines(keepends=True)
        b = preview(ws, project, new_mode, new).splitlines(keepends=True)
        file = {"path": filename.decode(errors="replace"), "change": change.decode()}
        if len(a) + len(b) > MAX_DIFF_LINES:
            file["notice"] = f"Line diff omitted: the two previews exceed {MAX_DIFF_LINES:,} combined lines."
        else:
            edits = SequenceMatcher(None, a, b).get_opcodes()
            file["prior"] = [(op, "".join(a[i:j])) for op, i, j, _, _ in edits if i != j]
            file["current"] = [(op, "".join(b[i:j])) for op, _, _, i, j in edits if i != j]
        files.append(file)
    return files, len(parts) // 2


def review_results(ws, project, sides):
    retained = []
    for side in sides:
        row = side["row"]
        usable = (
            row
            and row["kind"] == "tier3-live-v1"
            and row["report"]
            and row["folder"] == project.folder
            and row["status"] in {"neutral", "passed", "failed", "incomplete", "not_run", "skipped"}
        )
        retained.append((row["id"], row["sha"]) if usable else None)
    if any(retained):
        evidence = retained_evidence(ws.data_dir, project.id, retained, Path(project.folder).name or project.name)
        for side, rows in zip(sides, evidence["history"], strict=True):
            side["history"] = rows
        return evidence["comparison"]
    left, right = (side["row"] for side in sides)
    reason = "Select a retained run on each side."
    if left and right:
        if left["kind"] != right["kind"]:
            reason = "Different evaluation kinds. These runs do not measure the same checks."
        elif left["options"] != right["options"] and left["kind"] != "tier3-live-v1":
            reason = "Different evaluation settings. Review the selected checks in each run."
        else:
            reason = "A paired score requires retained with-skill trial evidence from two live evaluations."
    return {"status": "unavailable", "reasons": [reason]}


@router.get("", name="compare_revisions")
def compare(
    request: Request, project_id: str, *, prior: str = "", current: str = "", prior_run: str = "", current_run: str = ""
):
    project = project_for(request, project_id)
    ws = request.app.state.workspace
    jobs = request.app.state.jobs
    context = {"project": project, "prior": prior or project.branch, "current": current or project.branch, "sides": []}
    try:
        refs = saved_refs(ws, project)
        history = jobs.history(project_id)
        context["choices"] = list(refs) + list(dict.fromkeys(r["sha"] for r in history))
        for label, requested in (("Prior", prior_run), ("Current", current_run)):
            sha = resolve(ws, project, refs, context[label.lower()])
            choices = [r for r in history if r["sha"] == sha]
            run = next((r for r in choices if r["id"] == requested), None) if requested else next(iter(choices), None)
            if requested and not run:
                raise WorkspaceError("Choose a run retained for the selected revision.")
            row = jobs.get(project_id, run["id"]) if run else None
            context["sides"].append(
                {
                    "label": label,
                    "sha": sha,
                    "choices": choices,
                    "row": row,
                    "report": json.loads(row["report"] or "{}") if row else {},
                }
            )
        left, right = context["sides"]
        context["files"], context["count"] = changed_files(ws, project, left["sha"], right["sha"])
        context["comparison"] = review_results(ws, project, context["sides"])
    except WorkspaceError as exc:
        context["error"] = str(exc)
    return request.app.state.templates.TemplateResponse(
        request=request, name="comparison/index.html", context=context, status_code=422 if "error" in context else 200
    )
