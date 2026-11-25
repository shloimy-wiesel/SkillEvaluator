import os

import pytest
from run_journey import rerun_saved_inputs
from test_workspace import connect, playwright, running

pytest_plugins = ("test_workspace",)

ALL_REPORTS = ["cli", "json", "html", "markdown", "sarif", "junit", "github"]


def test_alias_view_and_scoped_validation(page, private_remote, tmp_path):
    with running(tmp_path / "volume") as base:
        remote, token = private_remote
        project = page.request.post(
            base + "/api/v1/projects",
            data={"remote": remote, "username": "author", "token": token, "folder": "skills/triage"},
        ).json()
        path = f"/projects/{project['id']}/expert/tier1-quality-check"
        response = page.request.get(base + "/api/v1" + path)
        assert response.ok
        assert response.json()["sha"] == project["revision"]
        invalid = page.request.post(base + "/api/v1" + path, data={"sha": project["revision"], "workers": 2})
        assert invalid.status == 422 and invalid.json()["detail"]["message"]
        unknown = base + path.replace("tier1-quality-check", "unknown-check")
        assert page.request.get(unknown).status == 404
        assert page.request.get(unknown.replace("/projects/", "/api/v1/projects/")).status == 404
        page.goto(base + path + "?sha=invalid")
        playwright.expect(page.get_by_role("main").get_by_role("alert")).to_contain_text("full commit SHA")
        page.get_by_label("Commit SHA").fill(project["revision"])
        page.get_by_role("button", name="Load commit files").click()
        playwright.expect(page.get_by_label("Minimum score")).to_be_visible()


def assert_native_bundle(page, expected):
    import xml.etree.ElementTree as ET

    def download(label):
        link = page.get_by_role("link", name=f"Download native {label}", exact=True)
        return page.request.get(link.get_attribute("href"))

    assert expected.lower() in download("Markdown").text().lower()
    assert expected.lower() in download("HTML").text().lower()
    assert any(expected.lower() in r["validator"].lower() for r in download("JSON").json()["results"])
    assert download("SARIF").json()["version"] == "2.1.0"
    suites = ET.fromstring(download("JUnit").text()).findall("testsuite")
    assert any(expected.lower() in s.attrib["name"].lower() for s in suites)
    assert "::notice" in page.locator("body").text_content()


def publish(tmp_path, files):
    import subprocess

    seed = tmp_path / "seed"
    for path, text in files.items():
        dest = seed / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text)
    repo = tmp_path / "server/handbook.git"
    subprocess.run(["git", "add", "."], cwd=seed, check=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=t@example.org", "commit", "-m", "inputs"],
        cwd=seed,
        check=True,
    )
    subprocess.run(["git", "push", repo, "main"], cwd=seed, check=True)
    subprocess.run(["git", "update-server-info"], cwd=repo, check=True)


def test_parallel_catalog_reports_each_child_at_selected_commit(page, private_remote, tmp_path):
    publish(tmp_path, {"skills/second/SKILL.md": "# Missing frontmatter\n"})
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("heading", name="handbook").wait_for()
        page.goto(page.url + "/expert/validate")
        page.get_by_label("Target directory").select_option("skills", timeout=2000)
        page.get_by_label("Catalog workers").fill("2")
        page.get_by_label("Checks to run").select_option("schema")
        page.get_by_label("Tiers").select_option("1")
        sha = page.get_by_label("Commit SHA").input_value()
        for bad in ({"target": "/etc"}, {"target": "alias"}, {"workers": 5}, {"workers": 2, "tiers": "1,2"}):
            assert page.request.post(page.url, form={"sha": sha, "tiers": "1", **bad}).status == 422
        page.get_by_role("button", name="Queue check").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("failed", timeout=25000)
        summary = page.request.get(
            page.get_by_role("link", name="Download native Catalog summary").get_attribute("href")
        ).json()
        assert (summary["total"], summary["failed"]) == (2, 2)
        assert {s["name"] for s in summary["skills"]} == {"triage", "second"}
        for s in summary["skills"]:
            leaf = page.get_by_role("link", name=f"Download native JSON · {s['name']}", exact=True)
            href = leaf.get_attribute("href")
            artifact = page.request.get(href)
            assert "SKILL.md must have YAML frontmatter" in artifact.text()
            assert artifact.headers["content-type"] == "application/octet-stream"
            assert "attachment" in artifact.headers["content-disposition"]
            assert page.request.get(href + ".missing").status == 404
        assert "2 workers" in page.locator("body").text_content()


