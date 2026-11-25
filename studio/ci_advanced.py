"""Browser adapter for the bundled CI wizard. All executable inputs are server-owned."""

import hashlib
import json
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Form, Request
from pydantic import BaseModel, Field, JsonValue, PlainSerializer

from skillevaluator import ci_onboarding as ci

from .ci_adapter import review_branch, worker
from .ci_receipts import Publication, feedback, published
from .ci_routes import API, PAGE, ReviewForm, project, rejected
from .editing import Conflict, branches, commit_changes, project_lock, require_base
from .frontend_routes import document
from .workspace import Project, WorkspaceError

router = APIRouter()
Provider = Literal["openai", "anthropic", "nv_build", "openai-compatible"]
LiteralText = Annotated[str, Field(pattern=r"^(?:[a-zA-Z0-9_./:@+][a-zA-Z0-9_./:@+-]*)?$", max_length=256)]
ALL = ci.all_tier_helpers
# JavaScript cannot represent every GitLab resource ID as an exact number.
PipelineId = Annotated[int, Field(gt=0, le=2**63 - 1), PlainSerializer(str, return_type=str, when_used="json")]


class Options(ReviewForm):
    action: Literal["review", "apply", "status", "receipt"]
    pipeline_id: PipelineId | None = None
    platform: Literal["auto", "github", "gitlab"] = "auto"
    tiers: Literal["one", "all"] = "one"
    mode: Literal["preview", "save", "pr"] = "save"
    channel: Literal["pinned", "stable"] = "pinned"
    paths: str = Field(default="", max_length=4096)
    default_branch: LiteralText = ""
    score: int = Field(default=70, ge=0, le=100)
    scope: Literal["auto", "all"] = "auto"
    full: Literal["auto", "hosted", "checks"] = "auto"
    release: str = Field(default="", pattern=r"^[A-Za-z0-9_-]{0,64}$")
    report_url: str = Field(default="", max_length=512)
    env_mode: Literal["docker", "local"] = "docker"
    provider: Provider = "openai"
    embedding_provider: Literal["", "openai", "nv_build", "openai-compatible"] = ""
    model: LiteralText = ""
    embedding_model: LiteralText = ""
    tier1_llm: bool = False
    tier1_provider: Literal["", "openai", "anthropic", "nv_build"] = ""
    tier1_model: LiteralText = ""
    tier3_provider: Literal["", "openai", "anthropic", "nv_build", "openai-compatible"] = ""
    tier3_model: LiteralText = ""
    base_url: LiteralText = ""
    embedding_base_url: LiteralText = ""
    tier3_base_url: LiteralText = ""
    agent_model: str = Field(default="", max_length=850)
    agents: str = Field(
        default="", pattern=r"^(?:(?:claude-code|codex|opencode)(?:,(?:claude-code|codex|opencode))*)?$"
    )
    runner: LiteralText = ""
    gateway_secret: LiteralText = "SKILL_EVAL_LLM_API_KEY"
    environment: LiteralText = "skillevaluator"
    n_attempts: int = Field(default=1, ge=1, le=10)
    n_concurrent: int = Field(default=1, ge=1, le=16)
    timeout_minutes: int = Field(default=300, ge=10, le=360)
    benchmark_pr: bool = False

    def arguments(self, p, default_branch):
        args = ["--no-input", "--default-branch", self.default_branch or default_branch]
        if self.score != 70:
            args += ["--min-score", str(self.score)]
        if self.scope != "auto":
            args += ["--scan-mode", self.scope]
        for root in self.paths.splitlines():
            if not re.fullmatch(r"[A-Za-z0-9._][A-Za-z0-9._/-]*", root):
                raise WorkspaceError("Choose literal scan roots listed for this revision.")
            args.extend(["--paths", root])
        if self.channel == "stable":
            args.extend(["--channel", "stable"])
        if self.tiers == "all":
            args.extend(["--tiers", "1,2,3", "--platform", self.platform])
        elif self.platform == "gitlab" or urlsplit(p.remote).hostname != "github.com":
            raise WorkspaceError("GitLab requires all tiers. Tier 1 alone supports github.com only.")
        else:
            args.append("--checks-only" if self.full == "checks" else "--full")
        if self.report_url and self.full == "checks":
            raise WorkspaceError("Report URL requires hosted reports.")
        if self.report_url and not self.report_url.startswith("https://"):
            raise WorkspaceError("Choose a valid HTTPS Pages URL.")
        if self.report_url:
            args.extend(["--report-url", self.report_url])
        if self.tiers == "all" and self.full != "auto":
            raise WorkspaceError("Hosted Pages is a GitHub Tier 1 option; all tiers use CI artifacts.")
        for key in ci.ALL_TIER_ONLY_OPTIONS:
            if key in ("platform", "tiers", "agent_model"):
                continue
            value = getattr(self, key)
            default = type(self).model_fields[key].default
            if value == default:
                continue
            if self.tiers != "all":
                raise WorkspaceError("Advanced model and runner options require all tiers.")
            args.append("--" + key.replace("_", "-"))
            if not isinstance(value, bool):
                args.append(str(value))
        for entry in self.agent_model.splitlines():
            if not re.fullmatch(r"(claude-code|codex|opencode)=[A-Za-z0-9_./:@+-]+", entry):
                raise WorkspaceError("Enter one literal AGENT=MODEL per line.")
            args.extend(["--agent-model", entry])
        for value in (self.base_url, self.embedding_base_url, self.tier3_base_url):
            if value and (
                urlsplit(value).scheme != "https" or not urlsplit(value).hostname or urlsplit(value).username
            ):
                raise WorkspaceError("Use credential-free HTTPS model endpoints.")
        return args


