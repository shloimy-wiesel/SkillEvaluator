import subprocess

import yaml

# ruff: noqa: F811 -- shared browser and authenticated Git fixtures
from test_workspace import before_push, connect, page, playwright, private_remote, running  # noqa: F401

SCAN = ".github/workflows/skill-checks.yml"


def test_review_checks_then_publish(page, private_remote, tmp_path):
    remote = tmp_path / "server/handbook.git"
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Repository CI").click(timeout=1500)
        page.get_by_role("button", name="Check status").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("Workflow absent on remote branch main")
        page.get_by_label("Minimum score").fill("83")
        page.get_by_label("Scan scope").select_option("all")
        page.get_by_label("Release channel").select_option("stable")
        page.get_by_role("button", name="Review setup").click()
        review = page.get_by_label("Generated workflow").inner_text()
        assert subprocess.run(["git", "cat-file", "-e", "main:" + SCAN], cwd=remote).returncode
        page.get_by_role("button", name="Publish reviewed workflow").click()
        saved = subprocess.check_output(["git", "show", "main:" + SCAN], cwd=remote).decode()
        assert saved == review
        job = yaml.safe_load(saved)["jobs"]["skills"]
        assert job["uses"].endswith("@stable") or "stable" in job["uses"]
        assert job["with"] == {"paths": "skills/triage", "min-score": 83, "scan-mode": "all", "llm": False}
        page.get_by_role("button", name="Check status").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("Workflow present on remote branch main")
        playwright.expect(page.get_by_role("link", name="Inspect scan runs on Git host")).to_have_attribute(
            "href", private_remote[0].removesuffix(".git") + "/actions/workflows/skill-checks.yml"
        )


def test_review_demo_then_publish_separate_branch(page, private_remote, tmp_path):
    remote = tmp_path / "server/handbook.git"
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Repository CI").click()
        page.get_by_role("button", name="Review demo").click(timeout=1500)
        playwright.expect(page.get_by_role("alert")).to_contain_text("Set up checks")
        page.get_by_role("button", name="Review setup").click()
        preview = yaml.safe_load(page.get_by_label("Generated workflow").inner_text())["jobs"]["skills"]
        assert preview["with"]["min-score"] == 70 and preview["with"]["scan-mode"] == "auto"
        assert "@stable" not in preview["uses"] and "@sha256:" in preview["with"]["image"]
        page.get_by_role("button", name="Publish reviewed workflow").click()
        page.get_by_role("button", name="Review demo").click()
        playwright.expect(page.get_by_label("Demo change")).to_contain_text("<!-- SkillEvaluator onboarding demo:")
        page.get_by_role("button", name="Publish demo branch").click()
        playwright.expect(page.get_by_role("link", name="Open pull request for review")).to_have_attribute(
            "href", private_remote[0].removesuffix(".git") + "/compare/main...ci/skillevaluator-test?expand=1"
        )
        original = subprocess.check_output(["git", "show", "main:skills/triage/SKILL.md"], cwd=remote)
        assert original == b"# Triage\n"
        assert (
            subprocess.check_output(["git", "show", "ci/skillevaluator-test:skills/triage/SKILL.md"], cwd=remote)
            == original + b"\n<!-- SkillEvaluator onboarding demo: exercise automatic PR feedback. -->\n"
        )


def test_changed_review_and_untrusted_workflow_fields_are_rejected(page, private_remote, tmp_path):
    remote = tmp_path / "server/handbook.git"
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Repository CI").click()
        page.get_by_role("button", name="Review setup").click()
        page.get_by_label("Minimum score").fill("12")
        page.get_by_role("button", name="Publish reviewed workflow").click()
        playwright.expect(page.get_by_role("alert")).to_contain_text("Review the generated workflow")
        page.get_by_role("button", name="Review setup").click()
        status = page.get_by_label("Minimum score").evaluate("""async input => {
          const data = new FormData(input.form);
          data.set('action', 'publish'); data.set('workflow', 'unreviewed workflow');
          data.set('repo', '/other/project');
          return (await fetch(input.form.getAttribute('action'), {method:'POST', body:data})).status;
        }""")
        assert status == 422
        assert subprocess.run(["git", "cat-file", "-e", "main:" + SCAN], cwd=remote).returncode