def test_live_catalog_retains_scoped_starters_and_leaf_gates(page, private_remote, tmp_path, monkeypatch):
    import subprocess

    monkeypatch.delenv("STUDIO_LIVE_ENABLED", raising=False)
    marker = tmp_path / "grader-ran-on-host"
    publish(
        tmp_path,
        {
            "skills/nested/triage/SKILL.md": "---\nname: triage\ndescription: Sort animal sightings by habitat.\n---\n# Second triage\n",
            "skills/nested/triage/evals/config.yml": "schema_version: 1\ngrading:\n  mode: custom_only\n",
            "skills/nested/triage/evals/grader.py": f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
        },
    )
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path / "seed", text=True).strip()
    publish(tmp_path, {"skills/later/SKILL.md": "# Later\n"})
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("heading", name="handbook").wait_for()
        page.goto(page.url + "/expert/validate")
        page.get_by_label("Commit SHA").fill(sha)
        page.get_by_role("button", name="Load commit files").click()
        page.get_by_label("Target directory").select_option("skills")
        page.get_by_label("Catalog workers").fill("2")
        page.get_by_label("Checks to run").select_option("unicode")
        page.get_by_label("Reports").select_option("json")
        page.get_by_role("button", name="Queue check").click()
        identities = {}
        for replay in (False, True):
            summary = page.get_by_role("link", name="Download native Catalog summary")
            playwright.expect(summary).to_be_visible(timeout=20000)
            members = page.request.get(summary.get_attribute("href")).json()["skills"]
            assert {s["name"] for s in members} == {"triage", "nested/triage"}
            for member in members:
                link = page.get_by_role("link", name=f"Download native JSON · {member['name']}", exact=True)
                report = page.request.get(link.get_attribute("href")).json()
                assert report["evaluated_source"]["commit"] == sha
                reason = "sandbox consent" if "/" in member["name"] else "runtime is disabled"
                assert reason in str(report) and "embedding setup is required" in str(report).lower()
                assert member["tier3"]["execution_status"] == "skipped"
                identity = report["results"][0]["publication_target"]["skill_digest"]
                if replay:
                    assert identity == identities[member["name"]]
                identities[member["name"]] = identity
                assert report["gating"]["tiers"]["3"]["blocking"] is False
                note = "Reused saved starter" if replay else "Generated and saved starter"
                playwright.expect(page.get_by_text(f"{member['name']}: {note}", exact=True)).to_be_visible()
            if not replay:
                rerun_saved_inputs(page)
        assert not marker.exists()


def test_harness_collection_uses_the_loaded_commit(page, private_remote, tmp_path):
    import subprocess

    publish(tmp_path, {"skills/second/SKILL.md": "# Second\n"})
    pinned = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path / "seed", text=True).strip()
    publish(tmp_path, {"skills/later/SKILL.md": "# Later\n"})
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("heading", name="handbook").wait_for()
        page.goto(page.url + "/expert/harness-check")
        page.get_by_label("Commit SHA").fill(pinned)
        page.get_by_role("button", name="Load commit files").click()
        page.get_by_label("Target directory").select_option("skills", timeout=2000)
        page.get_by_label("Managed harness profiles").select_option("agent-clis")
        page.get_by_label("Write harness JSON").check()
        page.get_by_label("Verbose output").check()
        page.get_by_role("button", name="Queue check").click()
        link = page.get_by_role("link", name="Download native JSON")
        playwright.expect(link).to_be_visible(timeout=20000)
        report = page.request.get(link.get_attribute("href")).json()["harness_compatibility"]
        assert {p.split("/")[-1] for p in report} == {"triage", "second"}
        assert all({r["harness"] for r in rows} == {"codex", "opencode", "claude-code"} for rows in report.values())
        assert "verified 0." in page.locator("body").text_content()


