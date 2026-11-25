import json
import os
from pathlib import Path

import pytest
from run_journey import rerun_saved_inputs
from test_providers import open_settings, save_profile
from test_workspace import playwright, running

pytest_plugins = ("test_workspace", "test_providers")


@pytest.fixture
def retained(page, private_remote, tmp_path, monkeypatch, request):
    from studio import live_job

    def engine(args, cwd, env):
        root = Path(args[args.index("--results-dir") + 1]) / "triage/20260101_120000"
        for agent in ("codex", "opencode"):
            arm = root / agent / "with-skill"
            trial = arm / "trials/triage-1"
            trial.mkdir(parents=True)
            (arm / "summary.json").write_text(
                json.dumps(
                    {
                        "metrics": ["security"],
                        "scores": {"security": 0.75},
                        "model": "private-model",
                        "execution_status": "succeeded",
                        "expected_attempts": 1,
                        "scored_attempts": 1,
                        "num_trials": 1,
                    }
                )
            )
            (trial / "reward.json").write_text(
                json.dumps(
                    {"case_id": "triage", "trial_id": "triage-1", "attempt_index": 0, "scores": {"security": 0.75}}
                )
            )
            (trial / "trajectory.json").write_text(
                '{"steps":[{"message":"Inspect failed check","api_key":"private-value"}]}'
            )
        # A measured matched pair for codex, but no baseline evidence for opencode.
        baseline = root / "codex/without-skill"
        (baseline / "trials/triage-1").mkdir(parents=True)
        summary = json.loads((root / "codex/with-skill/summary.json").read_text())
        summary["scores"]["security"] = 0.25
        (baseline / "summary.json").write_text(json.dumps(summary))
        (baseline / "trials/triage-1/reward.json").write_text(
            json.dumps({"case_id": "triage", "trial_id": "triage-1", "attempt_index": 0, "scores": {"security": 0.25}})
        )
        (root / "result.json").write_text(
            json.dumps(
                {
                    "run_id": root.name,
                    "skill_name": "triage",
                    "execution_status": "succeeded",
                    "verdict": "neutral",
                    "tier3_feedback": {"schema_version": "1.0", "recommendations": ["Keep the retry case."]},
                }
            )
        )
        (root / "run_config.json").write_text(
            json.dumps(
                {
                    "run_id": root.name,
                    "agents": {"codex": {"agent": "codex"}, "opencode": {"agent": "opencode"}},
                }
            )
        )
        (root / "report.html").write_text("<h1>Native findings</h1><script>alert(7)</script>")
        if "--harbor-keep-jobs" in args:
            job = root / "_harbor-jobs/codex-with-skill/triage-1/agent"
            job.mkdir(parents=True)
            (job / "trajectory.json").write_text(
                json.dumps(
                    {
                        "schema_version": "ATIF-v1.4",
                        "session_id": "abc",
                        "steps": [
                            {"step_id": 1, "source": "user", "message": "Original task"},
                            {"step_id": 2, "source": "agent", "message": "Read triage guide"},
                        ],
                    }
                )
            )
        return 0

    monkeypatch.setattr(live_job, "invoke_engine", engine)
    volume = tmp_path / "volume"
    with running(volume) as base:
        settings = open_settings(page, base, private_remote)
        save_profile(
            page.get_by_role("region", name="Chat", exact=True), "https://chat.example/v1", "test", "chat-secret"
        )
        page.goto(base + settings.removesuffix("/providers") + "/live")
        page.get_by_label("Workflow").select_option("direct")
        if getattr(request, "param", None) == "keep-jobs":
            page.get_by_text("Trial settings and budgets").click()
            page.get_by_label("Retain Harbor jobs").check(timeout=2000)
        page.get_by_role("button", name="Queue live evaluation").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("neutral")
        yield base, settings.removesuffix("/providers"), volume


