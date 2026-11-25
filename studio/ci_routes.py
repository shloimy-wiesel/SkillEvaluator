"""Revision-bound repository automation, using only server-owned templates."""

import hashlib
import re
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from .ci_adapter import review_branch
from .ci_receipts import Publication, feedback, published
from .editing import Conflict, branches, commit_changes, project_lock, read_file, require_base
from .frontend_routes import document
from .project_api import failure, get_project
from .workspace import Project, WorkspaceError

router = APIRouter()
PAGE = "/projects/{project_id}/ci"
API = "/api/v1" + PAGE


def project(request, project_id):
    ws = request.app.state.workspace
    return ws, get_project(ws, project_id)


def is_gitlab(p):
    url = urlsplit(p.remote)
    return url.hostname != "github.com"


class CIView(BaseModel):
    project: Project
    gitlab: bool
    notice: str | None = None
    compare: str | None = None
    scan_runs: str | None = None
    workflow: str | None = None
    digest: str | None = None
    demo: str | None = None
    demo_digest: str | None = None
    demo_branch: str | None = None
    demo_target: str | None = None


def page(p, **context):
    return CIView(project=p, gitlab=is_gitlab(p), **context)


def rejected(exc):
    conflict = isinstance(exc, Conflict)
    return failure(409 if conflict else 422, "revision_conflict" if conflict else "ci_failed", str(exc))


@router.get(PAGE, name="repository_ci", include_in_schema=False)
def landing(request: Request, project_id: str):
    project(request, project_id)
    return document(request, "ci.html")


@router.get(API)
def setup(request: Request, project_id: str) -> CIView:
    _, p = project(request, project_id)
    return page(p, **feedback(request, p, "repository_ci"))


class ReviewForm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    branch: str
    revision: str
    approval: str = ""


class SetupForm(ReviewForm):
    action: Literal["review", "publish", "status"]
    score: int = Field(default=70, ge=0, le=100)
    scope: Literal["auto", "all"] = "auto"
    channel: Literal["pinned", "stable"] = "pinned"


class DemoForm(ReviewForm):
    action: Literal["review", "publish", "request"]


@router.post(API)
def operate(request: Request, project_id: str, form: SetupForm) -> CIView | Publication:
    from skillevaluator import ci_onboarding as ci

    branch, revision = form.branch, form.revision
    score, scope, channel = form.score, form.scope, form.channel
    ws, p = project(request, project_id)
    try:
        with project_lock(ws, p.id):
            require_base(p, branch, revision)
            if is_gitlab(p):
                raise WorkspaceError("Use Advanced CI setup for GitLab all-tier workflows.")
            existing = read_file(ws, p, ci.SCAN, repo_root=True)
            if form.action == "status":
                if branches(ws, p).get(branch) != revision:
                    raise Conflict("Remote branch changed; reopen it to refresh status.")
                state = "present" if existing is not None else "absent"
                publisher = read_file(ws, p, ci.PUBLISH, repo_root=True)
                publication = "present" if publisher is not None else "absent"
                return page(
                    p,
                    notice=f"Workflow {state} on remote branch {branch}. Publisher {publication}. Scan results not verified.",
                    scan_runs=(p.remote.rstrip("/").removesuffix(".git") + "/actions/workflows/skill-checks.yml")
                    if existing is not None
                    else None,
                )
            if existing is not None:
                raise WorkspaceError("Setup preserves existing workflows. This branch already has a scan.")
            if not all(re.fullmatch(r"[A-Za-z0-9._/-]+", v) for v in (p.folder, p.branch)):
                raise WorkspaceError("This folder or branch cannot be used as a literal CI selector.")
            release = None if channel == "stable" else ci.load_release(Path(ci.__file__).with_name("ci-release.json"))
            workflow = ci.render_files(release, [p.folder], score, scope, p.branch, p.name, full=False)[ci.SCAN]
            digest = hashlib.sha256(workflow.encode()).hexdigest()
            if form.action == "review":
                return page(p, workflow=workflow, digest=digest)
            if form.approval != digest:
                raise WorkspaceError("Review the generated workflow before publishing.")
            commit_changes(ws, p, {ci.SCAN: workflow.encode()}, "Set up Tier 1 skill checks", repo_root=True)
            return published(request, p, "repository_ci", "Published the reviewed workflow.")
    except WorkspaceError as exc:
        raise rejected(exc) from exc


