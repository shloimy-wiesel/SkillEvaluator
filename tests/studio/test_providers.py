import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from test_workspace import connect, playwright, running

pytest_plugins = ("test_workspace",)
expect = playwright.expect


def open_settings(page, base, remote):
    page.goto(base)
    connect(page, *remote, skill="skills/triage")
    page.get_by_role("link", name="Provider settings").click(timeout=2000)
    return page.url.removeprefix(base)


def save_profile(panel, endpoint, model, key):
    panel.get_by_label("Provider", exact=True).select_option("openai-compatible")
    panel.get_by_label("Base URL").fill(endpoint)
    panel.get_by_label("Model", exact=True).fill(model)
    panel.get_by_label("API key").fill(key)
    panel.get_by_role("button", name="Save settings").click()


def test_author_reopens_independent_profiles(page, private_remote, tmp_path):
    volume = tmp_path / "volume"
    with running(volume) as base:
        path = open_settings(page, base, private_remote)
        for role in ("Chat", "Embeddings"):
            panel = page.get_by_role("region", name=role, exact=True)
            save_profile(panel, f"https://{role.lower()}.private/v1", f"{role}-model", f"{role}-secret")
    with running(volume) as base:
        page.goto(base + path)
        for role in ("Chat", "Embeddings"):
            panel = page.get_by_role("region", name=role, exact=True)
            expect(panel.get_by_label("Model", exact=True)).to_have_value(f"{role}-model")
            expect(panel.get_by_label("Base URL")).to_have_value(f"https://{role.lower()}.private/v1")
            expect(panel.get_by_text("Key stored")).to_be_visible()
            assert f"{role}-secret" not in page.content()
            assert f"{role}-secret".encode() not in (volume / "studio.sqlite3").read_bytes()


@pytest.fixture
def gateway(loopback_tls, monkeypatch):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append((self.path, self.headers.get("Authorization")))
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            allowed = self.path.startswith("/allowed/")
            if self.path.startswith("/role/"):
                allowed = (self.path, self.headers.get("Authorization"), body.get("model")) in {
                    ("/role/vector/embeddings", "Bearer key-B", "embed-private"),
                    ("/role/chat/chat/completions", "Bearer key-A", "chat-private"),
                }
            self.send_response(200 if allowed else 401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if allowed and self.path.endswith("/embeddings"):
                body = {"data": [{"index": 0, "object": "embedding", "embedding": [0.3, 0.4]}]}
            elif allowed:
                body = {"choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}}]}
            else:
                body = {"error": {"message": "never-display-this-provider-body"}}
            self.wfile.write(json.dumps(body).encode())

        def do_GET(self):
            seen.append((self.path, self.headers.get("Authorization")))
            if self.path.startswith("/redirect"):
                self.send_response(307)
                self.send_header("Location", "/unexpected")
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"data": [{"id": "private-chat"}, {"id": "chat-secret"}]}).encode())

    tls, ca = loopback_tls
    monkeypatch.setenv("SSL_CERT_FILE", str(ca))
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            yield f"https://127.0.0.1:{server.server_port}", seen
        finally:
            server.shutdown()
            thread.join()


def test_private_model_readiness_and_credential_boundaries(page, private_remote, tmp_path, gateway):
    endpoint, seen = gateway
    with running(tmp_path / "volume") as base:
        open_settings(page, base, private_remote)
        chat = page.get_by_role("region", name="Chat", exact=True)
        save_profile(chat, endpoint + "/v1", "private-chat", "chat-secret")
        probe = chat.get_by_role("button", name="Check readiness and discover models")
        probe.click(timeout=2000)
        expect(chat.get_by_role("status")).to_contain_text("Selected model is listed")
        expect(chat.get_by_role("listitem")).to_have_text("private-chat")
        assert seen == [("/v1/models", "Bearer chat-secret")]
        assert "chat-secret" not in page.content()
        save_profile(chat, endpoint + "/redirect", "private-chat", "chat-secret")
        probe.click()
        expect(page.get_by_role("alert")).to_contain_text("discovery failed")
        assert seen[-1] == ("/redirect/models", "Bearer chat-secret")
        save_profile(chat, "https://other.private/v1", "elsewhere", "")
        expect(chat.get_by_text("No key stored")).to_be_visible()
        probe.click()
        expect(page.get_by_role("alert")).to_contain_text("API key")


