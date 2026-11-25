import json
import subprocess

# ruff: noqa: F811 -- pytest discovers shared browser fixtures by name
from test_workspace import before_push, connect, page, playwright, private_remote, running  # noqa: F401


def test_author_cases_and_publish_only_after_preview(page, tmp_path, private_remote):
    remote = tmp_path / "server/handbook.git"
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Datasets").click(timeout=1500)
        page.get_by_role("button", name="Open draft").click()
        page.get_by_label("Case ID").fill("first")
        page.get_by_label("Prompt", exact=True).fill("Classify the ticket")
        page.get_by_label("Expected output", exact=True).fill("An urgency level")
        page.get_by_label("Assertions").fill("Names the urgency\nExplains the evidence")
        page.get_by_role("button", name="Add case").click()
        playwright.expect(page.get_by_role("heading", name="first")).to_be_visible()
        page.get_by_role("button", name="Preview changes").click()
        playwright.expect(page.get_by_label("Change preview")).to_contain_text("+")
        assert subprocess.check_output(["git", "rev-list", "--count", "main"], cwd=remote).strip() == b"1"
        page.get_by_role("button", name="Commit and push").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("Pushed")
        saved = json.loads(subprocess.check_output(["git", "show", "main:skills/triage/evals/evals.json"], cwd=remote))
        assert saved["evals"] == [
            {
                "id": "first",
                "prompt": "Classify the ticket",
                "expected_output": "An urgency level",
                "assertions": ["Names the urgency", "Explains the evidence"],
            }
        ]


def test_generate_and_validate_local_draft(page, tmp_path, private_remote):
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Datasets").click()
        page.get_by_role("button", name="Open draft").click()
        page.get_by_text("Generate cases", exact=True).click(timeout=1500)
        page.get_by_label("Grounding").select_option("skill")
        page.get_by_label("Use local templates").check()
        page.get_by_role("button", name="Generate preview").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("Generated 1")
        page.get_by_role("button", name="Use generated cases").click()
        page.get_by_role("button", name="Validate draft").click()
        playwright.expect(page.get_by_label("Validation results")).to_contain_text("Dataset has 1 entry")


def test_review_export_before_publishing_redacted_fixtures(page, tmp_path, private_remote):
    remote = tmp_path / "server/handbook.git"
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Datasets").click()
        page.get_by_role("button", name="Open draft").click()
        page.get_by_text("Import traces", exact=True).click(timeout=1500)
        record = {
            "session_id": "one",
            "prompt": "Classify this incident",
            "outcome": "success",
            "final_output": "Priority two",
            "files": [{"path": "ticket.txt", "content": "person@real-domain.com"}],
        }
        page.get_by_label("Trace export").set_input_files(
            {
                "name": "export.jsonl",
                "mimeType": "application/json",
                "buffer": json.dumps(record).encode(),
            }
        )
        page.get_by_role("button", name="Import for review").click()
        page.get_by_label("Review decision").select_option("accept")
        page.get_by_label("Reviewer expectation").fill("Assigns severity two")
        page.get_by_role("button", name="Preview acceptance").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("1 addition")
        page.get_by_role("button", name="Stage accepted cases").click()
        page.get_by_role("button", name="Commit and push").click()
        saved = json.loads(subprocess.check_output(["git", "show", "main:skills/triage/evals/evals.json"], cwd=remote))
        (case,) = saved["evals"]
        assert case["trace_source"]["decision"] == "accept"
        assert case["expected_output"] == "Assigns severity two"
        content = subprocess.check_output(["git", "show", "main:skills/triage/evals/" + case["files"][0]], cwd=remote)
        assert content and b"real-domain.com" not in content


def test_create_named_dataset_then_edit_and_delete(page, tmp_path, private_remote):
    remote = tmp_path / "server/handbook.git"
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Datasets").click()
        page.get_by_role("button", name="Open draft").click()
        page.get_by_text("Manage datasets", exact=True).click(timeout=1500)
        page.get_by_label("New dataset name").fill("routing")
        page.get_by_role("button", name="Create dataset").click()
        page.get_by_label("Case ID").fill("one")
        page.get_by_label("Prompt", exact=True).fill("Route this task")
        page.get_by_label("Expected output", exact=True).fill("A route")
        page.get_by_label("Fixture selection").select_option("explicit")
        page.get_by_role("button", name="Add case").click()
        page.get_by_text("Edit case one", exact=True).click()
        page.get_by_label("Expected output", exact=True).first.fill("Route A")
        page.get_by_role("button", name="Update case").click()
        page.get_by_role("button", name="Commit and push").click()
        path = "main:skills/triage/evals/datasets/routing.json"
        (case,) = json.loads(subprocess.check_output(["git", "show", path], cwd=remote))["evals"]
        assert case["files"] == [] and case["expected_output"] == "Route A"
        page.get_by_role("button", name="Open draft").click()
        page.get_by_text("Manage datasets", exact=True).click()
        page.get_by_label("Dataset file").select_option("evals/datasets/routing.json")
        page.get_by_role("button", name="Switch dataset").click()
        page.get_by_text("Delete dataset", exact=True).click()
        page.get_by_role("button", name="Stage dataset deletion").click()
        page.get_by_role("button", name="Commit and push").click()
        assert subprocess.run(["git", "cat-file", "-e", path], cwd=remote).returncode != 0