def test_dashboard_queries_retained_agents(page, retained):
    base, project, _ = retained
    page.goto(base + project)
    page.get_by_role("link", name="Results dashboard").click(timeout=2000)
    playwright.expect(page.get_by_role("table")).to_contain_text("codex")
    page.get_by_label("Harness", exact=True).select_option("opencode")
    page.get_by_label("Display").select_option("comparison")
    page.get_by_role("button", name="Apply filters").click()
    table = page.get_by_role("table")
    playwright.expect(table).to_contain_text("missing condition")
    playwright.expect(table).to_contain_text("opencode")
    playwright.expect(table).not_to_contain_text("codex")
    page.get_by_label("Evidence source").select_option("native", timeout=2000)
    page.get_by_label("Metrics").select_option("tokens")
    page.get_by_role("button", name="Apply filters").click()
    playwright.expect(table).to_contain_text("private-model")
    playwright.expect(table).to_contain_text("total tokens delta")


def test_compare_agents_from_selected_native_summaries(page, retained):
    page.get_by_role("link", name="Compare agents", exact=True).click(timeout=2000)
    matrix = page.get_by_label("Agent score comparison")
    playwright.expect(matrix).to_contain_text("security", ignore_case=True, timeout=2000)
    playwright.expect(matrix).to_contain_text("0.75")
    playwright.expect(matrix).to_contain_text("+0.50")
    playwright.expect(matrix).to_contain_text("codex")
    playwright.expect(matrix).to_contain_text("opencode")


def test_view_rebuilds_missing_native_html_without_mutating_run(page, retained):
    _, _, volume = retained
    report = next((volume / "artifacts").rglob("report.html"))
    report.unlink()
    page.get_by_role("link", name="Review artifacts and feedback").click()
    page.get_by_role("link", name="View report", exact=True).click(timeout=2000)
    preview = page.get_by_label("Artifact preview")
    playwright.expect(preview).to_contain_text("triage")
    playwright.expect(preview).to_contain_text("codex")
    assert not report.exists()


def test_select_report_sources_without_pairing_across_runs(page, retained):
    base, project, _ = retained
    first = page.url.rsplit("/", 1)[-1]
    rerun_saved_inputs(page)
    playwright.expect(page.get_by_role("status")).to_contain_text("neutral")
    second = page.url.rsplit("/", 1)[-1]
    page.goto(base + project + "/results")
    runs = page.get_by_label("Retained runs")
    runs.select_option([first, second])
    page.get_by_label("Display").select_option("comparison")
    page.get_by_role("button", name="Apply filters").click()
    table = page.get_by_role("table")
    playwright.expect(table).to_contain_text(first)
    playwright.expect(table).to_contain_text(second)
    playwright.expect(table).not_to_contain_text("ambiguous duplicate conditions")
    runs.select_option([first])
    page.get_by_role("button", name="Apply filters").click()
    playwright.expect(table).to_contain_text(first)
    playwright.expect(table).not_to_contain_text(second)


def test_inspect_scoped_report_and_harbor_trajectory(page, retained):
    from urllib.parse import urlsplit

    _, _, volume = retained
    native = next((volume / "artifacts").glob("*/*/tier3/triage/*"))
    (native / "linked").symlink_to(volume)
    (native / "fake").mkdir()
    (native / "fake/summary.json").symlink_to(volume / "credential.key")
    (native / "fake/reward.json").hardlink_to(volume / "credential.key")
    page.get_by_role("link", name="Review artifacts and feedback").click(timeout=2000)
    view = page.request.get(page.url.replace("/projects/", "/api/v1/projects/")).json()
    assert set(view["run"]) == {"id", "folder", "sha"}
    assert "private-value" not in json.dumps(view)
    assert "fake/" not in page.content() and "/linked/" not in page.content()
    page.get_by_role("link", name="report.html", exact=False).click()
    playwright.expect(page.get_by_label("Artifact preview")).to_contain_text("Native findings")
    assert "<script>alert(7)</script>" not in page.content()
    page.get_by_label("File filter").fill("opencode")
    page.get_by_role("button", name="Filter files").click()
    page.get_by_role("link", name="trajectory.json", exact=False).click()
    preview = page.get_by_label("Artifact preview")
    playwright.expect(preview).to_contain_text("Inspect failed check")
    assert "private-value" not in preview.inner_text()
    href = page.url
    path = urlsplit(href).path
    assert page.request.get(href.replace(path.split("/")[2], "other-project")).status == 404
    assert page.request.get(href.split("?")[0] + "?file=../../credential.key").status == 404
    with page.expect_download() as download:
        page.get_by_role("link", name="Download redacted text").click(timeout=2000)
    assert download.value.path().read_text() == preview.inner_text()
    assert download.value.suggested_filename == "trajectory.json.txt"
    assert page.request.get(href.split("?")[0] + "?download=true&file=../../credential.key").status == 404


