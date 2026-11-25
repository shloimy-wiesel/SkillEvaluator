"""Opt-in worker acceptance: real Docker, OpenCode and the generated standard verifier."""

import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from test_providers import open_settings, save_profile
from test_workspace import playwright, running

pytest_plugins = ("test_workspace",)


@pytest.mark.skipif(os.getenv("STUDIO_TEST_LIVE_RUNTIME") != "1", reason="requires local Docker, Compose and Harbor")
def test_private_standard_trial(page, private_remote, tmp_path, monkeypatch, make_tls):
    from studio.native_location import native_directory
    from test_datasets import seed_skill

    host = subprocess.check_output(
        ["docker", "network", "inspect", "bridge", "--format", "{{(index .IPAM.Config 0).Gateway}}"], text=True
    ).strip()
    tls, ca = make_tls(host)
    calls = []

    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, body, stream=False):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if stream else "application/json")
            self.end_headers()
            self.wfile.write(body.encode() if stream else json.dumps(body).encode())

        def do_GET(self):
            if self.path != "/v1/models" or self.headers.get("Authorization") != "Bearer fixture-chat-secret":
                return self.send_error(403)
            return self.reply({"data": [{"id": "private-agent"}, {"id": "private-judge"}]})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            model = body["model"]
            if self.path != "/v1/chat/completions" or self.headers.get("Authorization") != "Bearer fixture-chat-secret":
                return self.send_error(403)
            calls.append((self.client_address[0], model))
            if model == "private-agent":
                parts = [
                    {"delta": {"role": "assistant", "content": "The sum is four."}, "finish_reason": None},
                    {"delta": {}, "finish_reason": "stop"},
                ]
                chunks = [
                    {
                        "id": "fixture",
                        "model": model,
                        "object": "chat.completion.chunk",
                        "created": 1,
                        "choices": [{"index": 0, **part}],
                    }
                    for part in parts
                ]
                return self.reply("".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n", True)
            if model != "private-judge":
                return self.send_error(400)
            prompt = str(body["messages"])
            if "The sum is four." not in prompt:
                return self.send_error(422, "Missing trial evidence")
            answer = {
                "user_goal": "Add two and two",
                "end_state": "Answered four",
                "achieved": True,
                "reason": "The answer is four.",
            }
            if "FORMAT_FOLLOWED" in prompt:
                answer = {
                    "criteria": dict.fromkeys(
                        ("ACTION_CORRECT", "FACTUALLY_ACCURATE", "TASK_ADDRESSED", "ACTIONABLE", "FORMAT_FOLLOWED"),
                        True,
                    ),
                    "reason": "The answer is four.",
                }
            return self.reply(
                {
                    "id": "judge",
                    "created": 1,
                    "model": model,
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": json.dumps(answer)},
                        }
                    ],
                }
            )

    seed_skill(
        tmp_path,
        {
            "evals/evals.json": json.dumps(
                {
                    "skill_name": "triage",
                    "evals": [{"id": "sum", "prompt": "What is two plus two?", "expected_output": "Four."}],
                }
            ),
        },
    )
    monkeypatch.setenv("SSL_CERT_FILE", os.path.relpath(ca))
    volume = tmp_path / "volume"
    monkeypatch.setenv("STUDIO_LIVE_ENABLED", "1")
    with ThreadingHTTPServer((host, 0), Fixture) as server:
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            endpoint = f"https://{host}:{server.server_port}/v1"
            # A real TLS failure in an ordinary trial-network container. Never send a key on an unverified connection.
            subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "bridge",
                    "python:3.12-slim",
                    "python",
                    "-c",
                    "import ssl,sys,urllib.request,urllib.error\n"
                    "try: urllib.request.urlopen(sys.argv[1],timeout=5)\n"
                    "except urllib.error.URLError as e: assert isinstance(e.reason, ssl.SSLCertVerificationError), repr(e)\n"
                    'else: raise AssertionError("unexpected trust")',
                    endpoint + "/models",
                ],
                check=True,
                timeout=30,
            )
            with running(volume) as base:
                settings = open_settings(page, base, private_remote)
                save_profile(
                    page.get_by_role("region", name="Chat", exact=True),
                    endpoint,
                    "private-judge",
                    "fixture-chat-secret",
                )
                save_profile(
                    page.get_by_role("region", name="Embeddings", exact=True),
                    endpoint,
                    "private-embed",
                    "unused-embed-secret",
                )
                project_id = settings.split("/")[2]
                page.goto(base + settings.removesuffix("/providers") + "/live")
                page.get_by_label("opencode", exact=True).check()
                page.get_by_label("Comparison arms").select_option("skill")
                page.get_by_text("Trial settings and budgets").click()
                page.get_by_label("OpenCode model override").fill("openai/private-agent")
                page.get_by_label("Attempts per case").fill("1")
                page.get_by_label("Retain Harbor jobs").check()
                page.get_by_label("Run a paid agent preflight").select_option("false")
                page.get_by_role("button", name="Queue live evaluation").click()
                playwright.expect(
                    page.get_by_text("opencode: openai/private-agent · differs from saved chat", exact=True)
                ).to_be_visible()
                playwright.expect(page.get_by_text("Execution: succeeded", exact=False)).to_be_visible(timeout=240000)
                run_id = page.url.rsplit("/", 1)[1]
                assert "fixture-chat-secret" not in page.content() and "unused-embed-secret" not in page.content()
        finally:
            server.shutdown()
            thread.join()
    assert {model for peer, model in calls if peer != host} == {"private-agent", "private-judge"}, calls
    native = native_directory(volume / "artifacts" / project_id / run_id / "tier3")
    result = json.loads((native / "result.json").read_text())
    assert result["execution_status"] == "succeeded"
    assert result["agents"]["opencode"]["model"] == "openai/private-agent"
    (reward,) = native.rglob("skill_evaluator_reward.json")
    accuracy = json.loads(reward.read_text())["details"]["accuracy"]
    assert (accuracy["judge_model_used"], accuracy["score"]) == ("private-judge", 1.0)
    assert any(item.get("excerpt") == "The sum is four." for item in accuracy["evidence_refs"])
    for file in native.rglob("*"):
        if file.is_file():
            data = file.read_bytes()
            assert b"fixture-chat-secret" not in data and b"unused-embed-secret" not in data


def test_worker_rejects_mixed_key_and_certificate_before_trial(tmp_path, loopback_tls):
    import sys

    from studio.worker_deadline import run_evaluator
    from studio.workspace import WorkspaceError

    _, ca = loopback_tls
    ca.write_bytes(ca.read_bytes() + (tmp_path / "key.pem").read_bytes())
    with pytest.raises(WorkspaceError, match="public PEM certificates"):
        run_evaluator([sys.executable, "--version"], cwd=tmp_path, sandbox=True, env={"SSL_CERT_FILE": str(ca)})
