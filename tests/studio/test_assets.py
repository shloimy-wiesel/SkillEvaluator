import subprocess

# ruff: noqa: F811
from test_workspace import before_push, connect, page, playwright, private_remote, running  # noqa: F401


def test_custom_grader_preview_and_push(page, tmp_path, private_remote):
    remote = tmp_path / "server/handbook.git"
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Evaluation assets").click(timeout=2000)
        form = page.get_by_role("form", name="Custom grader")
        form.get_by_label("Language").select_option("shell")
        form.get_by_role("button", name="Preview").click()
        playwright.expect(page.get_by_label("Change preview")).to_contain_text("evals/grader.sh")
        assert subprocess.check_output(["git", "rev-list", "--count", "main"], cwd=remote).strip() == b"1"
        page.get_by_role("button", name="Commit and push").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("Pushed")
        assert subprocess.check_output(
            ["git", "ls-tree", "main", "skills/triage/evals/grader.sh"], cwd=remote
        ).startswith(b"100755")
        assert b"default_plus_custom" in subprocess.check_output(
            ["git", "show", "main:skills/triage/evals/config.yml"], cwd=remote
        )


def test_native_harbor_starter(page, tmp_path, private_remote):
    remote = tmp_path / "server/handbook.git"
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Evaluation assets").click()
        form = page.get_by_role("form", name="Native Harbor task")
        form.get_by_label("Case ID").fill("audit-log", timeout=2000)
        form.get_by_role("button", name="Preview").click()
        playwright.expect(page.get_by_label("Change preview")).to_contain_text("nvidia/audit-log")
        page.get_by_role("button", name="Commit and push").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("Pushed")
        tree = subprocess.check_output(["git", "ls-tree", "-r", "main", "skills/triage/evals"], cwd=remote).decode()
        assert "config.yml" not in tree
        assert any(row.startswith("100755") and row.endswith("/audit-log/tests/test.sh") for row in tree.splitlines())
