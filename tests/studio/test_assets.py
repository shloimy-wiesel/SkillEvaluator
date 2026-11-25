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


def test_check_selected_reference_cases(page, tmp_path, private_remote):
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Evaluation assets").click()
        page.get_by_label("Case IDs").fill("arithmetic\nmissing", timeout=2000)
        page.get_by_role("button", name="Check suite").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("passed", timeout=10000)
        url = page.get_by_role("link", name="Download JSON").get_attribute("href")
        result = page.request.get(url).json()
        assert result["cases"] == 2 and result["split"] == "assessment" and result["status"] == "valid"


def test_qualification_insufficient_coverage_never_spends(page, tmp_path, private_remote):
    import json

    seed = tmp_path / "seed"
    policy = {
        "schema": "skillevaluator.grader-qualification-policy/v1",
        "policy_id": "coverage",
        "required_metrics": ["overall"],
        "min_class_cases": {"pass": 2, "fail": 2},
        "min_category_cases": {},
        "max_rates": {"false_pass_rate": 0, "false_fail_rate": 0, "unjudgeable_rate": 0},
    }
    (seed / "skills/triage/policy.json").write_text(json.dumps(policy))
    subprocess.run(["git", "add", "."], cwd=seed, check=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=t@example.org", "commit", "-m", "policy"],
        cwd=seed,
        check=True,
    )
    subprocess.run(["git", "push", str(tmp_path / "server/handbook.git"), "main"], cwd=seed, check=True)
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Evaluation assets").click()
        page.get_by_label("Case IDs").fill("arithmetic")
        page.get_by_label("Qualification policy").select_option("policy.json")
        page.get_by_role("button", name="Run qualification").click(timeout=2000)
        playwright.expect(page.get_by_role("status")).to_contain_text("not_run", timeout=10000)
        url = page.get_by_role("link", name="Download JSON").get_attribute("href")
        report = page.request.get(url).json()
        assert report["attempts"] == [] and report["execution_status"] == "not_run"


def test_unknown_case_retains_engine_diagnostic_and_exit_code(page, tmp_path, private_remote):
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Evaluation assets").click()
        page.get_by_label("Case IDs").fill("not-a-case")
        page.get_by_role("button", name="Check suite").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("failed", timeout=5500)
        playwright.expect(page.get_by_text("Gate exit code").locator("xpath=following-sibling::dd[1]")).to_have_text(
            "2"
        )
        playwright.expect(page.get_by_role("main")).to_contain_text("unknown case IDs")


def test_run_shipped_verifier_retains_attempt_evidence(page, tmp_path, private_remote):
    import pytest
    from test_providers import save_profile

    pytest.importorskip("harbor")
    volume = tmp_path / "volume"
    with running(volume) as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        overview = page.url
        page.get_by_role("link", name="Provider settings").click()
        save_profile(
            page.get_by_role("region", name="Chat", exact=True),
            "https://127.0.0.1:1/v1",
            "fixture-model",
            "test-only-key",
        )
        page.goto(overview)
        page.get_by_role("link", name="Evaluation assets").click()
        # No trajectory: the shipped verifier does not need a model response for this case.
        page.get_by_label("Case IDs").fill("missing")
        page.get_by_label("Repeats").fill("1")
        page.get_by_role("button", name="Run qualification").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("passed", timeout=25000)
        report = page.request.get(page.get_by_role("link", name="Download JSON").get_attribute("href")).json()
        assert report["coverage"]["attempts"] == 1 and report["provenance"]["case_ids"] == ["missing"]
        from io import BytesIO
        from zipfile import ZipFile

        response = page.request.get(page.get_by_role("link", name="Download attempt evidence").get_attribute("href"))
        with ZipFile(BytesIO(response.body())) as archive:
            assert b"insufficient_evidence" in archive.read("missing/attempt-1/expected-vs-observed.json")
            assert not any(b"test-only-key" in archive.read(name) for name in archive.namelist())