def test_migrate_legacy_then_review_routing_without_losing_authored_fields(page, tmp_path, private_remote):
    from skillevaluator.tier3.dataset_utils import load_dataset_entries

    seed = tmp_path / "seed"
    remote = tmp_path / "server/handbook.git"
    source = seed / "skills/triage/eval/dataset.jsonl"
    source.parent.mkdir()
    source.write_text(
        json.dumps(
            {
                "id": 42,
                "question": "Identify routing",
                "ground_truth": "A route",
                "expected_skill": "triage",
                "metadata": {"origin": "maintainer"},
            }
        )
    )
    subprocess.run(["git", "add", "."], cwd=seed, check=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=t@example.org", "commit", "-m", "legacy"],
        cwd=seed,
        check=True,
    )
    subprocess.run(["git", "push", str(remote), "main"], cwd=seed, check=True)
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Datasets").click()
        page.get_by_role("button", name="Open draft").click()
        page.get_by_text("Migrate dataset", exact=True).click()
        page.get_by_label("New destination").fill("evals/evals.json")
        page.get_by_role("button", name="Run migration").click()
        page.get_by_text("Edit case 42", exact=True).click()
        page.get_by_label("Should this skill trigger?").first.select_option("no", timeout=1500)
        page.get_by_role("button", name="Update case").click()
        page.get_by_role("button", name="Commit and push").click()
        path = tmp_path / "published.json"
        path.write_bytes(subprocess.check_output(["git", "show", "main:skills/triage/evals/evals.json"], cwd=remote))
        (case,) = load_dataset_entries(path)
        assert case["should_trigger"] is False and case["id"] == 42 and "files" not in case
        assert case["metadata"] == {"origin": "maintainer"}
        assert (
            subprocess.check_output(["git", "show", "main:skills/triage/eval/dataset.jsonl"], cwd=remote)
            == source.read_bytes()
        )


def test_stale_publish_keeps_reviewable_draft_at_its_original_revision(page, tmp_path, private_remote):
    from test_editing import publish_from_seed

    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Datasets").click()
        page.get_by_role("button", name="Open draft").click()
        page.get_by_label("Case ID").fill("retained")
        page.get_by_label("Prompt", exact=True).fill("Classify incident")
        page.get_by_label("Expected output", exact=True).fill("Severity two")
        page.get_by_role("button", name="Add case").click()
        publish_from_seed(tmp_path, "main", "# Collaborator\n")
        with page.expect_response(lambda r: r.request.method == "POST" and r.status == 409):
            page.get_by_role("button", name="Commit and push").click()
        playwright.expect(page.get_by_role("alert")).to_contain_text("remote branch changed")
        page.goto(page.url)
        playwright.expect(page.get_by_role("heading", name="retained")).to_be_visible(timeout=1500)


def test_invalid_case_keeps_author_input_for_correction(page, tmp_path, private_remote):
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Datasets").click()
        page.get_by_role("button", name="Open draft").click()
        page.get_by_label("Case ID").fill("bad/id")
        page.get_by_label("Prompt", exact=True).fill("A carefully authored question")
        page.get_by_label("Expected output", exact=True).fill("Expected response")
        page.get_by_role("button", name="Add case").click()
        playwright.expect(page.get_by_role("alert")).to_contain_text("case id")
        playwright.expect(page.get_by_label("Prompt", exact=True)).to_have_value(
            "A carefully authored question", timeout=1500
        )


def test_model_preview_uses_only_saved_chat_credentials(page, tmp_path, private_remote, loopback_tls, monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    import pytest
    from test_providers import open_settings, save_profile

    pytest.importorskip("openai")
    calls = []
    candidate = {
        "id": "model-one",
        "question": "Which queue owns this ticket?",
        "expected_skill": "triage",
        "expected_script": None,
        "ground_truth": "Support queue",
        "expected_behavior": ["Names the queue"],
    }

    class Gateway(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["content-length"])))
            calls.append((self.path, self.headers["Authorization"], payload["model"]))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "choices": [
                            {
                                "finish_reason": "stop",
                                "index": 0,
                                "message": {"role": "assistant", "content": json.dumps([candidate])},
                            }
                        ]
                    }
                ).encode()
            )

    tls, ca = loopback_tls
    monkeypatch.setenv("SSL_CERT_FILE", str(ca))
    monkeypatch.setenv("OPENAI_API_KEY", "ambient")
    with ThreadingHTTPServer(("127.0.0.1", 0), Gateway) as server, running(tmp_path / "volume") as base:
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            settings = open_settings(page, base, private_remote)
            save_profile(
                page.get_by_role("region", name="Chat", exact=True),
                f"https://127.0.0.1:{server.server_port}/v1",
                "fixture-chat",
                "saved-chat",
            )
            page.goto(base + settings.rsplit("/", 1)[0])
            page.get_by_role("link", name="Datasets").click()
            page.get_by_role("button", name="Open draft").click()
            page.get_by_text("Generate cases", exact=True).click()
            page.get_by_label("Grounding").select_option("skill")
            page.get_by_role("button", name="Generate preview").click()
            playwright.expect(page.get_by_role("status")).to_contain_text("Mode: llm", timeout=2000)
            assert calls == [("/v1/chat/completions", "Bearer saved-chat", "fixture-chat")]
            playwright.expect(page.get_by_text(candidate["question"], exact=True)).to_be_visible()
        finally:
            server.shutdown()
            thread.join()
