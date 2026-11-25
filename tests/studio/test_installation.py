import subprocess
import sys

from test_workspace import connect, running

pytest_plugins = ("test_workspace",)


def test_installed_version_context_help_and_safe_detail(page, private_remote, tmp_path):
    version = subprocess.check_output(
        [sys.executable, "-I", "-c", "from skillevaluator.cli import cli;cli()", "--version"], text=True
    ).strip()
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Installation and changed files").click(timeout=2000)
        assert version in page.locator("main").inner_text()
        for topic, expected in [
            ("root", "--version"),
            ("tier1", "quality-check"),
            ("tier2", "dedup-scan"),
            ("tier3", "import-traces"),
            ("precommit-run", "--quality-config"),
        ]:
            page.get_by_label("Help topic").select_option(topic)
            page.get_by_role("button", name="Show help").click()
            assert expected in page.get_by_label("Installed command help").inner_text()
        page.get_by_text("Diagnostic detail", exact=True).click()
        detail = page.locator("details[open]").inner_text()
        assert sys.version.split()[0] in detail and "skills/triage" in detail
        assert private_remote[1] not in page.content() and str(tmp_path) not in detail


def test_changed_files_reach_only_affected_skills(page, private_remote, tmp_path):
    seed = tmp_path / "seed"
    other = seed / "skills" / "release"
    other.mkdir()
    (other / "SKILL.md").write_text(
        "---\nname: release\ndescription: Prepare a release for distribution and verification.\n---\n# Release\n"
    )
    (seed / "skills/triage/notes.md").write_text("updated")
    (seed / "README.md").write_text("not a skill")
    (seed / "quality.yaml").write_text("expected_headers: []\n")
    subprocess.run(["git", "add", "."], cwd=seed, check=True)
    subprocess.run(
        ["git", "-c", "user.email=test@example.org", "-c", "user.name=test", "commit", "-m", "changes"],
        cwd=seed,
        check=True,
    )
    subprocess.run(["git", "push", tmp_path / "server/handbook.git", "main"], cwd=seed, check=True)
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Installation and changed files").click()
        entry = page.url
        paths = ["README.md", "skills/release/SKILL.md", "skills/triage/notes.md"]
        select = page.get_by_label("Changed paths")
        assert "skills/triage/SKILL.md" not in select.locator("option").all_text_contents()
        sha = page.locator("input[name=sha]").input_value()
        for override, status in [
            ({"paths": "skills/triage/SKILL.md"}, 422),
            ({"check": "shell"}, 422),
            ({"quality_config": "/etc/passwd"}, 422),
            ({"sha": "0" * 40}, 409),
        ]:
            response = page.request.post(entry, form={"sha": sha, "paths": "README.md", "check": "quality", **override})
            assert response.status == status
        for check, selected in [
            ("schema", paths),
            ("lint-scripts", paths),
            ("schema", paths[:1]),
            ("quality", paths[1:2]),
        ]:
            page.goto(entry)
            page.get_by_label("Offline check").select_option(check, timeout=2000)
            select.select_option(selected)
            if check == "schema" and len(selected) > 1:
                page.get_by_label("Include redacted evaluator detail").check(timeout=2000)
            args = []
            if check == "quality":
                page.get_by_label("Minimum score").fill("99")
                page.get_by_label("Quality configuration").select_option("quality.yaml")
                args = ["--quality-config", "quality.yaml", "--min-score", "99"]
            page.get_by_role("button", name="Check selected paths").click()
            page.get_by_role("heading", name="Changed-file results").wait_for(timeout=20000)
            result = page.get_by_label("Check output").inner_text()
            cli = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    "from skillevaluator.cli import cli;cli()",
                    "precommit-run",
                    check,
                    *args,
                    "--",
                    *selected,
                ],
                cwd=seed,
                text=True,
                capture_output=True,
            )
            assert result == (cli.stdout.strip() or "No affected skills.")
            assert page.get_by_text("Gate exit code").locator("xpath=following-sibling::dd[1]").inner_text() == str(
                cli.returncode
            )
            page.get_by_text("Diagnostic detail", exact=True).click(timeout=2000)
            detail = page.locator("details[open]").inner_text()
            assert sha in detail and "changed-files-v1" in detail and private_remote[1] not in detail
            if check == "schema" and len(selected) > 1:
                assert "DEBUG" in detail and "2 affected skills" in detail
                assert "PASS  release  schema" in result and "FAIL  triage  schema" in result
            if check == "quality":
                assert "(min 99)" in result
