"""Preview engine-generated assets against committed files, never the live checkout."""

from difflib import unified_diff
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

from skillevaluator.tier3.scaffold import init_custom_grader, init_harbor_task

from .editing import Conflict, commit_changes, read_file, require_base
from .grader_job import GRADER, GraderOptions, public_identity
from .providers import worker_environment
from .workspace import WorkspaceError

router = APIRouter(prefix="/projects/{project_id}/assets")


def project(request, project_id):
    ws = request.app.state.workspace
    p = ws.get(project_id)
    if not p:
        raise HTTPException(404, "Unknown project")
    return ws, p


def render(request, p, error=None, **context):
    raw = request.app.state.workspace.git(
        p, ["--literal-pathspecs", "ls-tree", "-rz", p.revision, "--", p.folder], raw=True
    )
    files = []
    for record in raw.split(b"\0"):
        if record.startswith((b"100644 ", b"100755 ")):
            path = Path(record.partition(b"\t")[2].decode(errors="replace")).relative_to(p.folder)
            if path.suffix == ".json":
                files.append(str(path))
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="assets/index.html",
        context=dict(project=p, files=files, error=error, **context),
        status_code=409 if isinstance(error, Conflict) else 422 if error else 200,
    )


@router.get("", name="assets")
def index(request: Request, project_id: str, pushed: str = ""):
    _, p = project(request, project_id)
    return render(request, p, pushed=pushed == p.revision)


def materialize(ws, p, dest, directory):
    """Copy only regular Git blobs in an authorized subtree, with bounded input."""
    prefix = Path(p.folder) / directory
    raw = ws.git(p, ["--literal-pathspecs", "ls-tree", "-rlz", p.revision, "--", str(prefix)], raw=True)
    result = {}
    total = 0
    for record in raw.split(b"\0"):
        if not record:
            continue
        header, path = record.split(b"\t", 1)
        mode, _, oid, size = header.split()
        rel = Path(path.decode()).relative_to(p.folder)
        if mode not in {b"100644", b"100755"} or ".git" in (s.lower() for s in rel.parts):
            raise WorkspaceError("Only regular project files are supported.")
        total += int(size)
        if total > 16 * 1024**2 or len(result) >= 1024:
            raise WorkspaceError("Asset snapshot exceeds 16 MiB or 1024 files.")
        data = ws.git(p, ["cat-file", "blob", oid.decode()], raw=True)
        file = dest / rel
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
        exe = mode == b"100755"
        file.chmod(0o755 if exe else 0o644)
        result[str(rel)] = data, exe
    return result


def scaffold(ws, p, *, kind, mode, language, force, config, case_id):
    if (
        language not in {"shell", "python"}
        or kind not in {"grader", "harbor"}
        or mode not in ({"default_plus_custom", "custom_only"} | ({"default"} if kind == "harbor" else set()))
    ):
        raise WorkspaceError("Choose a listed starter, language and mode.")
    with TemporaryDirectory() as temp:
        name = Path(p.folder).name or p.name
        if name in {".", ".."} or Path(name).name != name:
            raise WorkspaceError("Invalid skill name.")
        root = Path(temp) / name
        root.mkdir()
        skill = read_file(ws, p, "SKILL.md")
        if skill is None:
            raise WorkspaceError("Missing SKILL.md.")
        (root / "SKILL.md").write_bytes(skill)
        before = materialize(ws, p, root, "evals")
        if kind == "harbor":
            code = init_harbor_task(
                root, mode=mode, language=language, force=force, with_config=config, case_id=case_id
            )
        else:
            code = init_custom_grader(root, mode=mode, language=language, force=force, no_config=not config)
        if code:
            raise WorkspaceError("Starter already exists. Select overwrite to replace it.")
        after = {
            str(f.relative_to(root)): (f.read_bytes(), bool(f.stat().st_mode & 0o100))
            for f in (root / "evals").rglob("*")
            if f.is_file()
        }
        changes, modes, preview = {}, {}, []
        for path in sorted(before.keys() | after.keys()):
            if before.get(path) == after.get(path):
                continue
            old, _ = before.get(path, (b"", False))
            new, mode = after.get(path, (None, False))
            changes[path], modes[path] = new, mode
            preview.append(f"{path} ({'deleted' if new is None else 'executable' if mode else 'regular file'})\n")
            preview.extend(
                unified_diff(
                    old.decode(errors="replace").splitlines(True),
                    (new or b"").decode(errors="replace").splitlines(True),
                    fromfile="saved/" + path,
                    tofile="draft/" + path,
                )
            )
        return changes, modes, "".join(preview)


