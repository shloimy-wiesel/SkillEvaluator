import subprocess

import yaml

# ruff: noqa: F811
from test_workspace import before_push, connect, page, playwright, private_remote, running  # noqa: F401


def test_large_asset_preview_still_publishes_complete_starter(page, tmp_path, private_remote):
    from test_datasets import seed_skill

    workdir = "/" + "x" * 33000
    seed_skill(
        tmp_path, {"evals/config.yml": yaml.safe_dump({"schema_version": 1, "harbor": {"agent_workdir": workdir}})}
    )
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Evaluation assets").click()
        form = page.get_by_role("form", name="Custom grader")
        form.get_by_label("Update evaluation configuration").check()
        form.get_by_role("button", name="Preview").click()
        playwright.expect(page.get_by_label("Change preview")).to_contain_text("Diff omitted")
        page.get_by_role("button", name="Commit and push").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("Pushed")
        remote = tmp_path / "server/handbook.git"
        blob = subprocess.check_output(["git", "show", "main:skills/triage/evals/config.yml"], cwd=remote)
        config = yaml.safe_load(blob)
        assert config["harbor"]["agent_workdir"] == workdir
        assert config["grading"]["mode"] == "default_plus_custom"
        assert subprocess.check_output(
            ["git", "ls-tree", "main", "skills/triage/evals/grader.py"], cwd=remote
        ).startswith(b"100755")


