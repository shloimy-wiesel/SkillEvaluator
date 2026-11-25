"""Opt-in destructive smoke on an operator-provided disposable GitLab project."""

import json
import os
import time
from pathlib import Path
from uuid import uuid4

import pytest

# ruff: noqa: F811 -- pytest discovers shared fixtures by name
from test_workspace import page, playwright, running  # noqa: F401


def connect_with_tokens(page, base, config):
    page.goto(base)
    page.get_by_label("Repository URL").fill(config["remote"])
    page.get_by_label("Skill folder").fill(config.get("folder", "."))
    page.get_by_text("Self-managed GitLab").click()
    page.get_by_label("GitLab installation URL").fill(config["root"])
    page.get_by_label("Private CA certificate").fill(config.get("ca_pem", ""))
    page.get_by_text("Private repository credentials").click()
    page.get_by_label("Git username").fill(config["username"])
    page.get_by_label("Access token").fill(config["git_token"])
    page.get_by_role("button", name="Connect project").click()
    detail = page.url
    page.get_by_role("link", name="GitLab access").click()
    page.get_by_label("GitLab API token").fill(config["api_token"])
    page.get_by_role("button", name="Save API token").click()
    return detail


@pytest.mark.skipif(not os.getenv("STUDIO_GITLAB_RUNNER_CONFIG"), reason="requires isolated disposable GitLab Runner")
def test_reviewed_setup_runs_keyless_job(page, tmp_path):
    """Fresh project, main, dedicated runner, smoke-ci.yml override; see studio/GITLAB.md."""
    from studio.gitlab import instance
    from studio.workspace import Workspace

    config = json.loads(Path(os.environ["STUDIO_GITLAB_RUNNER_CONFIG"]).read_text())
    with running(tmp_path / "data") as base:
        detail = connect_with_tokens(page, base, {**config, "folder": "skills/triage"})
        ws = Workspace(tmp_path / "data")
        (project,) = ws.projects()
        lab = instance(ws, project)
        info = lab.request("GET")
        assert info["visibility"] == "private" and info["ci_config_path"] == "smoke-ci.yml"
        assert lab.namespace.count("/") >= 2 and info["default_branch"] == "main"
        page.goto(detail)
        page.get_by_role("link", name="Repository CI").click()
        page.get_by_role("link", name="Advanced CI setup").click()
        page.get_by_label("Evaluation tiers").select_option("all")
        page.get_by_label("Publication mode").select_option("save")
        page.get_by_role("button", name="Review files").click()
        playwright.expect(page.get_by_label(".gitlab-ci.yml", exact=True)).to_contain_text("skill-evaluation")
        page.get_by_role("button", name="Apply reviewed setup").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("Reviewed setup saved")
        sha = ws.get(project.id).revision
        assert sha != project.revision
        deadline = time.monotonic() + 120
        while True:
            pipelines = lab.request("GET", "/pipelines", query={"sha": sha, "ref": "main"})
            if pipelines and pipelines[0]["status"] not in {"created", "waiting_for_resource", "pending", "running"}:
                break
            assert time.monotonic() < deadline, f"No completed runner pipeline for {sha}: {pipelines}"
            time.sleep(2)
        pipeline = pipelines[0]
        page.get_by_label("Evaluation tiers").select_option("all")
        page.get_by_role("button", name="Read live status").click()
        status = page.get_by_role("status")
        playwright.expect(status).to_contain_text(f"{lab.web_url}/-/pipelines/{pipeline['id']}")
        playwright.expect(status).to_contain_text("Latest pipeline: success")
        (job,) = lab.request("GET", f"/pipelines/{pipeline['id']}/jobs")
        assert (job["name"], job["status"], job["commit"]["id"], job["runner"]["id"]) == (
            "studio-smoke",
            "success",
            sha,
            config["runner_id"],
        )


@pytest.mark.skipif(not os.getenv("STUDIO_GITLAB_SMOKE_CONFIG"), reason="requires disposable GitLab project")
def test_real_gitlab_project(page, tmp_path):
    from studio.gitlab import instance
    from studio.workspace import Workspace

    config = json.loads(Path(os.environ["STUDIO_GITLAB_SMOKE_CONFIG"]).read_text())
    branch = "studio-smoke-" + uuid4().hex[:12]
    with running(tmp_path / "data") as base:
        detail = connect_with_tokens(page, base, config)
        page.get_by_role("button", name="Check project API access").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("Project API read access confirmed")
        page.goto(detail)
        page.get_by_role("link", name="Edit skill").click()
        page.get_by_label("New branch name").fill(branch)
        page.get_by_role("button", name="Create branch").click()
        skill = page.get_by_label("SKILL.md")
        skill.fill(skill.input_value() + "\n<!-- Studio smoke -->\n")
        page.get_by_role("button", name="Save and push").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("Pushed")
    ws = Workspace(tmp_path / "data")
    (project,) = ws.projects()
    lab = instance(ws, project)
    default = lab.request("GET")["default_branch"]
    mr = lab.request(
        "POST",
        "/merge_requests",
        payload={
            "source_branch": branch,
            "target_branch": default,
            "title": f"Verify {branch}",
        },
    )
    assert mr["web_url"] == f"{lab.web_url}/-/merge_requests/{mr['iid']}"
    assert mr["sha"] == project.revision
    assert isinstance(lab.request("GET", "/pipelines", query={"sha": project.revision}), list)