def test_root_rejects_unmanaged_runtime_inputs_before_queue(page, private_remote, tmp_path):
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("heading", name="handbook").wait_for()
        page.goto(page.url + "/expert/validate")
        sha = page.get_by_label("Commit SHA").input_value()
        for fields in (
            {"environment_kwarg": "volume=/etc"},
            {"kata_runtime": "/bin/sh"},
            {"include_skills": "/etc"},
            {"copy_repo": "true"},
            {"results_dir": "/var/tmp"},
            {"harness_profiles": "/tmp/profiles"},
            {"output_dir": "/tmp/reports"},
            {"external": "true", "profile": "registry"},
        ):
            response = page.request.post(page.url, form={"sha": sha, **fields})
            assert response.status == 422
        page.goto(page.url.split("/expert/")[0] + "/runs")
        playwright.expect(page.get_by_text("No runs yet.", exact=True)).to_be_visible()


@pytest.mark.parametrize("action", ["validate", "security-scan", "tier1-security-scan"])
def test_security_enrichment_requires_saved_provider(page, private_remote, tmp_path, action):
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("heading", name="handbook").wait_for()
        page.goto(page.url + "/expert/" + action)
        sha = page.get_by_label("Commit SHA").input_value()
        for key in ("llm", "llm_verify"):
            response = page.request.post(page.url, form={"sha": sha, key: "true"})
            assert response.status == 422 and "chat provider" in response.text()


@pytest.mark.parametrize("label", ["Quality check", "Tier 1: Quality check"])
def test_author_runs_only_quality_and_downloads_requested_evidence(page, private_remote, tmp_path, label):
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Evaluation runs").click()
        page.get_by_text("Expert checks and validation", exact=True).click(timeout=2000)
        page.get_by_role("link", name=label, exact=True).click(timeout=3000)
        page.get_by_label("Minimum score").fill("100")
        page.get_by_label("Reports").select_option("json")
        page.get_by_role("button", name="Queue check").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("failed", timeout=20000)
        report = page.request.get(page.get_by_role("link", name="Download native JSON").get_attribute("href")).json()
        assert len(report["results"]) == 1
        assert "quality" in report["results"][0]["validator"].lower()
        assert page.get_by_role("link", name="Download native HTML").count() == 0
        page.go_back()
        page.get_by_label("Reports").select_option(ALL_REPORTS)
        page.get_by_role("button", name="Queue check").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("failed", timeout=20000)
        assert_native_bundle(page, "quality")


@pytest.mark.parametrize("action", ["validate", "tier1", "tier1-validate"])
def test_workflow_runs_selected_checks_and_honors_report_omission(page, private_remote, tmp_path, action):
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("heading", name="handbook").wait_for()
        page.goto(page.url + "/expert/" + action)
        page.get_by_label("Checks to run").select_option("schema", timeout=2000)
        if action == "validate":
            page.get_by_label("Tiers").select_option("1")
        page.get_by_role("button", name="Queue check").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("failed", timeout=20000)
        report = page.request.get(page.get_by_role("link", name="Download native JSON").get_attribute("href")).json()
        assert "SKILL.md must have YAML frontmatter" in str(report["results"])
        assert page.get_by_role("link", name="Download native HTML").count() == 1
        page.go_back()
        page.get_by_label("Reports").select_option("cli")
        page.get_by_role("button", name="Queue check").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("failed", timeout=20000)
        assert page.get_by_role("link", name="Download native JSON").count() == 0
        assert page.get_by_role("link", name="Download native HTML").count() == 0
        assert page.get_by_role("link", name="Download native Benchmark").count() == int(action == "validate")
        if action == "validate":
            page.go_back()
            page.get_by_label("Reports").select_option([])
            page.get_by_label("Verbose output").check()
            page.get_by_role("button", name="Queue check").click()
            playwright.expect(page.get_by_role("status")).to_contain_text("failed", timeout=20000)
            assert page.get_by_role("link", name="Download native JSON").count() == 0
            assert page.get_by_role("link", name="Download native Benchmark").count() == 1