@router.post("/scaffold", name="asset_scaffold")
def change(
    request: Request,
    project_id: str,
    *,
    kind: str = Form(),
    branch: str = Form(),
    revision: str = Form(),
    language: str = Form(),
    mode: str = Form(),
    config: bool = Form(False),
    force: bool = Form(False),
    case_id: str = Form("case-001"),
    action: str = Form(),
):
    ws, p = project(request, project_id)
    draft = {
        "kind": kind,
        "branch": branch,
        "revision": revision,
        "language": language,
        "mode": mode,
        "config": config,
        "force": force,
        "case_id": case_id,
    }
    try:
        require_base(p, branch, revision)
        changes, modes, diff = scaffold(
            ws, p, kind=kind, mode=mode, language=language, force=force, config=config, case_id=case_id
        )
        if action == "preview":
            return render(request, p, draft=draft, diff=diff or "No changes.")
        if action != "save":
            raise WorkspaceError("Choose preview or save.")
        sha = commit_changes(ws, p, changes, "Create evaluation starter", executable=modes)
    except (WorkspaceError, ValueError, OSError, yaml.YAMLError) as exc:
        return render(request, p, exc, draft=draft)
    return RedirectResponse(str(request.url_for("assets", project_id=p.id)) + "?pushed=" + sha, 303)


@router.post("/qualify", name="qualify_grader")
def qualify_form(
    request: Request,
    project_id: str,
    *,
    branch: str = Form(),
    revision: str = Form(),
    suite: str = Form(""),
    policy: str = Form(""),
    split: str = Form("assessment"),
    cases: str = Form(""),
    repeats: int = Form(3),
    concurrency: int = Form(1),
    timeout: float = Form(300),
    max_false_pass_rate: float | None = Form(None),
    max_false_fail_rate: float | None = Form(None),
    max_unjudgeable_rate: float | None = Form(None),
    action: str = Form(),
):
    ws, p = project(request, project_id)
    try:
        require_base(p, branch, revision)
        if action not in {"check", "qualify"}:
            raise WorkspaceError("Unknown qualification action.")
        for name in (suite, policy):
            if name and (not name.endswith(".json") or read_file(ws, p, name) is None):
                raise WorkspaceError("Select an existing skill JSON file.")
        chat = None
        if action == "qualify":
            if suite:
                raise WorkspaceError(
                    "Live qualification requires the bundled reference suite on this host. Use Check suite for project manifests."
                )
            try:
                chat = public_identity(worker_environment(ws, p.id, "chat"))
            except ValueError:
                pass  # A not-ready preflight still produces a receipt without inference.
        opts = GraderOptions(
            check_suite=action == "check",
            chat=chat,
            suite=suite,
            policy=policy,
            split=split,
            cases=tuple(cases.split()),
            repeats=repeats,
            concurrency=concurrency,
            timeout=timeout,
            max_false_pass_rate=max_false_pass_rate,
            max_false_fail_rate=max_false_fail_rate,
            max_unjudgeable_rate=max_unjudgeable_rate,
        )
        run_id = request.app.state.jobs.enqueue(p, revision, GRADER, opts)
    except (WorkspaceError, ValueError) as exc:
        return render(request, p, exc)
    return RedirectResponse(request.url_for("run_detail", project_id=p.id, run_id=run_id), 303)


@router.get("/evidence/{run_id}", name="grader_evidence")
def evidence(request: Request, project_id: str, run_id: str):
    ws, p = project(request, project_id)
    row = request.app.state.jobs.get(p.id, run_id)
    if not row or row["kind"] != GRADER.kind or row["status"] not in {"passed", "failed", "not_run"}:
        raise HTTPException(404, "No qualification evidence")
    path = ws.data_dir / "artifacts" / p.id / row["id"] / "qualification.zip"
    if not path.is_file():
        raise HTTPException(404, "No qualification evidence")
    return FileResponse(path, media_type="application/zip", filename="grader-validation.zip")