def descriptors(ws):
    directory = ws.data_dir / "ci-releases"
    if directory.is_symlink():
        return {}
    return {
        p.stem: p
        for p in sorted(directory.glob("*.json"))
        if re.fullmatch("[A-Za-z0-9_-]{1,64}", p.stem)
        and not p.is_symlink()
        and p.is_file()
        and p.stat().st_size <= 16384
    }


class Pipeline(BaseModel):
    id: PipelineId
    status: str


class Job(BaseModel):
    name: str
    status: str
    url: str


class Review(BaseModel):
    files: dict[str, str]
    plan: dict[str, JsonValue]
    manual_merge: str


class AdvancedView(BaseModel):
    project: Project
    releases: list[str]
    form: Options
    roots: list[str] = []
    discovery_error: str = ""
    notice: str | None = None
    result: Review | None = None
    digest: str | None = None
    jobs: list[Job] | None = None
    pipelines: list[Pipeline] = []
    selected: PipelineId | None = None


def view(request, p, form=None, **ctx):
    return AdvancedView(
        project=p,
        releases=["", *descriptors(request.app.state.workspace)],
        form=form or Options(branch=p.branch, revision=p.revision, action="review"),
        **ctx,
    )


@router.get(PAGE + "/advanced", name="advanced_ci", include_in_schema=False)
def advanced(request: Request, project_id: str):
    project(request, project_id)
    return document(request, "ci-advanced.html")


@router.get(API + "/advanced")
def options(request: Request, project_id: str) -> AdvancedView:
    ws, p = project(request, project_id)
    receipt = feedback(request, p, "advanced_ci")
    try:
        roots = [r["root"] for r in ci.git_helpers.discover(ws.checkout(p))]
    except ci.SetupError as exc:
        # Root discovery is advisory; live status does not require a valid scan layout.
        return view(request, p, discovery_error=str(exc), **receipt)
    return view(request, p, roots=roots, **receipt)


@router.post(API + "/advanced", response_model=AdvancedView | Publication)
def advanced_action(request: Request, project_id: str, form: Options):
    from fastapi.responses import JSONResponse

    ws, p = project(request, project_id)
    try:
        with project_lock(ws, p.id):
            require_base(p, form.branch, form.revision)
            if branches(ws, p).get(p.branch) != p.revision:
                raise Conflict("Remote branch changed. Reopen it before continuing.")
            if form.action == "status":
                result = worker(ws, p, "status", platform=form.platform, tiers=form.tiers, pipeline_id=form.pipeline_id)
                return view(request, p, form, notice=result.pop("status"), **result)
            default = ws.git(p, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"]).removeprefix("origin/")
            args = form.arguments(p, default)
            release = None
            if form.release:
                descriptor = descriptors(ws).get(form.release)
                if descriptor is None:
                    raise WorkspaceError("Choose an installed release descriptor.")
                release = descriptor.read_text()
                if form.channel == "stable":
                    raise WorkspaceError("Stable cannot use a pinned descriptor.")
            result = worker(ws, p, "prepare", args=args, mode=form.mode, release=release)
            digest = hashlib.sha256(
                json.dumps([p.id, p.revision, form.mode, args, result], sort_keys=True).encode()
            ).hexdigest()
            if form.action == "review":
                return view(request, p, form, result=result, digest=digest)
            if digest != form.approval:
                raise WorkspaceError("Review the files and options again before continuing.")
            if form.action == "receipt":
                return JSONResponse(
                    result["plan"], headers={"Content-Disposition": 'attachment; filename="ci-plan.json"'}
                )
            if form.mode == "preview":
                raise WorkspaceError("Select a publication mode and review again before applying.")
            if result["manual_merge"]:
                raise WorkspaceError("Existing GitLab pipeline requires a manual merge.")
            if form.mode == "pr":
                if (form.default_branch or p.branch) != p.branch:
                    raise WorkspaceError("Open the default branch before PR setup.")
                if form.tiers == "all":
                    if not result["files"]:
                        return published(request, p, "advanced_ci", "All-tier workflows already configured.")
                    url = review_branch(
                        ws,
                        p,
                        {k: v.encode() for k, v in result["files"].items()},
                        ALL.SETUP_BRANCH,
                        "Set up all-tier skill checks",
                        repo_root=True,
                    )
                    return published(request, p, "advanced_ci", url)
                result = worker(ws, p, "publish", args=args, mode=form.mode, reviewed=result, release=release)
                return published(request, p, "advanced_ci", result["notice"])
            if result["files"]:
                commit_changes(
                    ws,
                    p,
                    {k: v.encode() for k, v in result["files"].items()},
                    "Set up reviewed skill evaluation CI",
                    repo_root=True,
                )
            return published(request, p, "advanced_ci", "Reviewed setup saved. Host settings were not changed.")
    except (WorkspaceError, ci.SetupError) as exc:
        raise rejected(exc) from exc


@router.post(PAGE + "/advanced", include_in_schema=False)
def download_receipt(request: Request, project_id: str, form: Annotated[Options, Form()]):
    if form.action != "receipt":
        raise rejected(WorkspaceError("Use the versioned API for CI setup."))
    return advanced_action(request, project_id, form)