@pytest.mark.parametrize(
    "action,expected",
    [
        ("pii-scan", "PII"),
        ("security-scan", "Security"),
        ("lint-scripts", "Lint"),
        ("harness-check", "codex"),
        ("tier1-pii-scan", "PII"),
        ("tier1-security-scan", "Security"),
        ("tier1-lint-scripts", "Lint"),
    ],
)
def test_focused_command_keeps_own_scope(page, private_remote, tmp_path, action, expected):
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("heading", name="handbook").wait_for()
        page.goto(page.url + "/expert/" + action)
        if action == "harness-check":
            page.get_by_label("Harnesses", exact=True).select_option("codex", timeout=2000)
            page.get_by_label("Write harness JSON").check()
        else:
            page.get_by_label("Reports").select_option(ALL_REPORTS, timeout=2000)
        page.get_by_role("button", name="Queue check").click()
        link = page.get_by_role("link", name="Download native JSON")
        playwright.expect(link).to_be_visible(timeout=30000)
        report = page.request.get(link.get_attribute("href")).json()
        if action == "harness-check":
            assert expected in str(report["harness_compatibility"])
            assert "claude-code" not in str(report["harness_compatibility"])
        else:
            assert expected.lower() in report["results"][0]["validator"].lower()
            assert_native_bundle(page, expected)


@pytest.mark.parametrize("action", ["rubric-eval", "tier1-rubric-eval", "tier1", "tier1-validate"])
def test_rubric_uses_frozen_chat_role_on_rerun(page, private_remote, tmp_path, loopback_tls, monkeypatch, *, action):
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    from test_providers import save_profile

    from skillevaluator.constants import RUBRIC_CRITERIA

    pytest.importorskip("openai")
    seen = []
    workflow = action in ("tier1", "tier1-validate")
    if not workflow:
        publish(tmp_path, {"skills/second/SKILL.md": "# Second\n"})

    class Judge(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, body["model"], self.headers.get("Authorization")))
            scores = {"checks": [{"id": c["id"], "score": 8, "pass": True, "notes": "OK"} for c in RUBRIC_CRITERIA]}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "id": "fixture",
                        "object": "chat.completion",
                        "created": 1,
                        "model": body["model"],
                        "choices": [
                            {
                                "index": 0,
                                "finish_reason": "stop",
                                "message": {"role": "assistant", "content": json.dumps(scores)},
                            }
                        ],
                    }
                ).encode()
            )

    tls, ca = loopback_tls
    monkeypatch.setenv("SSL_CERT_FILE", os.path.relpath(ca))
    with ThreadingHTTPServer(("127.0.0.1", 0), Judge) as judge, running(tmp_path / "volume") as base:
        judge.socket = tls.wrap_socket(judge.socket, server_side=True)
        Thread(target=judge.serve_forever, daemon=True).start()
        try:
            page.goto(base)
            connect(page, *private_remote, skill="skills/triage")
            page.get_by_role("heading", name="handbook").wait_for()
            project = page.url
            page.goto(project + "/expert/" + action)
            sha = page.get_by_label("Commit SHA").input_value()
            denied = page.request.post(page.url, form={"sha": sha, **({"llm": "true"} if workflow else {})})
            assert denied.status == 422 and "chat provider" in denied.text()
            endpoint = f"https://127.0.0.1:{judge.server_port}/v1"
            page.goto(project + "/providers")
            chat = page.get_by_role("region", name="Chat", exact=True)
            save_profile(chat, endpoint, "frozen-model", "frozen-secret")
            page.goto(project + "/expert/" + action)
            if workflow:
                page.get_by_label("Checks to run").select_option("unicode")
                page.get_by_label("Model-backed checks").select_option("true")
            else:
                page.get_by_label("Target directory").select_option("skills")
            page.get_by_label("Minimum score").fill("90")
            page.get_by_label("Reports").select_option(ALL_REPORTS)
            page.get_by_role("button", name="Queue check").click()
            playwright.expect(page.get_by_role("status")).to_contain_text("failed", timeout=30000)
            run = page.url
            page.goto(project + "/providers")
            save_profile(chat, endpoint, "new-model", "new-secret")
            page.goto(run)
            rerun_saved_inputs(page)
            playwright.expect(page.get_by_role("status")).to_contain_text("failed", timeout=30000)
            assert seen == [("/v1/chat/completions", "frozen-model", "Bearer frozen-secret")] * (2 if workflow else 4)
            native = page.request.get(
                page.get_by_role("link", name="Download native JSON").get_attribute("href")
            ).json()
            assert any("rubric" in r["validator"].lower() and r["status"] == "failed" for r in native["results"])
            if not workflow:
                assert all(name in str(native["results"]) for name in ("triage", "second"))
                assert_native_bundle(page, "rubric")
            assert "frozen-secret" not in page.content()
            assert b"frozen-secret" not in (tmp_path / "volume/studio.sqlite3").read_bytes()
        finally:
            judge.shutdown()