def test_contextual_feedback_survives_reopen(page, retained, loopback_tls, monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from urllib.parse import urlsplit

    calls = []

    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(
                (self.headers["Authorization"], json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            )
            answer = {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Review triage-1. chat-secret"},
                        "finish_reason": "stop",
                    }
                ]
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(answer).encode())

    base, project, volume = retained
    run_url = page.url
    tls, ca = loopback_tls
    monkeypatch.setenv("SSL_CERT_FILE", os.path.relpath(ca))
    with ThreadingHTTPServer(("127.0.0.1", 0), Provider) as server:
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        Thread(target=server.serve_forever, daemon=True).start()
        try:
            page.goto(base + project + "/providers")
            save_profile(
                page.get_by_role("region", name="Chat", exact=True),
                f"https://127.0.0.1:{server.server_port}/v1",
                "private-chat",
                "chat-secret",
            )
            page.goto(run_url)
            page.get_by_role("link", name="Review artifacts and feedback").click()
            path = urlsplit(page.url).path
            page.get_by_label("Question").fill("Explain coverage chat-secret", timeout=2000)
            page.get_by_role("button", name="Ask about this run").click()
            playwright.expect(page.get_by_label("Conversation")).to_contain_text("Review triage-1.")
            with running(volume) as reopened:
                page.goto(reopened + path)
                page.get_by_label("Question").fill("And opencode?")
                page.get_by_role("button", name="Ask about this run").click()
                playwright.expect(
                    page.get_by_label("Conversation").get_by_text("Review triage-1.", exact=False)
                ).to_have_count(2)
                assert "chat-secret" not in page.content()
        finally:
            server.shutdown()
    auth, body = calls[-1]
    assert auth == "Bearer chat-secret" and body["model"] == "private-chat"
    assert [m["role"] for m in body["messages"]] == ["system", "user", "assistant", "user"]
    assert "opencode" in body["messages"][0]["content"]
    assert "Keep the retry case." in body["messages"][0]["content"]
    assert "chat-secret" not in json.dumps(body)


@pytest.mark.parametrize("retained", ["keep-jobs"], indirect=True)
def test_filter_retained_harbor_job_steps(page, retained):
    page.get_by_role("link", name="Review artifacts and feedback").click()
    page.get_by_role("link", name="_harbor-jobs", exact=False).click()
    page.get_by_label("Step source").select_option("agent")
    page.get_by_role("button", name="Show steps").click()
    steps = page.get_by_label("Trajectory steps")
    playwright.expect(steps).to_contain_text("Read triage guide")
    playwright.expect(steps).not_to_contain_text("Original task")


def test_dashboard_upload_is_project_scoped_bounded_json(page, retained, private_remote):
    base, project, _ = retained
    page.goto(base + project + "/results")
    doc = {"agents": {"uploaded-harness": {"execution_status": "succeeded", "model": "chat-secret"}}}
    page.get_by_label("Dashboard report JSON").set_input_files(
        {"name": "evidence.json", "mimeType": "application/json", "buffer": json.dumps(doc).encode()}, timeout=1500
    )
    page.get_by_role("button", name="Import report").click()
    table = page.get_by_role("table")
    playwright.expect(table).to_contain_text("uploaded-harness")
    playwright.expect(table).not_to_contain_text("chat-secret")
    page.reload()
    playwright.expect(table).to_contain_text("uploaded-harness")
    from urllib.parse import parse_qs, urlsplit

    source = parse_qs(urlsplit(page.url).query)["run"][0]
    uploaded_url = page.url
    other = open_settings(page, base, private_remote).removesuffix("/providers")
    assert page.request.get(base + other + "/results?run=" + source).status == 404
    denied = page.request.post(base + "/api/v1" + other + "/results/uploads/" + source + "/remove")
    assert denied.status == 404 and denied.json()["detail"]["message"] == "Unknown imported report"
    url = base + "/api/v1" + project + "/results/uploads"
    for data, status in [
        (b'{"path":"/etc/passwd"}', 422),
        (b"[" * 1500, 422),
        (b"x" * (2**20 + 1), 413),
        (b'{"agents":{},"agents":{"x":{"model":"x"}}}', 422),
    ]:
        assert page.request.post(url, data=data, headers={"Content-Type": "application/json"}).status == status
    expanded = {
        "dashboard_metadata": {"harness_features": "f" * 16000},
        "agents": {str(i): {"model": "m"} for i in range(200)},
    }
    assert page.request.post(url, data=expanded).status == 422
    assert page.request.post(base + "/projects/missing/results/uploads", data=doc).status == 404
    page.goto(uploaded_url)
    page.get_by_role("button", name="Remove " + source).click()
    playwright.expect(table).to_contain_text("codex")
    assert page.request.get(base + "/api/v1" + project + "/results?run=" + source).status == 404


