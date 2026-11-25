"""Revision-bound repository automation, using only server-owned templates."""

import hashlib
import re
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Form, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .ci_adapter import review_branch
from .editing import Conflict, branches, commit_changes, project_lock, read_file, require_base
from .workspace import WorkspaceError

router = APIRouter(prefix="/projects/{project_id}/ci")


def project(request, project_id):
    ws = request.app.state.workspace
    p = ws.get(project_id)
    if p is None:
        raise HTTPException(404, "Unknown project")
    return ws, p


def is_gitlab(p):
    url = urlsplit(p.remote)
    return url.hostname != "github.com"


def page(request, p, status=200, **context):
    return request.app.state.templates.TemplateResponse(
        request=request, name="ci.html", context={"project": p, "gitlab": is_gitlab(p), **context}, status_code=status
    )


@router.get("", name="repository_ci")
def landing(request: Request, project_id: str):
    _, p = project(request, project_id)
    return page(request, p, gitlab=is_gitlab(p))


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


@router.post("")
def operate(request: Request, project_id: str, form: Annotated[SetupForm, Form()]):
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
                    request,
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
                return page(request, p, workflow=workflow, digest=digest, score=score, scope=scope, channel=channel)
            if form.approval != digest:
                raise WorkspaceError("Review the generated workflow before publishing.")
            commit_changes(ws, p, {ci.SCAN: workflow.encode()}, "Set up Tier 1 skill checks", repo_root=True)
            return page(request, ws.get(p.id), notice="Published the reviewed workflow.")
    except WorkspaceError as exc:
        return page(request, p, 409 if isinstance(exc, Conflict) else 422, error=str(exc))


@router.post("/demo", name="ci_demo")
def demo(request: Request, project_id: str, form: Annotated[DemoForm, Form()]):
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
            if not any(root in (".", p.folder) or p.folder.startswith(root + "/") for root in roots):
                raise WorkspaceError("The workflow does not scan this skill folder.")
            saved = read_file(ws, p, "SKILL.md")
            if saved is None:
                raise WorkspaceError("The skill manifest is missing.")
            comment = "\n<!-- SkillEvaluator onboarding demo: exercise automatic PR feedback. -->\n"
            draft = saved + comment.encode()
            digest = hashlib.sha256(draft).hexdigest()
            demo_branch = all_tiers.DEMO_BRANCH if all_mode else ci.DEMO_BRANCH
            if form.action == "review":
                return page(request, p, demo=comment, demo_digest=digest, demo_branch=demo_branch)
            if form.approval != digest:
                raise WorkspaceError("Review the demo change before publishing.")
            if form.action == "request":
                url = review_branch(ws, p, {"SKILL.md": draft}, demo_branch, "Exercise automatic skill review feedback")
                return page(request, p, notice="Created review request: " + url, compare=url)
            commit_changes(ws, p, {"SKILL.md": draft}, "Exercise automatic skill PR feedback", new_branch=demo_branch)
            compare = (
                f"{p.remote.rstrip('/').removesuffix('.git')}/compare/{quote(branch, safe='')}...{demo_branch}?expand=1"
            )
            return page(
                request, p, notice="Demo branch published. Confirm the pull request on your Git host.", compare=compare
            )
    except WorkspaceError as exc:
        return page(request, p, 409 if isinstance(exc, Conflict) else 422, error=str(exc))