@pytest.mark.parametrize("tiers", ["1,2", "1,2,3"])
def test_cross_tier_validation_routes_embeddings_separately(
    page, private_remote, tmp_path, loopback_tls, monkeypatch, *, tiers
):
    import json
    import subprocess
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    from test_providers import save_profile

    pytest.importorskip("openai")
    seed = tmp_path / "seed"
    (seed / "skills/triage/SKILL.md").write_text(
        "---\nname: triage\ndescription: Sort incoming requests by priority and type.\n---\n"
        "# Classification\n"
        + "Read the incoming request and select the correct queue. " * 18
        + "\n## Ordering\n"
        + "Rank severe requests first and archive resolved items. " * 18
    )
    repo = tmp_path / "server/handbook.git"
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=t@example.org", "commit", "-am", "sections"],
        cwd=seed,
        check=True,
    )
    subprocess.run(["git", "push", repo, "main"], cwd=seed, check=True)
    subprocess.run(["git", "update-server-info"], cwd=repo, check=True)
    seen = []
    catalog = tiers == "1,2,3"
    if catalog:
        manifest = (seed / "skills/triage/SKILL.md").read_text()
        publish(
            tmp_path,
            {
                "skills/triage/contact.md": "boss@company.com\n",
                "skills/other/contact.md": "boss@company.com\n",
                "skills/other/SKILL.md": manifest.replace("name: triage", "name: other"),
            },
        )

    class Gateway(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, body["model"], self.headers.get("Authorization")))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if "input" in body:
                n = len(body["input"])
                reply = {
                    "object": "list",
                    "data": [
                        {"index": i, "object": "embedding", "embedding": [float(i == j) for j in range(n)]}
                        for i in range(n)
                    ],
                }
            else:
                verdict = {"index": 0, "verdict": "false_positive", "confidence": "high", "rationale": "Example."}
                reply = {
                    "id": "fixture",
                    "object": "chat.completion",
                    "created": 1,
                    "model": body["model"],
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": json.dumps({"verdicts": [verdict]})},
                        }
                    ],
                }
            self.wfile.write(json.dumps(reply).encode())

    tls, ca = loopback_tls
    monkeypatch.setenv("SSL_CERT_FILE", str(ca))
    with ThreadingHTTPServer(("127.0.0.1", 0), Gateway) as gateway, running(tmp_path / "volume") as base:
        gateway.socket = tls.wrap_socket(gateway.socket, server_side=True)
        Thread(target=gateway.serve_forever, daemon=True).start()
        try:
            page.goto(base)
            connect(page, *private_remote, skill="skills/triage")
            page.get_by_role("heading", name="handbook").wait_for()
            project = page.url
            page.goto(project + "/providers")
            for role in ("Chat", "Embeddings"):
                save_profile(
                    page.get_by_role("region", name=role, exact=True),
                    f"https://127.0.0.1:{gateway.server_port}/{role}",
                    role + "-model",
                    role + "-key",
                )
            page.goto(project + "/expert/validate")
            page.get_by_label("Tiers", exact=False).select_option(tiers, timeout=2000)
            if catalog:
                page.get_by_label("Target directory").select_option("skills")
                page.get_by_label("Catalog workers").fill("2")
                page.get_by_label("Verify findings with chat provider").check()
                page.get_by_text("Tier 3 settings", exact=True).click()
                page.get_by_label("Prepare missing dataset").select_option("false")
            page.get_by_label("Checks to run").select_option("pii" if catalog else "unicode")
            page.get_by_label("Tier 2 gate").select_option("false")
            page.get_by_role("button", name="Queue check").click()
            report_link = page.get_by_role(
                "link", name="Download native JSON · triage" if catalog else "Download native JSON", exact=True
            )
            playwright.expect(report_link).to_be_visible(timeout=30000)
            report = page.request.get(report_link.get_attribute("href")).json()
            assert any(r["validator"] == "Context Deduplication" for r in report["results"])
            expected = {("/Embeddings/embeddings", "Embeddings-model", "Bearer Embeddings-key")}
            if catalog:
                expected.add(("/Chat/chat/completions", "Chat-model", "Bearer Chat-key"))
                assert set(seen) == expected
                run = page.url
                page.goto(project + "/providers")
                for role in ("Chat", "Embeddings"):
                    save_profile(
                        page.get_by_role("region", name=role, exact=True),
                        f"https://127.0.0.1:{gateway.server_port}/rotated",
                        "new-model",
                        "new-key",
                    )
                seen.clear()
                page.goto(run)
                rerun_saved_inputs(page)
                playwright.expect(report_link).to_be_visible(timeout=30000)
            assert set(seen) == expected
        finally:
            gateway.shutdown()


