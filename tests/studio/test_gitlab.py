"""Real Git smart HTTPS; the GitLab API here is a protocol fixture."""

import subprocess

# ruff: noqa: F811 -- pytest discovers shared fixtures by name
from test_workspace import before_push, connect, page, playwright, private_remote, running  # noqa: F401


def test_self_managed_author_reopens_and_pushes(page, private_remote, tmp_path, api_handler, monkeypatch):
    url, git_token = private_remote
    root = url.rsplit("/", 1)[0].replace("127.0.0.1", "localhost") + "/forge"
    repo = tmp_path / "server/forge/engineering/platform/handbook.git"
    repo.parent.mkdir(parents=True)
    (tmp_path / "server/handbook.git").rename(repo)
    monkeypatch.delenv("GIT_SSL_CAINFO")
    volume = tmp_path / "volume"
    requests = []

    def project_api(handler):
        if "/api/v4/" not in handler.path:
            return False
        requests.append((handler.path, handler.headers.get("PRIVATE-TOKEN"), handler.headers.get("Authorization")))
        handler.send_response(200)
        handler.end_headers()
        handler.wfile.write(b'{"path_with_namespace":"engineering/platform/handbook"}')
        return True

    api_handler.append(project_api)
    with running(volume) as base:
        page.goto(base)
        page.get_by_text("Self-managed GitLab").click(timeout=1500)
        page.get_by_label("GitLab installation URL").fill(root)
        page.get_by_label("Private CA certificate").fill((tmp_path / "certificate.pem").read_text())
        connect(page, root + "/engineering/platform/handbook.git", git_token, "skills/triage")
        playwright.expect(page.get_by_role("heading", name="handbook")).to_be_visible()
        page.get_by_role("link", name="GitLab access").click(timeout=1500)
        page.get_by_role("button", name="Check project API access").click()
        playwright.expect(page.get_by_role("alert")).to_contain_text("separate GitLab API token")
        page.get_by_label("GitLab API token").fill("fixture-read-api")
        page.get_by_role("button", name="Save API token").click()
    with running(volume) as base:
        page.goto(base)
        page.get_by_role("link", name="handbook").click()
        detail = page.url
        page.get_by_role("link", name="GitLab access").click()
        page.get_by_role("button", name="Check project API access").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("Project API read access confirmed")
        assert requests == [("/forge/api/v4/projects/engineering%2Fplatform%2Fhandbook", "fixture-read-api", None)]
        assert (
            page.get_by_role("link", name="Merge requests").get_attribute("href")
            == root + "/engineering/platform/handbook/-/merge_requests"
        )
        assert "fixture-read-api" not in page.content()
        page.goto(detail)
        page.get_by_role("link", name="Edit skill").click()
        page.get_by_label("New branch name").fill("review/private")
        page.get_by_role("button", name="Create branch").click()
        page.get_by_label("SKILL.md").fill("# Reviewed\n")
        page.get_by_role("button", name="Save and push").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("Pushed")
        assert (
            subprocess.check_output(["git", "show", "review/private:skills/triage/SKILL.md"], cwd=repo)
            == b"# Reviewed\n"
        )


def test_credentials_do_not_follow_git_or_api_redirects(page, private_remote, tmp_path, api_handler):
    remote, token = private_remote
    root = remote.rsplit("/", 1)[0]
    redirect = root.replace("127.0.0.1", "localhost") + "/destination"
    leaked = []

    def redirects(handler):
        if handler.path.startswith("/destination"):
            leaked.append(handler.path)
            handler.send_response(403)
        elif "/api/v4/" in handler.path or handler.path.startswith("/other/"):
            handler.send_response(302)
            handler.send_header("Location", redirect)
        else:
            return False
        handler.end_headers()
        return True

    api_handler.append(redirects)
    repo = tmp_path / "server/team/handbook.git"
    repo.parent.mkdir()
    (tmp_path / "server/handbook.git").rename(repo)
    with running(tmp_path / "volume") as base:
        page.goto(base)
        page.get_by_text("Self-managed GitLab").click()
        page.get_by_label("GitLab installation URL").fill(root.replace("127.0.0.1", "localhost"))
        connect(page, root + "/team/handbook.git", token, "skills/triage")
        playwright.expect(page.locator("main").get_by_role("alert")).to_contain_text("match the repository")
        for namespace in ("other", "team"):
            page.goto(base)
            page.get_by_text("Self-managed GitLab").click()
            page.get_by_label("GitLab installation URL").fill(root)
            connect(page, root + f"/{namespace}/handbook.git", token, "skills/triage")
            if namespace == "other":
                playwright.expect(page.locator("main").get_by_role("alert")).to_contain_text("Git could not open")
        page.get_by_role("link", name="GitLab access").click()
        page.get_by_label("GitLab API token").fill("fixture-api")
        page.get_by_role("button", name="Save API token").click()
        page.get_by_role("button", name="Check project API access").click()
        playwright.expect(page.get_by_role("alert")).to_contain_text("redirected")
    assert leaked == []
