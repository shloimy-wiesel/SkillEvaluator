"""Opt-in worker acceptance: real Docker, OpenCode and the generated standard verifier."""

import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest


@pytest.mark.skipif(os.getenv("STUDIO_TEST_LIVE_RUNTIME") != "1", reason="requires local Docker, Compose and Harbor")
def test_private_standard_trial(tmp_path, monkeypatch, make_tls):
    from studio.live_job import invoke_engine
    from studio.native_location import native_directory

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
            self.reply({"data": [{"id": "private-agent"}, {"id": "private-judge"}]})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            model = body["model"]
            if self.path != "/v1/chat/completions" or self.headers.get("Authorization") != "Bearer fixture-chat-secret":
                return self.send_error(403)
            calls.append((self.client_address[0], model))
            if model == "private-agent":
                parts = [
                    {"delta": {"role": "assistant", "content": "Four."}, "finish_reason": None},
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
            self.reply(
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

    skill = tmp_path / "inputs" / "addition"
    (skill / "evals").mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: addition\ndescription: Add small numbers.\n---\nReturn the sum.")
    (skill / "evals/evals.json").write_text(
        json.dumps(
            {
                "skill_name": "addition",
                "evals": [{"id": "sum", "prompt": "What is two plus two?", "expected_output": "Four."}],
            }
        )
    )
    monkeypatch.setenv("STUDIO_LIVE_ENABLED", "1")
    with ThreadingHTTPServer((host, 0), Fixture) as server:
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            env = dict(
                PATH=f"{Path(sys.executable).parent}:/usr/local/bin:/usr/bin:/bin",
                HOME=str(tmp_path),
                SSL_CERT_FILE=str(ca),
                SKILL_EVAL_LLM_PROVIDER="openai-compatible",
                SKILL_EVAL_LLM_MODEL="private-judge",
                SKILL_EVAL_LLM_API_KEY="fixture-chat-secret",
                SKILL_EVAL_LLM_BASE_URL=f"https://{host}:{server.server_port}/v1",
            )
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
                    env["SKILL_EVAL_LLM_BASE_URL"] + "/models",
                ],
                check=True,
                timeout=30,
            )
            code = invoke_engine(
                [
                    "tier3",
                    "evaluate",
                    str(skill),
                    "--env-mode",
                    "docker",
                    "--agents",
                    "opencode",
                    "--agent-model",
                    "opencode=openai/private-agent",
                    "--skip-baseline",
                    "--no-agent-runtime-preflight",
                    "--n-attempts",
                    "1",
                    "--max-cases",
                    "1",
                    "--harbor-keep-jobs",
                    "--results-dir",
                    str(tmp_path / "results"),
                ],
                tmp_path,
                env,
            )
        finally:
            server.shutdown()
            thread.join()
    assert {model for peer, model in calls if peer != host} == {"private-agent", "private-judge"}, (code, calls)
    native = native_directory(tmp_path / "results")
    result = json.loads((native / "result.json").read_text())
    assert result["execution_status"] == "succeeded"
    assert result["agents"]["opencode"]["model"] == "openai/private-agent"
    (reward,) = native.rglob("skill_evaluator_reward.json")
    accuracy = json.loads(reward.read_text())["details"]["accuracy"]
    assert (accuracy["judge_model_used"], accuracy["score"]) == ("private-judge", 1.0)
    assert any(item.get("excerpt") == "Four." for item in accuracy["evidence_refs"])
    assert not any(b"fixture-chat-secret" in file.read_bytes() for file in native.rglob("*") if file.is_file())


def test_worker_rejects_mixed_key_and_certificate_before_trial(tmp_path, loopback_tls):
    from studio.worker_deadline import run_evaluator
    from studio.workspace import WorkspaceError

    _, ca = loopback_tls
    ca.write_bytes(ca.read_bytes() + (tmp_path / "key.pem").read_bytes())
    with pytest.raises(WorkspaceError, match="public PEM certificates"):
        run_evaluator([sys.executable, "--version"], cwd=tmp_path, sandbox=True, env={"SSL_CERT_FILE": str(ca)})
