"""Preview engine-generated assets against committed files, never the live checkout."""

from contextlib import suppress
from difflib import unified_diff
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from skillevaluator.tier3.scaffold import init_custom_grader, init_harbor_task

from .editing import Conflict, commit_changes, read_file, require_base
from .frontend_routes import document
from .grader_job import GRADER, GraderOptions, QualificationControls, public_identity
from .grader_sandbox import require_sandbox
from .project_api import failure, get_project
from .providers import worker_environment
from .workspace import Project, WorkspaceError

router = APIRouter()
path = "/projects/{project_id}/assets"
api_path = "/api/v1" + path


def project(request, project_id):
    ws = request.app.state.workspace
    return ws, get_project(ws, project_id)


class AssetView(BaseModel):
    project: Project
    files: list[str]


@router.get(api_path)
def asset_view(request: Request, project_id: str) -> AssetView:
    ws, p = project(request, project_id)
    raw = ws.git(p, ["--literal-pathspecs", "ls-tree", "-rz", p.revision, "--", p.folder], raw=True)
    files = []
    for record in raw.split(b"\0"):
        if record.startswith((b"100644 ", b"100755 ")):
            path = Path(record.partition(b"\t")[2].decode(errors="replace")).relative_to(p.folder)
            if path.suffix == ".json":
                files.append(str(path))
    return AssetView(project=p, files=files)


@router.get(path, name="assets", include_in_schema=False)
def index(request: Request, project_id: str):
    project(request, project_id)
    return document(request, "assets.html")


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


class RevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    branch: str
    revision: str


class Starter(RevisionInput):
    kind: Literal["grader", "harbor"]
    language: Literal["shell", "python"]
    mode: Literal["default", "custom_only", "default_plus_custom"]
    config: bool = False
    force: bool = False
    case_id: str = "case-001"
    action: Literal["preview", "save"]


class Preview(BaseModel):
    diff: str


class Pushed(BaseModel):
    revision: str


@router.post(api_path + "/scaffold")
def change(request: Request, project_id: str, body: Starter) -> Preview | Pushed:
    ws, p = project(request, project_id)
    try:
        require_base(p, body.branch, body.revision)
        changes, modes, diff = scaffold(ws, p, **body.model_dump(exclude={"branch", "revision", "action"}))
        if body.action == "preview":
            return Preview(diff=diff or "No changes.")
        sha = commit_changes(ws, p, changes, "Create evaluation starter", executable=modes)
    except Conflict as exc:
        raise failure(409, "stale_revision", str(exc)) from exc
    except (ValueError, OSError, yaml.YAMLError) as exc:
        raise failure(422, "starter_failed", str(exc)) from exc
    return Pushed(revision=sha)


class Qualification(RevisionInput, QualificationControls):
    action: Literal["check", "qualify"]


class Queued(BaseModel):
    run_id: str


@router.post(api_path + "/qualify", status_code=202)
def qualify(request: Request, project_id: str, body: Qualification) -> Queued:
    ws, p = project(request, project_id)
    try:
        require_base(p, body.branch, body.revision)
        for name in (body.suite, body.policy):
            if name and (not name.endswith(".json") or read_file(ws, p, name) is None):
                raise WorkspaceError("Select an existing skill JSON file.")
        chat = None
        if body.action == "qualify":
            if body.suite:
                require_sandbox(body.sandbox_consent)
            # A not-ready preflight still produces a receipt without inference.
            with suppress(ValueError):
                chat = public_identity(worker_environment(ws, p.id, "chat"))
        opts = GraderOptions(
            check_suite=body.action == "check",
            chat=chat,
            **body.model_dump(exclude={"branch", "revision", "action"}),
        )
        run_id = request.app.state.jobs.enqueue(p, body.revision, GRADER, opts)
    except Conflict as exc:
        raise failure(409, "stale_revision", str(exc)) from exc
    except ValueError as exc:
        raise failure(422, "qualification_failed", str(exc)) from exc
    return Queued(run_id=run_id)


@router.get(path + "/evidence/{run_id}", name="grader_evidence")
def evidence(request: Request, project_id: str, run_id: str):
    ws, p = project(request, project_id)
    row = request.app.state.jobs.get(p.id, run_id)
    if not row or row["kind"] != GRADER.kind or row["status"] not in {"passed", "failed", "not_run"}:
        raise HTTPException(404, "No qualification evidence")
    path = ws.data_dir / "artifacts" / p.id / row["id"] / "qualification.zip"
    if not path.is_file():
        raise HTTPException(404, "No qualification evidence")
    return FileResponse(path, media_type="application/zip", filename="grader-validation.zip")