def test_configuration_file_is_selected_at_the_requested_commit(page, private_remote, tmp_path):
    import subprocess

    seed = tmp_path / "seed"
    path = "config/team-quality.yaml"
    (seed / "config").mkdir()
    (seed / path).write_text("expected_headers: []\n")
    subprocess.run(["git", "add", path], cwd=seed, check=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=t@example.org", "commit", "-m", "settings"],
        cwd=seed,
        check=True,
    )
    older = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=seed, text=True).strip()
    subprocess.run(["git", "rm", path], cwd=seed, check=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=t@example.org", "commit", "-m", "remove"],
        cwd=seed,
        check=True,
    )
    repo = tmp_path / "server/handbook.git"
    subprocess.run(["git", "push", repo, "main"], cwd=seed, check=True)
    subprocess.run(["git", "update-server-info"], cwd=repo, check=True)
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("heading", name="handbook").wait_for()
        page.goto(page.url + "/expert/quality-check")
        page.get_by_label("Commit SHA").fill(older)
        page.get_by_role("button", name="Load commit files").click(timeout=2000)
        page.get_by_label("Quality configuration").select_option(path)
        page.get_by_label("Reports").select_option("json")
        page.get_by_role("button", name="Queue check").click()
        link = page.get_by_role("link", name="Download native JSON")
        playwright.expect(link).to_be_visible(timeout=15000)
        assert "team-quality.yaml" in page.request.get(link.get_attribute("href")).text()


def test_pipeline_passes_only_scoped_parameters_to_installed_cli(tmp_path):
    from pydantic import ValidationError
    from studio.expert_options import ExpertOptions
    from studio.jobs import JobContext

    sha = "a" * 40
    skill = tmp_path / "triage"
    ctx = JobContext(tmp_path, skill, sha, None, None, "project", "run", tmp_path / "out")
    (tmp_path / "waivers.yaml").write_text("[]")
    opts = ExpertOptions(
        action="validate",
        tiers="1",
        checks=("schema", "pii"),
        skip=("pii",),
        llm=False,
        previous_version="1.2.3",
        profile="registry",
        pii_waivers="waivers.yaml",
        fail_fast=True,
        continue_on_failure=True,
        include_revision=True,
    )
    args = opts.arguments(ctx)
    assert args[:2] == ["validate", str(skill)]
    for flag, value in [
        ("--checks", "schema,pii"),
        ("--skip", "pii"),
        ("--tiers", "1"),
        ("--previous-version", "1.2.3"),
        ("--profile", "registry"),
        ("--pii-waivers", str(tmp_path / "waivers.yaml")),
        ("--evaluated-source-revision", sha),
    ]:
        assert args[args.index(flag) + 1] == value
    assert {"--no-llm", "--fail-fast", "--continue-on-failure"}.issubset(args)
    assert {"--report", "--min-score", "--llm-verify", "--block-on-dedup"}.isdisjoint(args)
    for params in [
        {"action": "lint-scripts", "min_score": 1},
        {"action": "pii-scan", "pii_waivers": "../secret.yaml"},
        {"action": "validate", "tiers": "1", "env_mode": "docker"},
        {"action": "tier1", "fail_fast": True},
    ]:
        with pytest.raises(ValidationError):
            ExpertOptions(**params)


