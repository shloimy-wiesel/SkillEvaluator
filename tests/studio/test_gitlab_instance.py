"""Opt-in destructive smoke on an operator-provided disposable GitLab project."""

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

# ruff: noqa: F811 -- pytest discovers shared fixtures by name
from test_workspace import page, playwright, running  # noqa: F401


@pytest.mark.skipif(not os.getenv("STUDIO_GITLAB_SMOKE_CONFIG"), reason="requires disposable GitLab project")
def test_real_gitlab_project(page, tmp_path):
    from studio.gitlab import instance
    from studio.workspace import Workspace

    config = json.loads(Path(os.environ["STUDIO_GITLAB_SMOKE_CONFIG"]).read_text())
    branch = "studio-smoke-" + uuid4().hex[:12]
    with running(tmp_path / "data") as base:
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
        page.get_by_role("link", name="GitLab access").click(timeout=5000)
        page.get_by_label("GitLab API token").fill(config["api_token"])
        page.get_by_role("button", name="Save API token").click()
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