def test_worker_resolves_each_saved_profile_without_host_credentials(page, private_remote, tmp_path, monkeypatch):
    from studio.providers import worker_environment
    from studio.workspace import Workspace

    from skillevaluator.provider_config import resolve_embedding_provider, resolve_llm_provider

    volume = tmp_path / "volume"
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-key")
    with running(volume) as base:
        project_id = open_settings(page, base, private_remote).split("/")[2]
        for role, key in [("Chat", "chat-credential"), ("Embeddings", "embedding-credential")]:
            panel = page.get_by_role("region", name=role, exact=True)
            save_profile(panel, f"https://{role.lower()}.private/v1", role + "-model", key)
            panel.get_by_label("Provider", exact=True).select_option("openai")
            panel.get_by_label("API key").fill(key)
            panel.get_by_role("button", name="Save settings").click()
    workspace = Workspace(volume)
    for role, resolver, expected in [
        ("chat", resolve_llm_provider, "chat-credential"),
        ("embeddings", resolve_embedding_provider, "embedding-credential"),
    ]:
        env = worker_environment(workspace, project_id, role)
        assert env["OPENAI_BASE_URL"] == f"https://{role}.private/v1"
        config = resolver(env)
        assert config.api_key == expected
        assert config.base_url == f"https://{role}.private/v1"
        assert config.model.lower() == role + "-model"
    assert os.environ["OPENAI_API_KEY"] == "ambient-key"


@pytest.mark.parametrize("command", ["doctor", "health-check"])
def test_scanner_readiness_scope_and_json(page, private_remote, tmp_path, command):
    with running(tmp_path / "volume") as base:
        open_settings(page, base, private_remote)
        page.get_by_label("Readiness action").select_option(command, timeout=1500)
        page.get_by_label("Tier scope").select_option("1")
        page.get_by_label("Scanner checks").select_option(["schema", "quality"])
        page.get_by_label("Probe timeout").fill("2.5")
        page.get_by_label("Show redacted JSON").check()
        page.get_by_role("button", name="Run selected check").click()
        payload = json.loads(page.get_by_label("Native JSON").inner_text())
        assert payload["command"] == command
        assert payload["status"] == "pass"
        assert [tier["tier"] for tier in payload["tiers"]] == ["1"]
        expect(page.get_by_role("table")).to_contain_text("the selected checks run no external scanner")


def test_models_native_limit_and_redacted_catalog(page, private_remote, tmp_path, gateway):
    endpoint, seen = gateway
    with running(tmp_path / "volume") as base:
        open_settings(page, base, private_remote)
        save_profile(
            page.get_by_role("region", name="Chat", exact=True), endpoint + "/v1", "private-chat", "chat-secret"
        )
        for limit, expected in [(1, ["private-chat"]), (2, ["private-chat", "[redacted]"])]:
            page.get_by_label("Readiness action").select_option("models", timeout=1500)
            page.get_by_label("Catalog limit").fill(str(limit))
            page.get_by_label("Show redacted JSON").check()
            page.get_by_role("button", name="Run selected check").click()
            report = json.loads(page.get_by_label("Native JSON").inner_text())
            assert [row["id"] for row in report["models"]] == expected
            assert report["models"][0]["is_configured"]
            assert "chat-secret" not in page.content()
        assert seen == [("/v1/models", "Bearer chat-secret")] * 2