def demo_manifest(ws, p, roots):
    def selected(path):
        return any(root == "." or path.startswith(root + "/") for root in roots)

    connected = (Path(p.folder) / "SKILL.md").as_posix()
    if selected(connected):
        return connected
    entries = ws.git(p, ["ls-tree", "-rz", p.revision], raw=True)
    if len(entries) > 16 * 1024 * 1024:
        raise WorkspaceError("Repository discovery exceeded the size limit.")
    for entry in entries.split(b"\0"):
        if not entry.startswith((b"100644 blob ", b"100755 blob ")):
            continue
        path = entry.partition(b"\t")[2].decode("utf-8", errors="replace")
        if Path(path).name == "SKILL.md" and selected(path):
            return path
    raise WorkspaceError("No tracked skill manifest matches the configured scan roots.")


@router.post(API + "/demo", name="ci_demo")
def demo(request: Request, project_id: str, form: DemoForm) -> CIView | Publication:
    from skillevaluator import ci_onboarding as ci

    branch, revision = form.branch, form.revision
    ws, p = project(request, project_id)
    try:
        with project_lock(ws, p.id):
            require_base(p, branch, revision)
            all_tiers = ci.all_tier_helpers
            scan = read_file(ws, p, all_tiers.GL_SCAN if is_gitlab(p) else all_tiers.SCAN, repo_root=True)
            all_mode = scan is not None
            if scan is None and not is_gitlab(p):
                scan = read_file(ws, p, ci.SCAN, repo_root=True)
            if scan is None:
                raise WorkspaceError("Set up checks on the default branch first.")
            head = ws.git(p, ["ls-remote", "--symref", "--", p.remote, "HEAD"], authenticated=True).splitlines()
            if f"ref: refs/heads/{branch}\tHEAD" not in head or f"{revision}\tHEAD" not in head:
                raise Conflict("Open the current remote default branch to prepare a demo.")
            try:
                if all_mode:
                    data = ci.workflow_helpers.parse_workflow(scan.decode())
                    if is_gitlab(p):
                        problem = all_tiers.gitlab_config_problem(scan.decode())
                        if problem:
                            raise WorkspaceError(problem)
                        paths = data["variables"]["SKILL_EVAL_PATHS"]
                    else:
                        inputs, problem = all_tiers._github_workflow_inputs(
                            scan.decode(), "skills", "evaluate-all-tiers.yml"
                        )
                        if problem:
                            raise WorkspaceError(problem)
                        paths = inputs["paths"]
                    roots = [ci.git_helpers.safe_relative(v) for v in paths.splitlines()]
                else:
                    roots = ci.workflow_helpers.existing_scan(scan.decode()).roots
            except (KeyError, AttributeError, TypeError, ci.SetupError, UnicodeError) as exc:
                raise WorkspaceError("Demo requires a recognized scan workflow.") from exc
            target = demo_manifest(ws, p, roots)
            saved = read_file(ws, p, target, repo_root=True)
            if saved is None:
                raise WorkspaceError("The skill manifest is missing.")
            comment = "\n<!-- SkillEvaluator onboarding demo: exercise automatic PR feedback. -->\n"
            draft = saved + comment.encode()
            digest = hashlib.sha256(p.revision.encode() + b"\0" + target.encode() + b"\0" + draft).hexdigest()
            demo_branch = all_tiers.DEMO_BRANCH if all_mode else ci.DEMO_BRANCH
            if form.action == "review":
                return page(p, demo=comment, demo_digest=digest, demo_branch=demo_branch, demo_target=target)
            if form.approval != digest:
                raise WorkspaceError("Review the demo change before publishing.")
            if form.action == "request":
                url = review_branch(
                    ws, p, {target: draft}, demo_branch, "Exercise automatic skill review feedback", repo_root=True
                )
                return published(request, p, "repository_ci", "Review request: " + url, compare=url)
            if is_gitlab(p):
                raise WorkspaceError("Choose the reviewed merge request action on GitLab.")
            commit_changes(
                ws, p, {target: draft}, "Exercise automatic skill PR feedback", new_branch=demo_branch, repo_root=True
            )
            compare = (
                f"{p.remote.rstrip('/').removesuffix('.git')}/compare/{quote(branch, safe='')}...{demo_branch}?expand=1"
            )
            return published(
                request,
                p,
                "repository_ci",
                "Demo branch published. Confirm the pull request on your Git host.",
                compare,
            )
    except WorkspaceError as exc:
        raise rejected(exc) from exc
