"""Revision-pinned Tier 2 runs and private, immutable provider snapshots."""

import json
import os
import re
import subprocess
import sys
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from skillevaluator.constants import (
    SIMILARITY_DEFAULT_MAX_ENTRIES,
    SIMILARITY_DEFAULT_MAX_SCALAR_COMPARISONS,
    SIMILARITY_MAX_ENTRIES,
)
from skillevaluator.provider_config import resolve_embedding_provider, resolve_llm_provider

from .jobs import JobDefinition, Outcome
from .operator_env import operator_env
from .provider_snapshots import exposes_credential, seal, unseal
from .providers import MODEL, database, worker_environment
from .runs import project_for
from .workspace import WorkspaceError

router = APIRouter(prefix="/projects/{project_id}/overlap")
Format = Literal["cli", "json", "html", "markdown", "junit", "sarif", "github"]
ARTIFACTS = {
    "catalog.json",
    "overlap.html",
    "overlap.md",
    "overlap.json",
    "overlap.junit.xml",
    "overlap.sarif.json",
    "github.txt",
}


class Provider(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: str
    model: str
    base_url: str | None
    region: str | None


class Inputs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal["direct", "similarity", "context", "dedup"] = "direct"
    threshold: float = Field(default=0.8, ge=0, le=1)
    similarity_threshold: float = Field(default=0.75, ge=0, le=1)
    full_body: bool = False
    catalog: str = ""
    collection: str = ""
    content_type: Literal["auto", "skill", "rules", "workflows"] = "auto"
    save_catalog: bool = False
    max_entries: int = Field(SIMILARITY_DEFAULT_MAX_ENTRIES, ge=1, le=SIMILARITY_MAX_ENTRIES)
    max_scalar_comparisons: int = Field(SIMILARITY_DEFAULT_MAX_SCALAR_COMPARISONS, ge=1)
    formats: tuple[Format, ...] | None = None


class Submission(Inputs):
    sha: str
    model: str = ""
    llm_model: str = ""

    def check(self, dirs, catalogs):
        if self.full_body and not self.catalog and self.action == "direct":
            raise WorkspaceError("Full-body direct comparison requires a catalog.")
        if (self.catalog and self.catalog not in catalogs) or (self.collection and self.collection not in dirs):
            raise WorkspaceError("Choose inputs from the selected commit.")
        if self.catalog and self.save_catalog:
            raise WorkspaceError("Select an input catalog or save a new catalog, not both.")
        if self.action != "similarity" and (
            self.save_catalog
            or self.collection
            or self.content_type != "auto"
            or self.max_entries != SIMILARITY_DEFAULT_MAX_ENTRIES
            or self.max_scalar_comparisons != SIMILARITY_DEFAULT_MAX_SCALAR_COMPARISONS
        ):
            raise WorkspaceError("Collection and indexing controls require the similarity check.")
        if (self.catalog or self.save_catalog) and self.content_type not in ("skill", "auto"):
            raise WorkspaceError("Catalogs support skill content only.")
        if self.action in ("context", "dedup") and (self.catalog or self.full_body):
            raise WorkspaceError("Catalog and full-body options require catalog comparison or similarity.")
        if (self.action == "direct" and (self.model or self.llm_model)) or (
            self.action == "similarity" and self.llm_model
        ):
            raise WorkspaceError("Choose model overrides only for the focused checks that use them.")


class OverlapOptions(Inputs):
    snapshot: str
    chat: Provider | None
    embeddings: Provider


def snapshot(workspace, project_id, action, *, model="", llm_model="", **options):
    private = {}
    public = {"chat": None}
    for role, resolve in (("embeddings", resolve_embedding_provider), ("chat", resolve_llm_provider)):
        if role == "chat" and action == "similarity":
            continue
        override = model if role == "embeddings" else llm_model
        if override and not MODEL.fullmatch(override):
            raise WorkspaceError("Invalid model override.")
        try:
            env = worker_environment(workspace, project_id, role)
            if override:
                prefix = "SKILL_EVAL_EMBEDDING_" if role == "embeddings" else "SKILL_EVAL_LLM_"
                env[prefix + "MODEL"] = override
            if env.get("SKILL_EVAL_LLM_PROVIDER") == "bedrock":
                env["AWS_REGION"] = os.environ.get("AWS_REGION", "us-west-2")
            config = resolve(env)
        except ValueError as exc:
            raise WorkspaceError(f"Complete the saved {role} provider settings first.") from exc
        private[role] = asdict(config)
        public[role] = Provider(**{name: getattr(config, name) for name in Provider.model_fields})
    frozen = OverlapOptions(snapshot=uuid4().hex, action=action, **public, **options)
    if exposes_credential(frozen, *(p["api_key"] for p in private.values())):
        raise WorkspaceError("Keep credentials out of public settings.")
    with closing(database(workspace)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS overlap_snapshots
                    (project TEXT, id TEXT, profiles BLOB NOT NULL, PRIMARY KEY(project, id))""")
        db.execute(
            "INSERT INTO overlap_snapshots VALUES (?,?,?)",
            (project_id, frozen.snapshot, seal(workspace, private)),
        )
    return frozen


def evaluate(ctx, options):
    catalog = ctx.input_file(options.catalog) if options.catalog else None
    target = ctx.skill
    if options.collection:
        target = ctx.root / options.collection
        if (
            not target.is_relative_to(ctx.root)
            or target.resolve() != target
            or not target.is_dir()
            or ".git" in target.relative_to(ctx.root).parts
            or any(p.is_symlink() for p in target.rglob("*"))
        ):
            raise WorkspaceError("Select an unlinked collection in the pinned repository.")
    with closing(database(ctx.workspace)) as db:
        row = db.execute(
            "SELECT profiles FROM overlap_snapshots WHERE project=? AND id=?", (ctx.project_id, options.snapshot)
        ).fetchone()
    if not row:
        raise WorkspaceError("Saved provider snapshot is unavailable.")
    profiles = unseal(ctx.workspace, row[0])
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHON_DOTENV_DISABLED": "1"}
    allow = ["SSL_CERT_FILE"]
    if options.chat and options.chat.provider == "bedrock":
        allow += [
            "AWS_REGION",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "AWS_ROLE_ARN",
            "AWS_WEB_IDENTITY_TOKEN_FILE",
        ]
    env.update(operator_env(*allow))
    ctx.progress("Evaluating semantic overlap")
    payload = {
        "options": options.model_dump(),
        "profiles": profiles,
        "skill": str(target.relative_to(ctx.root.parent)),
        "artifacts": str(ctx.artifacts),
        "root": str(ctx.root.relative_to(ctx.root.parent)),
        "catalog": str(catalog.relative_to(ctx.root.parent)) if catalog else None,
    }
    run = subprocess.run(
        [sys.executable, "-I", str(Path(__file__).with_name("overlap_worker.py"))],
        cwd=ctx.root.parent,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=600,
        check=True,
    )
    result = json.loads(run.stdout)
    if result.get("error") == "catalog_preflight":
        raise WorkspaceError("Invalid or incompatible catalog. Check its schema, endpoint, model and embedding mode.")
    return Outcome(**result)


OVERLAP = JobDefinition("tier2-overlap-v1", OverlapOptions, evaluate)


def choices(workspace, project, sha):
    if not re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", sha):
        raise WorkspaceError("Choose a full commit SHA.")
    if workspace.git(project, ["cat-file", "-t", sha]) != "commit":
        raise WorkspaceError("Choose a commit in this project.")
    dirs, catalogs, blocked = {"."}, set(), set()
    for row in workspace.git(project, ["ls-tree", "-rz", sha]).rstrip("\0").split("\0"):
        header, _, name = row.partition("\t")
        if not name:
            continue
        path = Path(name)
        if header.startswith(("120000 ", "160000 ")):
            blocked.update(str(p) for p in path.parents)
        else:
            dirs.update(str(p) for p in path.parents)
            if path.suffix.lower() == ".json":
                catalogs.add(name)
    return sorted(dirs - blocked), sorted(catalogs)


@router.get("", name="overlap_form")
def index(request: Request, project_id: str, sha: str = ""):
    project = project_for(request, project_id)
    sha = sha or project.revision
    try:
        dirs, catalogs = choices(request.app.state.workspace, project, sha)
    except WorkspaceError as exc:
        raise HTTPException(422, str(exc)) from exc
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="overlap/index.html",
        context={
            "project": project,
            "sha": sha,
            "dirs": dirs,
            "catalogs": catalogs,
            "entries": SIMILARITY_DEFAULT_MAX_ENTRIES,
            "scalars": SIMILARITY_DEFAULT_MAX_SCALAR_COMPARISONS,
        },
    )


@router.post("")
def queue(request: Request, project_id: str, form: Annotated[Submission, Form()]):
    project = project_for(request, project_id)
    try:
        workspace = request.app.state.workspace
        form.check(*choices(workspace, project, form.sha))
        options = snapshot(workspace, project_id, **form.model_dump(exclude={"sha"}))
        run_id = request.app.state.jobs.enqueue(project, form.sha, OVERLAP, options)
    except WorkspaceError as exc:
        return request.app.state.templates.TemplateResponse(
            request=request,
            name="overlap/index.html",
            status_code=422,
            context={"project": project, "sha": form.sha, "error": str(exc)},
        )
    return RedirectResponse(request.url_for("run_detail", project_id=project_id, run_id=run_id), 303)


@router.get("/{run_id}/files/{name}", name="overlap_artifact")
def artifact(request: Request, project_id: str, run_id: str, name: str):
    run = request.app.state.jobs.get(project_id, run_id)
    if (
        not run
        or run["kind"] != OVERLAP.kind
        or name not in ARTIFACTS
        or name not in json.loads(run["report"] or "{}").get("studio_artifacts", [])
    ):
        raise HTTPException(404)
    path = request.app.state.workspace.data_dir / "artifacts" / project_id / run_id / name
    return FileResponse(
        path,
        filename=name,
        media_type="application/octet-stream",
        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"},
    )
