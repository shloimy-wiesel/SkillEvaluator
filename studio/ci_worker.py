"""One invocation of the installed CI engine in a disposable, credential-scoped checkout."""

import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console

from skillevaluator import ci_onboarding as ci

all_tiers = ci.all_tier_helpers


def invoke(command, args):
    return command.main(args=args, standalone_mode=False)


def run(q):
    if q["gitlab_root"]:
        os.environ["SKILLEVALUATOR_GITLAB_API_URL"] = q["gitlab_root"] + "/api/v4"
    host, origin, name = all_tiers._parse_origin(q["remote"])
    platform = "github" if host == "github.com" else "gitlab"
    if platform == "github":
        ci.git_helpers.parse_remote(q["remote"])
    if platform == "github" and q["token"]:
        os.environ["GH_TOKEN"] = q["token"]
    output = io.StringIO()
    ci.console = Console(file=output, force_terminal=False, width=2000, highlight=False)
    if q["task"] == "admission":
        info = all_tiers.Client(ci, platform, origin, name).info()
        if info["default_branch"] != q["branch"]:
            raise ci.SetupError("Open the current default branch before creating a review request.")
        return {}
    if q["task"] in ("review_request", "existing_review"):
        client = all_tiers.Client(ci, platform, origin, name)
        if q["task"] == "existing_review":
            reviews = client.reviews(q["head"])
            if len(reviews) != 1:
                raise ci.SetupError("Inspect the existing branch on the host; no unique open review was found.")
            item = reviews[0]
            matches = (
                item["head"]["sha"] == q["tip"]
                and item["head"]["ref"] == q["head"]
                and item["base"]["ref"] == q["branch"]
                and item["head"]["repo"]["full_name"] == name
            )
            value = item["html_url"]
            if not matches:
                raise ci.SetupError("The open review has a different revision or target. Inspect it on the host.")
        else:
            value = client.api("POST", "/pulls", {"base": q["branch"], "head": q["head"], "title": q["title"]})[
                "html_url"
            ]
        pattern = r"/pull/[0-9]+"
        if not re.fullmatch(re.escape(origin + "/" + name) + pattern, value):
            raise ci.SetupError("Inspect the published branch on the host; unexpected review URL.")
        return {"notice": value}
    repo = Path.cwd() / "snapshot"
    git = ci.git_helpers.git
    git(Path.cwd(), "clone", "--local", "--no-checkout", "--", q["checkout"], str(repo), network=True)
    git(repo, "remote", "set-url", "origin", q["remote"])
    git(repo, "checkout", "--detach", q["revision"])
    git(repo, "config", "user.name", "Studio")
    git(repo, "config", "user.email", "studio@localhost")
    if q["task"] == "status":
        args = ["--repo", str(repo), "--platform", q["platform"]]
        if q["tiers"] == "all":
            args += ["--tiers", "1,2,3"]
        invoke(ci.status, args)
        return {"status": output.getvalue()}
    args = q["args"]
    full = "--full" in args
    tiers = "--tiers" in args
    # Discovery, validation, descriptors and generated YAML all belong to the installed CLI.
    for item in ci.git_helpers.discover(repo):
        literal(item["root"])
    for branch in (q["branch"], args[args.index("--default-branch") + 1]):
        literal(branch)
    receipt = Path.cwd() / "plan.json"
    options = list(args)
    descriptor = Path(ci.__file__).with_name("ci-release-all-tiers.json" if tiers else "ci-release.json")
    if q.get("release") is not None:
        descriptor = Path.cwd() / "descriptor.json"
        descriptor.write_text(q["release"])
        options += ["--release", str(descriptor)]
    custom = None
    if full and q["mode"] != "preview" and "--report-url" in options:
        index = options.index("--report-url")
        custom = options[index + 1]
        del options[index : index + 2]
    gitlab_preview = tiers and platform == "gitlab"
    invoke(
        ci.init,
        [*options, "--repo", str(repo), "--mode", "preview" if gitlab_preview else "save", "--output", str(receipt)],
    )
    plan = json.loads(receipt.read_text())
    allowed = {
        ci.SCAN,
        ci.PUBLISH,
        all_tiers.SCAN,
        all_tiers.FEEDBACK,
        all_tiers.ALTERNATE_FEEDBACK,
        all_tiers.GL_SCAN,
        all_tiers.GL_FEEDBACK,
    }
    if not set(plan["changed_files"]) <= allowed:
        raise ci.SetupError("Unexpected generated workflow path.")
    manual_merge = ""
    if gitlab_preview:
        generated = all_tiers.render(
            ci, repo, plan["release"], platform, plan["default_branch"], plan["selected_roots"], plan["options"]
        )
        files = {path: generated[path] for path in plan["changed_files"]}
        if all_tiers._gitlab_root_needs_merge(repo, platform, generated):
            output.seek(0)
            output.truncate()
            all_tiers._print_gitlab_root_merge_steps(ci, (repo / all_tiers.GL_SCAN).read_text())
            manual_merge = output.getvalue()
    else:
        files = {path: (repo / path).read_text() for path in plan["changed_files"]}
    # Restore the reviewed base for read-only preflight and PR-mode execution.
    git(repo, "reset", "--hard", q["revision"])
    git(repo, "clean", "-fdx")
    expected = None
    if full and q["mode"] != "preview":
        state = ci.remote_preflight(repo, name, plan["default_branch"], True)
        url = ci.report_url(name, custom or state["report_url"], verified_private_url=state["verified_private_url"])
        existing = (
            ci.workflow_helpers.existing_scan((repo / ci.SCAN).read_text()) if (repo / ci.SCAN).exists() else None
        )
        expected = {ci.SCAN: existing.text} if existing else None
        release = None if plan["channel"] == "stable" else ci.load_release(descriptor)
        generated = ci.render_files(
            release,
            plan["selected_roots"],
            plan["min_score"],
            plan["scan_mode"],
            plan["default_branch"],
            name,
            True,
            url,
            existing=existing,
            verified_private_url=state["verified_private_url"],
        )
        generated = ci.bind_caller_approval(repo, generated)
        plan.update(
            report_url=url,
            scan_blob=ci.caller_approval(generated),
            changed_files=ci.check_files(repo, generated, expected),
        )
        files = {k: generated[k] for k in plan["changed_files"]}
    if (
        tiers
        and platform == "github"
        and all_tiers.SCAN in files
        and ci.blob_id(files[all_tiers.SCAN]) != ci.committed_blob(repo, all_tiers.SCAN, files[all_tiers.SCAN])
    ):
        raise ci.SetupError("Git attributes transform the caller; manual approval is required.")
    if full and ci.SCAN in files and ci.blob_id(files[ci.SCAN]) != plan["scan_blob"]:
        raise ci.SetupError("Git attributes transform the scan. Review its approval manually.")
    plan.update(requested_action=q["mode"], action="preview")
    review = {"plan": plan, "files": files, "manual_merge": manual_merge}
    if q["task"] == "prepare":
        return review
    if q["reviewed"] != review:
        raise ci.SetupError("The plan changed. Review it again.")
    if not full:
        generated = {ci.SCAN: files.get(ci.SCAN) or (repo / ci.SCAN).read_text()}
    try:
        url = ci.create_setup(repo, name, plan["default_branch"], generated, full, plan, expected=expected)
    except ci.SetupError as exc:
        raise ci.SetupError(
            str(exc) + " Completed steps: " + (", ".join(plan["completed_steps"]) or "none confirmed")
        ) from exc
    return {"notice": url or "Host configuration verified."}


def literal(text):
    if not re.fullmatch("[A-Za-z0-9._/-]+", text):
        raise ci.SetupError("Only literal branch and folder selectors are supported.")


if __name__ == "__main__":
    try:
        result = run(json.load(sys.stdin))
    except (click.ClickException, ci.SetupError) as exc:
        result = {"error": str(exc)}
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        result = {"error": "CI host or checkout unavailable. Verify the project, permissions and repository state."}
    print(json.dumps(result))  # noqa: T201
