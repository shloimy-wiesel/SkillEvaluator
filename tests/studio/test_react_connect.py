"""React workspace, real Chromium and a private HTTPS smart-Git remote."""

# ruff: noqa: F401,F811 -- shared pytest fixtures
from test_workspace import before_push, page, playwright, private_remote, running


def test_workspace_api_corrects_github_url_and_keeps_errors_secret_free(page, tmp_path):
    with running(tmp_path / "volume") as base:
        endpoint = base + "/api/v1/projects"
        result = page.request.post(endpoint, data={"remote": "https://github.com/mattpocock/skills/tree/main/skills"})
        assert result.status == 422
        assert "https://github.com/mattpocock/skills.git" in result.json()["detail"]["message"]
        secret = "do-not-echo-test-secret"
        for body in ({"token": {"bad": secret}}, {"remote": f"https://user:{secret}@git.example.com/a.git"}):
            result = page.request.post(endpoint, data=body)
            assert result.status == 422
            assert secret not in result.text()
        assert page.request.post(endpoint, headers={"Origin": "https://another.example"}, data={}).status == 403
        for path in ("/projects/missing", "/api/v1/missing", "/_next/static/missing.js", "/other"):
            assert page.request.get(base + path).status == 404


def test_correct_clone_link_and_reopen_private_gitlab_project(
    page, private_remote, tmp_path, loopback_tls, monkeypatch
):
    url, token = private_remote
    root = url.rsplit("/", 1)[0] + "/forge"
    remote = root + "/group/team/handbook.git"
    nested = tmp_path / "server/forge/group/team"
    nested.mkdir(parents=True)
    (tmp_path / "server/handbook.git").rename(nested / "handbook.git")
    monkeypatch.delenv("GIT_SSL_CAINFO")
    volume = tmp_path / "volume"
    with running(volume) as base:
        page.goto(base)
        page.get_by_label("Repository URL").fill(remote.removesuffix(".git") + "/-/tree/main/skills")
        page.get_by_role("button", name="Connect project").click()
        playwright.expect(page.locator("main").get_by_role("alert")).to_contain_text("clone URL")
        page.get_by_label("Repository URL").fill(remote)
        page.get_by_label("Skill folder").fill("skills/triage")
        page.get_by_text("Self-managed GitLab").click()
        page.get_by_label("GitLab installation URL").fill(root)
        page.get_by_label("Private CA certificate").fill(loopback_tls[1].read_text())
        page.get_by_text("Private repository credentials").click()
        page.get_by_label("Git username").fill("author")
        page.get_by_label("Access token").fill(token)
        page.get_by_role("button", name="Connect project").click()
        playwright.expect(page.get_by_role("heading", name="handbook")).to_be_visible()
        path = page.url.removeprefix(base)
        revision = page.get_by_text("Checkout revision").locator("..").locator("dd").inner_text()
        assert len(revision) == 40
    with running(volume) as base:
        page.goto(base)
        page.get_by_role("link", name="handbook").click()
        playwright.expect(page.get_by_text(revision)).to_be_visible()
        assert page.url == base + path
        page.reload()
        page.get_by_role("button", name="Check remote access").click()
        playwright.expect(page.get_by_role("status")).to_have_text("Remote access confirmed.")
        assert token not in page.request.get(base + "/api/v1" + path).text()
        assert page.request.get(base + "/api/v1" + path).json()["project"]["remote"] == remote