def test_default_root_keyless_preserves_combined_evidence(page, private_remote, tmp_path, monkeypatch):
    monkeypatch.delenv("STUDIO_LIVE_ENABLED", raising=False)
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("heading", name="handbook").wait_for()
        page.goto(page.url + "/expert/validate")
        sha = page.get_by_label("Commit SHA").input_value()
        page.get_by_label("Checks to run").select_option("unicode")
        page.get_by_label("Verbose output").check()
        page.get_by_label("Reports").select_option("json")
        page.get_by_role("button", name="Queue check").click()
        link = page.get_by_role("link", name="Download native JSON")
        playwright.expect(link).to_be_visible(timeout=12000)
        report = page.request.get(link.get_attribute("href")).json()
        assert sha in str(report)
        assert "live runtime is disabled" in str(report).lower()
        assert "embedding setup is required" in str(report).lower()
        assert page.get_by_role("link", name="Download native Benchmark").count() == 1
        rerun_saved_inputs(page)
        playwright.expect(link).to_be_visible(timeout=20000)
        playwright.expect(page.get_by_text("Reused saved starter")).to_be_visible()


def test_root_blocks_on_missing_cases_without_autopilot(page, private_remote, tmp_path):
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("heading", name="handbook").wait_for()
        page.goto(page.url + "/expert/validate")
        page.get_by_label("Tiers", exact=False).select_option("1,3")
        page.get_by_label("Checks to run").select_option("unicode")
        page.get_by_text("Tier 3 settings", exact=True).click()
        page.get_by_label("Tier 3 blocking gate").select_option("true")
        page.get_by_label("Prepare missing dataset").select_option("false")
        page.get_by_role("button", name="Queue check").click()
        link = page.get_by_role("link", name="Download native JSON")
        playwright.expect(link).to_be_visible(timeout=20000)
        report = page.request.get(link.get_attribute("href")).json()
        assert report["gating"]["tiers"]["3"]["blocking"] is True
        assert report["tier3"]["verdict"] == "fail"
        playwright.expect(page.get_by_role("status")).to_contain_text("failed")


def test_root_inherited_custom_grader_cannot_bypass_sandbox_consent(page, private_remote, tmp_path, monkeypatch):
    from test_datasets import open_draft, seed_skill

    monkeypatch.delenv("STUDIO_LIVE_ENABLED", raising=False)
    seed_skill(
        tmp_path,
        {
            "evals/config.yml": "schema_version: 1\ngrading:\n  mode: custom_only\n",
            "evals/grader.py": "raise RuntimeError('must not execute here')",
            "evals/evals.json": '{"skill_name":"triage","evals":[{"id":"one","prompt":"Task","expected_output":"Answer"}]}',
        },
    )
    with running(tmp_path / "volume") as base:
        open_draft(page, base, private_remote)
        root = page.url.split("/datasets")[0] + "/expert/validate"
        for consent in (False, True):
            page.goto(root)
            page.get_by_label("Tiers", exact=False).select_option("1,3")
            page.get_by_label("Checks to run").select_option("unicode")
            page.get_by_text("Tier 3 settings", exact=True).click()
            if consent:
                page.get_by_label("Allow the repository grader in the sandbox").check()
            page.get_by_label("Reports").select_option("json")
            page.get_by_role("button", name="Queue check").click()
            link = page.get_by_role("link", name="Download native JSON")
            playwright.expect(link).to_be_visible(timeout=15000)
            report = page.request.get(link.get_attribute("href")).json()
            assert ("runtime is disabled" if consent else "sandbox consent") in str(report)