def test_latest_scoreable_summary_per_agent(page, retained):
    import shutil

    _, _, volume = retained
    rerun_saved_inputs(page)
    playwright.expect(page.get_by_role("status")).to_contain_text("neutral")
    latest = page.url.rsplit("/", 1)[-1]
    native = next((volume / "artifacts").glob(f"*/{latest}/tier3/triage/*/result.json")).parent
    shutil.rmtree(native / "opencode")
    summary = native / "codex/with-skill/summary.json"
    doc = json.loads(summary.read_text())
    doc["scores"]["security"] = 0.91
    summary.write_text(json.dumps(doc))
    page.get_by_role("link", name="Review artifacts and feedback").click()
    page.get_by_role("link", name="Latest per agent").click(timeout=1500)
    matrix = page.get_by_label("Agent score comparison")
    playwright.expect(matrix).to_contain_text("opencode")
    playwright.expect(matrix).to_contain_text("0.75")
    playwright.expect(matrix).to_contain_text("0.91")


@pytest.mark.parametrize("retained", ["keep-jobs"], indirect=True)
def test_harbor_job_navigation_opens_only_authorized_text(page, retained):
    _, _, volume = retained
    job = next((volume / "artifacts").rglob("_harbor-jobs")) / "codex-with-skill/triage-1"
    verifier = job / "verifier"
    verifier.mkdir()
    (verifier / "test-stdout.txt").write_text("Verifier ran case 42 chat-secret <script>")
    (verifier / "test-stderr.txt").symlink_to(volume / "credential.key")
    (job / "secret.txt").write_text("private")
    page.get_by_role("link", name="Review artifacts and feedback").click()
    page.get_by_role("link", name="Browse Harbor jobs").click(timeout=1500)
    page.get_by_label("Harbor job", exact=True).select_option("codex-with-skill", timeout=1500)
    page.get_by_role("button", name="Open job").click()
    page.get_by_role("link", name="test-stdout.txt", exact=False).click()
    preview = page.get_by_label("Artifact preview")
    playwright.expect(preview).to_contain_text("Verifier ran case 42")
    playwright.expect(preview).not_to_contain_text("chat-secret")
    assert "test-stderr.txt" not in page.content() and "secret.txt" not in page.content()


def test_report_sections_can_be_navigated_without_running_html(page, retained):
    _, _, volume = retained
    report = next((volume / "artifacts").rglob("report.html"))
    report.write_text(
        "<h1>Overview</h1><p>Pass</p><h2>Failures</h2><p>Review case 19 chat-secret</p>"
        '<script>window.badReport=1</script><img src="https://bad.invalid/pixel">'
    )
    page.get_by_role("link", name="Review artifacts and feedback").click()
    page.get_by_role("link", name="View report", exact=True).click()
    page.get_by_text("Failures", exact=True).click(timeout=1500)
    assert page.get_by_text("Review case 19 <redacted>", exact=True).is_visible()
    assert "bad.invalid" not in page.content() and "window.badReport" not in page.content()


