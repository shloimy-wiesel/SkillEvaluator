"""The run workspace reads and writes project-scoped JSON."""

import pytest
from test_workspace import connect, playwright, running

pytest_plugins = ("test_workspace",)


def test_run_workspace_reads_pinned_history_and_recovers_from_invalid_sha(page, private_remote, tmp_path):
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("heading", name="handbook").wait_for()
        endpoint = page.url.replace(base, base + "/api/v1") + "/runs"
        page.get_by_role("link", name="Evaluation runs").click()
        assert page.request.get(endpoint).status == 200
        sha = page.get_by_label("Commit SHA").input_value()
        page.get_by_label("Commit SHA").fill("bad")
        page.get_by_role("button", name="Queue static checks").click()
        playwright.expect(page.locator("main").get_by_role("alert")).to_contain_text("full commit SHA")
        playwright.expect(page.get_by_label("Commit SHA")).to_have_value("bad")
        page.get_by_label("Commit SHA").fill(sha)
        page.get_by_role("button", name="Queue static checks").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("failed")
        run = page.request.get(endpoint).json()["runs"][0]
        assert run["sha"] == sha
        assert page.request.get(endpoint + "/" + run["id"]).json()["run"]["sha"] == sha


@pytest.mark.parametrize(
    ("feature", "field"), [("installation", "changed"), ("overlap", "catalogs"), ("live", "profiles")]
)
def test_feature_inputs_are_project_scoped_json(page, private_remote, tmp_path, feature, field):
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        endpoint = page.url.replace(base, base + "/api/v1") + "/" + feature
        response = page.request.get(endpoint)
        assert response.ok
        assert isinstance(response.json()[field], list)
        assert private_remote[1] not in response.text()
        assert page.request.get(base + "/api/v1/projects/missing/" + feature).status == 404


def test_active_history_refresh_preserves_next_launch_draft(page, private_remote, tmp_path):
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        endpoint = page.url.replace(base, base + "/api/v1") + "/runs"
        view = page.request.get(endpoint).json()
        run = {"id": "fixture", "sha": view["project"]["revision"], "kind": "tier1-static", "created": "2026-11-25"}

        def respond(route):
            route.fulfill(json={**view, "runs": [run]})

        run["status"] = "running"
        page.route(endpoint, respond)
        page.get_by_role("link", name="Run history").click()
        page.get_by_label("Commit SHA").fill("next revision")
        playwright.expect(page.locator("#history")).to_contain_text("running")
        run["status"] = "passed"
        playwright.expect(page.locator("#history")).to_contain_text("passed")
        playwright.expect(page.get_by_label("Commit SHA")).to_have_value("next revision")