@pytest.mark.parametrize("partial", [True, False])
def test_root_folds_harbor_arm_evidence_with_pinned_options(tmp_path, monkeypatch, partial):
    import json
    import shutil
    from pathlib import Path

    from click.testing import CliRunner
    from studio.expert_options import ExpertOptions
    from studio.jobs import JobContext

    from skillevaluator.cli import cli
    from skillevaluator.embedded import sandbox_preflight
    from skillevaluator.evaluation import EvaluationService

    skill = tmp_path / "catalog/first/lookup-code"
    shutil.copytree(Path(__file__).resolve().parents[1] / "fixtures/skills/lookup-code", skill)
    shutil.copytree(skill, tmp_path / "catalog/second/lookup-code")
    out = tmp_path / "reports"
    ctx = JobContext(tmp_path, skill, "a" * 40, None, None, "project", "run", out)
    (tmp_path / "prices.json").write_text('{"fixture-model":{"input_per_mtok":1,"output_per_mtok":2}}')
    options = ExpertOptions(
        action="validate",
        target="catalog",
        tiers="1,3",
        checks=("unicode",),
        agents=("codex",),
        n_attempts=2,
        n_concurrent=3,
        max_agents=1,
        max_cases=2,
        pass_threshold=0.7,
        timeout_multiplier=1.5,
        stop_on_pass=False,
        skip_baseline=True,
        agent_runtime_preflight=False,
        tolerate_baseline_timeouts=False,
        max_agent_tokens=1024,
        max_judge_calls=0,
        max_cost_usd=1.25,
        price_file="prices.json",
        grading_mode="default",
        model="fallback-model",
        max_attempts_total=4,
        codex_model="fixture-model",
        env_mode="kata",
        kata_runtime="kata-qemu",
        harbor_keep_jobs=True,
        block_on_agent_eval=partial,
        include_revision=True,
    )
    observed = []

    def harbor(self, request, **kwargs):
        assert "kata_runtime=kata-qemu" in request.environment_kwarg
        assert (request.copy_repo, request.harbor_keep_jobs, request.include_skills) == (False, True, ())
        observed.append(
            (
                request.skill_workspace_mode,
                request.env_mode,
                request.agent_model,
                request.n_attempts,
                request.max_attempts_total,
                request.evaluated_source,
            )
        )
        assert (request.agents, request.model, request.n_concurrent, request.max_agents, request.max_cases) == (
            "codex",
            "fallback-model",
            3,
            1,
            2,
        )
        assert (
            request.pass_threshold,
            request.timeout_multiplier,
            request.stop_on_pass,
            request.skip_baseline,
            request.agent_runtime_preflight,
            request.tolerate_baseline_timeouts,
        ) == (0.7, 1.5, False, True, False, False)
        assert (
            request.max_agent_tokens,
            request.max_judge_calls,
            request.max_cost_usd,
            request.price_file,
            request.grading_mode,
        ) == (1024, 0, 1.25, tmp_path / "prices.json", "default")
        run = request.results_dir / skill.name / "20260101_120000"
        arm = run / "codex/with-skill"
        arm.mkdir(parents=True)
        (arm / "summary.json").write_text(
            json.dumps(
                {
                    "metrics": ["security"],
                    "scores": {"security": 0.75},
                    "execution_status": "succeeded",
                    "expected_attempts": 1,
                    "scored_attempts": 1,
                    "num_trials": 1,
                }
            )
        )
        (run / "run_config.json").write_text("{}")
        interrupted = partial and request.skill_path.parent.name == "second"
        payload = {
            "run_id": run.name,
            "run_dir": str(run),
            "agents": {"codex": {}},
            "execution_status": "failed" if interrupted else "succeeded",
            "execution_errors": ["second trial interrupted"] if interrupted else [],
        }
        (run / "result.json").write_text(json.dumps(payload))
        return payload

    monkeypatch.setattr(EvaluationService, "evaluate", harbor)
    token = sandbox_preflight.set(lambda _path: None)
    try:
        result = CliRunner().invoke(cli, [*options.arguments(ctx), "--results-dir", str(tmp_path / "runs")])
    finally:
        sandbox_preflight.reset(token)
    assert observed == [("isolated", "kata", ("codex=fixture-model",), 2, 4, {"commit": ctx.revision})] * 2
    assert result.exit_code == int(partial), result.output
    summary = json.loads((out / "catalog-summary.json").read_text())
    # Neither fixture supplies sufficient provenance for a blocking pass.
    assert summary["failed"] == (2 if partial else 0)
    for member in summary["skills"]:
        report = json.loads((out / member["name"] / member["json_report"]).read_text())
        assert report["evaluated_source"]["commit"] == ctx.revision
        assert report["tier3"]["agents"]["codex"]["conditions"]["with_skill"]["scored_attempts"] == 1
        assert (tmp_path / "runs" / member["name"] / "20260101_120000/result.json").is_file()
        assert ("second trial interrupted" in str(report["results"])) == (
            partial and member["name"].startswith("second")
        )
        assert member["tier3"] == {**report["publication"]["tier3"], "blocking": partial}