def test_bedrock_feedback_requires_authorized_runtime_identity(page, retained, monkeypatch):
    import subprocess

    base, project, _ = retained
    page.get_by_role("link", name="Review artifacts and feedback").click()
    url = page.url
    page.goto(base + project + "/providers")
    chat = page.get_by_role("region", name="Chat", exact=True)
    chat.get_by_label("Provider", exact=True).select_option("bedrock")
    chat.get_by_label("Base URL").fill("")
    chat.get_by_label("Model").fill("anthropic.claude-3-haiku-20240307-v1:0")
    chat.get_by_role("button", name="Save settings").click()
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "feedback-identity")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fixture-secret")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://ignore.invalid")
    run = subprocess.run

    def fixture_runtime(args, **kwargs):
        if len(args) == 3 and str(args[-1]).endswith("/feedback_worker.py"):
            # Exercise the real isolated worker + canonical client up to the SDK transport.
            bootstrap = """import os, runpy, sys, types
from types import SimpleNamespace as NS
def completion(**kwargs):
    assert kwargs['model'] == 'bedrock/anthropic.claude-3-haiku-20240307-v1:0'
    assert kwargs['aws_region_name'] == 'eu-west-1'
    assert os.environ['AWS_ACCESS_KEY_ID'] == 'feedback-identity'
    assert 'AWS_ENDPOINT_URL' not in os.environ and 'OPENAI_API_KEY' not in os.environ
    assert 'Keep the retry case.' in kwargs['messages'][0]['content']
    return NS(choices=[NS(message=NS(content='AWS fixture answer'),finish_reason='stop')])
sys.modules['litellm'] = NS(completion=completion)
runpy.run_path(sys.argv[1], run_name='__main__')"""
            args = [*args[:2], "-c", bootstrap, args[-1]]
        return run(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fixture_runtime)
    resp = page.request.post(url + "/feedback", form={"question": "Why?"})
    assert resp.status == 403
    monkeypatch.setenv("STUDIO_FEEDBACK_BEDROCK_PROJECTS", project.rsplit("/", 1)[-1])
    page.goto(url)
    page.get_by_label("Question").fill("Why?")
    page.get_by_role("button", name="Ask about this run").click()
    playwright.expect(page.get_by_label("Conversation")).to_contain_text("AWS fixture answer")


def test_missing_saved_report_uses_retained_measurements(page, retained):
    import sqlite3
    from contextlib import closing

    base, project, volume = retained
    run = page.url.rsplit("/", 1)[-1]
    with closing(sqlite3.connect(volume / "studio.sqlite3")) as db, db:
        db.execute("UPDATE runs SET report=NULL WHERE id=?", (run,))
    next((volume / "artifacts").rglob("report.html")).unlink()
    page.goto(base + project + "/results?run=" + run)
    playwright.expect(page.get_by_role("table")).to_contain_text("private-model", timeout=1500)
    page.get_by_role("link", name=run).first.click()
    page.get_by_role("link", name="Review artifacts and feedback").click()
    page.get_by_role("link", name="View report", exact=True).click()
    playwright.expect(page.get_by_label("Artifact preview")).to_contain_text("codex")
    assert not list((volume / "artifacts").rglob("report.html"))


def test_download_filtered_dashboard_csv(page, retained):
    import csv
    import io

    base, project, _ = retained
    page.goto(base + project + "/results")
    page.get_by_label("Harness", exact=True).select_option("codex")
    page.get_by_label("Display").select_option("comparison")
    page.get_by_role("button", name="Apply filters").click()
    link = page.get_by_role("link", name="Download comparison CSV")
    response = page.request.get(link.get_attribute("href", timeout=1500))
    assert response.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(response.text())))
    assert len(rows) == 1 and rows[0]["harness"] == "codex"
    assert rows[0]["with_score"] and rows[0]["without_score"]


def test_rebuild_rejects_path_shaped_native_agent_keys(page, retained):
    _, _, volume = retained
    report = next((volume / "artifacts").rglob("report.html"))
    report.unlink()
    config = report.with_name("run_config.json")
    doc = json.loads(config.read_text())
    doc["agents"]["../unrelated"] = {"agent": "malformed"}
    config.write_text(json.dumps(doc))
    page.get_by_role("link", name="Review artifacts and feedback").click()
    page.get_by_role("link", name="View report", exact=True).click()
    playwright.expect(page.get_by_role("main").get_by_role("alert")).to_contain_text("Cannot rebuild")
    response = page.request.get(page.url.replace("/projects/", "/api/v1/projects/"))
    assert response.status == 422 and not report.exists()