def test_native_inference_requires_consent_and_isolates_roles(page, private_remote, tmp_path, gateway):
    endpoint, seen = gateway
    with running(tmp_path / "volume") as base:
        open_settings(page, base, private_remote)
        for role in ("Chat", "Embeddings"):
            panel = page.get_by_role("region", name=role, exact=True)
            save_profile(panel, endpoint + "/" + role.lower(), "private-model", role + "-key")
            panel.get_by_label("Provider", exact=True).select_option("openai")
            panel.get_by_label("API key").fill(role + "-key")
            panel.get_by_role("button", name="Save settings").click()
        for live in (False, True):
            page.get_by_label("Tier scope").select_option("2")
            if live:
                page.get_by_label("Allow provider probes").check(timeout=1500)
                page.get_by_label("Probe timeout").fill("3")
            page.get_by_role("button", name="Run selected check").click()
            expect(page.get_by_role("status")).to_have_text("Readiness: " + ("fail" if live else "pass"))
            if not live:
                assert seen == []
        expect(page.get_by_role("table")).to_contain_text("HTTP 401")
        assert seen == [
            ("/embeddings/embeddings", "Bearer Embeddings-key"),
            ("/chat/chat/completions", "Bearer Chat-key"),
        ]
        assert "never-display-this-provider-body" not in page.content()


def test_successful_native_inference(gateway, monkeypatch):
    from studio.readiness import Probe, inspect

    endpoint, seen = gateway
    monkeypatch.setenv("SSL_CERT_FILE", os.path.relpath(os.environ["SSL_CERT_FILE"]))
    chat = {
        "SKILL_EVAL_LLM_PROVIDER": "openai",
        "SKILL_EVAL_LLM_MODEL": "chat-private",
        "OPENAI_API_KEY": "key-A",
        "OPENAI_BASE_URL": endpoint + "/role/chat",
    }
    emb = {
        "SKILL_EVAL_EMBEDDING_PROVIDER": "openai",
        "SKILL_EVAL_EMBEDDING_MODEL": "embed-private",
        "OPENAI_API_KEY": "key-B",
        "OPENAI_BASE_URL": endpoint + "/role/vector",
    }
    payload, code = inspect(Probe(action="doctor", tier="2", verify_models=True, timeout=2), chat, emb)
    assert code == 0 and payload["status"] == "pass", payload
    assert {row["detail"] for row in payload["tiers"][0]["checks"]} >= {
        "returned a 2-dimension vector",
        "returned a chat completion",
    }
    assert seen == [("/role/vector/embeddings", "Bearer key-B"), ("/role/chat/chat/completions", "Bearer key-A")]


@pytest.mark.parametrize("command", ["doctor", "tier3 doctor", "health-check"])
def test_runtime_options_and_native_failures(page, private_remote, tmp_path, gateway, command):
    endpoint, seen = gateway
    with running(tmp_path / "volume") as base:
        open_settings(page, base, private_remote)
        save_profile(
            page.get_by_role("region", name="Chat", exact=True), endpoint + "/v1", "default-model", "chat-secret"
        )
        page.get_by_label("Readiness action").select_option(command, timeout=1500)
        if command != "tier3 doctor":
            page.get_by_label("Tier scope").select_option("all")
            page.get_by_label("Scanner checks").select_option("schema")
        page.get_by_text("Tier 3 runtime options", exact=True).click()
        page.get_by_label("Runtime agents").select_option(["claude", "codex"], timeout=1500)
        page.get_by_label("Runtime environment").select_option("kata")
        page.get_by_label("Kata runtime handler").fill("runc")
        page.get_by_label("Kata DNS").fill("1.1.1.1")
        if command != "health-check":
            page.get_by_label("Execution backend").select_option("nemo-gym")
            page.get_by_label("Allow provider probes").check()
        page.get_by_label("Show redacted JSON").check()
        page.get_by_role("button", name="Run selected check").click()
        payload = json.loads(page.get_by_label("Native JSON").inner_text())
        assert payload["status"] == "fail"
        assert [v["tier"] for v in payload["tiers"]] == (["3"] if command == "tier3 doctor" else ["1", "2", "3"])
        rows = payload["tiers"][-1]["checks"]
        assert any(
            row["check"] == "Harbor agents" and set(row["detail"].split(", ")) == {"claude-code", "codex"}
            for row in rows
        )
        if command == "health-check":
            assert any("kata_runtime" in row["detail"] for row in rows)
            assert not seen
        else:
            assert any("supports --env-mode docker only" in row["detail"] for row in rows)
            assert any("Harbor environment providers only" in row["detail"] for row in rows)
            assert any(row["status"] == "warn" and "--verify-models" in row["detail"] for row in rows)