def test_custom_grader_preview_and_push(page, tmp_path, private_remote):
    remote = tmp_path / "server/handbook.git"
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        with page.expect_response(
            lambda response: "/api/v1/projects/" in response.url and response.url.endswith("/assets"), timeout=5000
        ) as loaded:
            page.get_by_role("link", name="Evaluation assets").click(timeout=2000)
        assert loaded.value.json()["project"]["branch"] == "main"
        endpoint = loaded.value.url
        revision = loaded.value.json()["project"]["revision"]
        invalid = page.request.post(
            endpoint + "/qualify", data={"branch": "main", "revision": revision, "action": "check", "concurrency": 5}
        )
        assert invalid.status == 422 and invalid.json()["detail"]["code"] == "invalid_request"
        form = page.get_by_role("form", name="Custom grader")
        form.get_by_label("Language").select_option("shell")
        form.get_by_label("Grading mode").select_option("custom_only")
        form.get_by_role("button", name="Preview").click()
        playwright.expect(page.get_by_label("Change preview")).to_contain_text("evals/grader.sh")
        assert subprocess.check_output(["git", "rev-list", "--count", "main"], cwd=remote).strip() == b"1"
        page.get_by_role("button", name="Commit and push").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("Pushed")
        assert subprocess.check_output(
            ["git", "ls-tree", "main", "skills/triage/evals/grader.sh"], cwd=remote
        ).startswith(b"100755")
        assert b"custom_only" in subprocess.check_output(
            ["git", "show", "main:skills/triage/evals/config.yml"], cwd=remote
        )
        stale = page.request.post(
            endpoint + "/scaffold",
            data={
                "branch": "main",
                "revision": revision,
                "action": "save",
                "kind": "grader",
                "language": "python",
                "mode": "custom_only",
                "force": True,
            },
        )
        assert stale.status == 409 and stale.json()["detail"]["code"] == "stale_revision"

        # Overwrite replaces the alternate language; --no-config keeps the prior mode.
        form.get_by_label("Overwrite existing starter").check()
        form.get_by_label("Update evaluation configuration").uncheck()
        form.get_by_label("Grading mode").select_option("default_plus_custom")
        form.get_by_role("button", name="Preview").click()
        playwright.expect(page.get_by_label("Change preview")).to_contain_text("grader.sh (deleted)")
        page.get_by_role("button", name="Commit and push").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("Pushed")
        tree = subprocess.check_output(["git", "ls-tree", "-r", "main", "skills/triage/evals"], cwd=remote)
        assert b"grader.py" in tree and b"grader.sh" not in tree
        assert b"custom_only" in subprocess.check_output(
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

        form.get_by_label("Case ID").fill("audit-log")
        form.get_by_label("Overwrite existing starter").check()
        form.get_by_label("Language").select_option("shell")
        form.get_by_label("Grading mode").select_option("default")
        form.get_by_label("Update evaluation configuration").check()
        form.get_by_role("button", name="Preview").click()
        playwright.expect(page.get_by_label("Change preview")).to_contain_text("grader.py (deleted)")
        page.get_by_role("button", name="Commit and push").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("Pushed")
        config = subprocess.check_output(["git", "show", "main:skills/triage/evals/config.yml"], cwd=remote)
        assert b"task_source: native_harbor" in config and b"mode: default\n" in config


def test_check_selected_reference_cases(page, tmp_path, private_remote):
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Evaluation assets").click()
        page.get_by_label("Case IDs").fill("tuning-add\ntuning-wrong", timeout=2000)
        page.get_by_label("Split", exact=True).select_option("tuning")
        page.get_by_role("button", name="Check suite").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("passed", timeout=10000)
        url = page.get_by_role("link", name="Download JSON").get_attribute("href")
        result = page.request.get(url).json()
        assert result["cases"] == 2 and result["split"] == "tuning" and result["status"] == "valid"


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
        assets = page.url
        for gate in ("false pass", "false fail", "unjudgeable"):
            page.get_by_label("Qualification policy").select_option("policy.json")
            page.get_by_label(f"Maximum {gate} rate").fill("0")
            page.get_by_role("button", name="Check suite").click()
            playwright.expect(page.get_by_role("main")).to_contain_text("cannot combine", timeout=8000)
            page.goto(assets)
        for action, status in (("Check suite", "failed"), ("Run qualification", "not_run")):
            page.goto(assets)
            page.get_by_label("Case IDs").fill("arithmetic")
            page.get_by_label("Qualification policy").select_option("policy.json")
            page.get_by_role("button", name=action).click(timeout=2000)
            playwright.expect(page.get_by_role("status")).to_contain_text(status, timeout=10000)
            playwright.expect(
                page.get_by_role("heading", name="Policy coverage: insufficient_evidence")
            ).to_be_visible()
            for label, count in (("pass", 1), ("fail", 0)):
                reason = f"overall: expected {label} case coverage {count} below 2"
                playwright.expect(page.get_by_role("listitem").filter(has_text=reason)).to_be_visible()
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
        page.get_by_label("Concurrency").fill("2")
        page.get_by_label("Attempt timeout").fill("30")
        page.get_by_role("button", name="Run qualification").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("passed", timeout=25000)
        report = page.request.get(page.get_by_role("link", name="Download JSON").get_attribute("href")).json()
        assert report["coverage"]["attempts"] == 1 and report["provenance"]["case_ids"] == ["missing"]
        assert report["provenance"]["concurrency"] == 2 and report["provenance"]["timeout"] == 30
        from io import BytesIO
        from zipfile import ZipFile

        response = page.request.get(page.get_by_role("link", name="Download attempt evidence").get_attribute("href"))
        assert response.headers["content-type"] == "application/zip"
        assert 'filename="grader-validation.zip"' in response.headers["content-disposition"]
        assert page.request.get(response.url.rsplit("/", 1)[0] + "/unknown-run").status == 404
        with ZipFile(BytesIO(response.body())) as archive:
            assert b"insufficient_evidence" in archive.read("missing/attempt-1/expected-vs-observed.json")
            assert not any(b"test-only-key" in archive.read(name) for name in archive.namelist())


def publish_project_suite(tmp_path):
    import json
    import shutil

    from skillevaluator.tier3.grader_validation import REFERENCE_SUITE

    seed = tmp_path / "seed"
    suite = seed / "skills/triage/labels"
    shutil.copytree(REFERENCE_SUITE, suite)
    manifest = suite / "suite.json"
    data = json.loads(manifest.read_text())
    next(case for case in data["cases"] if case["id"] == "missing")["id"] = "project-missing"
    manifest.write_text(json.dumps(data))
    # A Python file beside the manifest is neither an import source nor a verifier.
    (suite / "json.py").write_text("raise RuntimeError('must not be imported')\n")
    subprocess.run(["git", "add", "."], cwd=seed, check=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=t@example.org", "commit", "-m", "suite"], cwd=seed, check=True
    )
    subprocess.run(["git", "push", str(tmp_path / "server/handbook.git"), "main"], cwd=seed, check=True)


def test_authored_suite_requires_consent_and_sandbox(page, tmp_path, private_remote, monkeypatch):
    monkeypatch.delenv("STUDIO_LIVE_ENABLED", raising=False)
    publish_project_suite(tmp_path)
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Evaluation assets").click()
        page.get_by_label("Suite", exact=True).select_option("labels/suite.json")
        page.get_by_role("button", name="Run qualification").click()
        form = page.get_by_role("form", name="Grader qualification")
        playwright.expect(form.get_by_role("alert")).to_contain_text("consent")
        playwright.expect(form.get_by_label("Suite", exact=True)).to_have_value("labels/suite.json")
        page.get_by_label("Allow this project suite").check()
        page.get_by_role("button", name="Run qualification").click()
        playwright.expect(form.get_by_role("alert")).to_contain_text("isolated Docker worker")
        playwright.expect(form.get_by_label("Suite", exact=True)).to_have_value("labels/suite.json")
        page.get_by_label("Case IDs").fill("arithmetic")
        page.get_by_role("button", name="Check suite").click()
        playwright.expect(page.get_by_role("main")).to_contain_text("Suite valid: 1 assessment cases.", timeout=8000)


def test_project_suite_returns_isolated_attempts(page, tmp_path, private_remote, monkeypatch):
    import os
    from io import BytesIO
    from zipfile import ZipFile

    import pytest

    if not (image := os.environ.get("STUDIO_TEST_GRADER_IMAGE")):
        pytest.skip("Set STUDIO_TEST_GRADER_IMAGE to a local trusted live evaluator image")
    monkeypatch.setenv("STUDIO_LIVE_ENABLED", "1")
    monkeypatch.setenv("STUDIO_GRADER_IMAGE", image)
    publish_project_suite(tmp_path)
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Evaluation assets").click()
        page.get_by_label("Suite", exact=True).select_option("labels/suite.json")
        page.get_by_label("Allow this project suite").check()
        page.get_by_label("Case IDs").fill("project-missing")
        page.get_by_label("Repeats").fill("1")
        page.get_by_role("button", name="Run qualification").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("passed", timeout=20000)
        report = page.request.get(page.get_by_role("link", name="Download JSON").get_attribute("href")).json()
        assert report["coverage"]["attempts"] == 1 and report["provenance"]["case_ids"] == ["project-missing"]
        response = page.request.get(page.get_by_role("link", name="Download attempt evidence").get_attribute("href"))
        with ZipFile(BytesIO(response.body())) as archive:
            assert b"insufficient_evidence" in archive.read("project-missing/attempt-1/expected-vs-observed.json")


def test_valid_preflight_does_not_pass_a_live_rate_gate(page, tmp_path, private_remote):
    import pytest
    from test_providers import open_settings, save_profile

    pytest.importorskip("harbor")
    with running(tmp_path / "volume") as base:
        settings = open_settings(page, base, private_remote)
        save_profile(page.get_by_role("region", name="Chat", exact=True), "https://127.0.0.1:1/v1", "fixture", "key")
        assets = base + settings.removesuffix("/providers") + "/assets"
        for action in ("Check suite", "Run qualification"):
            page.goto(assets)
            page.get_by_label("Case IDs").fill("arithmetic")
            page.get_by_label("Maximum unjudgeable rate").fill("0")
            page.get_by_label("Repeats").fill("1")
            page.get_by_label("Attempt timeout").fill("0.001")
            page.get_by_role("button", name=action).click()
            check = action == "Check suite"
            playwright.expect(page.get_by_role("status")).to_contain_text(
                "passed" if check else "failed", timeout=12000
            )
            report = page.request.get(page.get_by_role("link", name="Download JSON").get_attribute("href")).json()
            if check:
                assert report["status"] == "valid" and "attempts" not in report
            else:
                playwright.expect(page.get_by_text("Gates exceeded: unjudgeable rate")).to_be_visible()
                assert report["metrics"]["overall"]["unjudgeable_rate"]["rate"] == 1
                assert report["threshold_failures"] == ["unjudgeable_rate"]


def test_authenticated_judge_thresholds_use_measured_rates(page, tmp_path, private_remote, loopback_tls, monkeypatch):
    import json
    import os
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    import pytest
    from test_providers import open_settings, save_profile

    pytest.importorskip("harbor")
    accepted = True
    auth = []

    class Judge(BaseHTTPRequestHandler):
        def do_POST(self):
            prompt = json.dumps(json.loads(self.rfile.read(int(self.headers["content-length"])))["messages"])
            auth.append(self.headers.get("Authorization"))
            if "ACTION_CORRECT" in prompt:
                reply = {
                    "criteria": dict.fromkeys(
                        ["ACTION_CORRECT", "FACTUALLY_ACCURATE", "TASK_ADDRESSED", "ACTIONABLE", "FORMAT_FOLLOWED"],
                        accepted,
                    ),
                    "reason": "fixture",
                }
            elif "achieved" in prompt:
                reply = {"user_goal": "compute", "end_state": "14", "achieved": accepted, "reason": "fixture"}
            else:
                reply = {
                    "results": [{"step": i, "passed": accepted, "reason": "fixture"} for i in (1, 2)],
                    "summary": "fixture",
                }
            body = json.dumps({"choices": [{"message": {"content": json.dumps(reply)}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    tls, ca = loopback_tls
    # The qualifier starts in a different, private working directory.
    monkeypatch.setenv("SSL_CERT_FILE", os.path.relpath(ca))
    with ThreadingHTTPServer(("127.0.0.1", 0), Judge) as judge, running(tmp_path / "volume") as base:
        judge.socket = tls.wrap_socket(judge.socket, server_side=True)
        thread = Thread(target=judge.serve_forever)
        thread.start()
        try:
            settings = open_settings(page, base, private_remote)
            save_profile(
                page.get_by_role("region", name="Chat", exact=True),
                f"https://127.0.0.1:{judge.server_port}/v1",
                "judge",
                "threshold-secret",
            )
            for gate, answer, split, case in (
                ("false pass", True, "tuning", "tuning-wrong"),
                ("false fail", False, "all", "arithmetic"),
            ):
                accepted = answer
                page.goto(base + settings.removesuffix("/providers") + "/assets")
                page.get_by_label("Split", exact=True).select_option(split)
                page.get_by_label("Case IDs").fill(case)
                page.get_by_label("Repeats").fill("1")
                page.get_by_label("Attempt timeout").fill("8")
                page.get_by_label(f"Maximum {gate} rate").fill("0")
                page.get_by_role("button", name="Run qualification").click()
                playwright.expect(page.get_by_role("status")).to_contain_text("failed", timeout=25000)
                report = page.request.get(page.get_by_role("link", name="Download JSON").get_attribute("href")).json()
                name = gate.replace(" ", "_") + "_rate"
                metrics = report["metrics"] or report["by_split"]["assessment"]
                assert any(metric[name]["rate"] == 1 for metric in metrics.values())
                assert report["threshold_failures"] == [name]
            assert set(auth) == {"Bearer threshold-secret"}
        finally:
            judge.shutdown()
            thread.join()
