import json
from pathlib import Path

import pytest
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
    page.get_by_role("button", name="Rerun saved inputs").click()
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
    monkeypatch.setenv("SSL_CERT_FILE", str(ca))
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
                assert page.get_by_label("Conversation").inner_text().count("Review triage-1.") == 2
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