@pytest.mark.parametrize("action", ["doctor", "tier3 doctor"])
def test_per_agent_catalog_results_from_installed_engine(page, private_remote, tmp_path, gateway, action):
    endpoint, seen = gateway
    with running(tmp_path / "volume") as base:
        open_settings(page, base, private_remote)
        save_profile(
            page.get_by_role("region", name="Chat", exact=True), endpoint + "/v1", "wrong-default", "chat-secret"
        )
        page.get_by_label("Readiness action").select_option(action)
        page.get_by_text("Tier 3 runtime options", exact=True).click()
        page.get_by_label("Runtime agents").select_option(["opencode", "codex"])
        page.get_by_label("codex model override").fill("private-chat", timeout=1500)
        page.get_by_label("opencode model override").fill("missing-model")
        page.get_by_label("Allow provider probes").check()
        page.get_by_role("button", name="Run selected check").click()
        expect(page.get_by_role("row").filter(has_text="codex model")).to_contain_text("private-chat")
        expect(page.get_by_role("row").filter(has_text="opencode model")).to_contain_text("missing-model")
        assert seen == [("/v1/models", "Bearer chat-secret")] * 2


@pytest.mark.parametrize("action", ["doctor", "health-check", "tier3 doctor"])
def test_adapter_matches_native_aliases(action, tmp_path):
    import subprocess
    import sys

    from studio.readiness import Probe, inspect

    result, code = inspect(
        Probe(action=action, agents=["claude"], env_mode="kata", kata_runtime="runc", kata_dns="1.1.1.1"), {}, {}
    )
    for agents, kwarg in [("-a", "--ek"), ("--agents", "--environment-kwarg")]:
        native = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                "from skillevaluator.cli import cli; cli()",
                *action.split(),
                agents,
                "claude-code",
                "--env-mode",
                "kata",
                kwarg,
                "kata_runtime=runc",
                kwarg,
                'kata_dns=["1.1.1.1"]',
                "--json",
            ],
            cwd=tmp_path,
            env={"HOME": str(tmp_path), "PATH": os.environ["PATH"]},
            capture_output=True,
        )
        assert native.returncode == code == 1
        assert result == json.loads(native.stdout)
        assert any(
            row["check"] == "kata prerequisite" and "kata_runtime" in row["detail"]
            for row in result["tiers"][0]["checks"]
        )


@pytest.mark.parametrize("action", ["doctor", "health-check"])
def test_native_scanner_timeout(action, tmp_path, monkeypatch):
    from studio.readiness import Probe, inspect

    scanner = tmp_path / "pip-audit"
    scanner.write_text("#!/bin/sh\nexec /bin/sleep 10\n")
    scanner.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    payload, code = inspect(Probe(action=action, tier="1", checks=["dependency"], timeout=0.1), {}, {})
    assert code == 1
    row = next(r for r in payload["tiers"][0]["checks"] if r["check"] == "pip-audit")
    assert row["status"] == "fail" and "timed out" in row["detail"].lower(), row


def test_invalid_probe_never_starts_provider_request(page, private_remote, tmp_path, gateway):
    endpoint, seen = gateway
    with running(tmp_path / "volume") as base:
        path = open_settings(page, base, private_remote)
        save_profile(
            page.get_by_role("region", name="Chat", exact=True), endpoint + "/v1", "private-chat", "chat-secret"
        )
        for action, options, message in [
            ("doctor", {"tier": "2", "verify_models": "true", "timeout": "nan"}, "timeout"),
            ("models", {"limit": "101"}, "limit"),
            ("health-check", {"verify_models": "true"}, "only to doctor"),
            ("doctor", {"codex_model": "chat-secret"}, "credentials"),
        ]:
            response = page.request.post(base + path + "/readiness/run", form={"action": action, **options})
            assert response.status == 422
            assert 'role="alert"' in response.text() and message in response.text()
            assert "chat-secret" not in response.text()
        assert not seen
