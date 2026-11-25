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
