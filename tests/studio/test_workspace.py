"""Author journeys against real Chromium, HTTP and Git."""

import base64
import functools
import io
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import pytest

playwright = pytest.importorskip("playwright.sync_api")
uvicorn = pytest.importorskip("uvicorn")
pytest.importorskip("fastapi")
pytest.importorskip("python_multipart")


@contextmanager
def running(data):
    from studio.app import create_app

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        server = uvicorn.Server(uvicorn.Config(create_app(data), log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]})
        thread.start()
        try:
            yield f"http://127.0.0.1:{sock.getsockname()[1]}"
        finally:
            server.should_exit = True
            thread.join(10)


@pytest.fixture
def page():
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=shutil.which("google-chrome"))
        yield browser.new_page()
        browser.close()


@pytest.fixture
def before_push():
    """One-shot collaborator actions between the author's check and Git's ref advertisement."""
    return []


@pytest.fixture
def private_remote(tmp_path, loopback_tls, monkeypatch, before_push, api_handler):
    origin = tmp_path / "server"
    origin.mkdir()
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "-b", "main", seed], check=True)
    skill = seed / "skills" / "triage"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Triage\n")
    (seed / "alias").symlink_to("skills/triage")
    subprocess.run(["git", "add", "."], cwd=seed, check=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=t@example.org", "commit", "-m", "seed"], cwd=seed, check=True
    )
    repo = origin / "handbook.git"
    subprocess.run(["git", "clone", "--bare", seed, repo], check=True)
    subprocess.run(["git", "update-server-info"], cwd=repo, check=True)
    token = "private-fixture-key"
    expected = base64.b64encode(f"author:{token}".encode()).decode()

    subprocess.run(["git", "config", "http.receivepack", "true"], cwd=repo, check=True)

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if api_handler and api_handler[0](self):
                return
            if self.headers.get("Authorization") == f"Basic {expected}":
                path, _, query = self.path.partition("?")
                if query == "service=git-receive-pack" and before_push:
                    before_push.pop()()
                size = self.headers.get("Content-Length", "0")
                reply = subprocess.check_output(
                    ["git", "http-backend"],
                    input=self.rfile.read(int(size)),
                    env={
                        **os.environ,
                        "GIT_PROJECT_ROOT": str(origin),
                        "GIT_HTTP_EXPORT_ALL": "1",
                        "REQUEST_METHOD": self.command,
                        "PATH_INFO": path,
                        "QUERY_STRING": query,
                        "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                        "CONTENT_LENGTH": size,
                        "REMOTE_USER": "author",
                    },
                )
                headers, body = reply.split(b"\r\n\r\n", 1)
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                for header in io.BytesIO(headers):
                    key, value = header.decode().strip().split(": ", 1)
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="git"')
            self.end_headers()
            return

        do_POST = do_GET  # noqa: N815 -- HTTP handler protocol

    tls, cert = loopback_tls
    monkeypatch.setenv("GIT_SSL_CAINFO", str(cert))
    with ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=origin)) as remote:
        remote.socket = tls.wrap_socket(remote.socket, server_side=True)
        thread = threading.Thread(target=remote.serve_forever)
        thread.start()
        try:
            yield f"https://127.0.0.1:{remote.server_port}/handbook.git", token
        finally:
            remote.shutdown()
            thread.join()


def connect(page, url, token, skill):
    page.get_by_label("Repository URL").fill(url)
    page.get_by_label("Skill folder").fill(skill)
    page.get_by_text("Private repository credentials").click()
    page.get_by_label("Git username").fill("author")
    page.get_by_label("Access token").fill(token)
    page.get_by_role("button", name="Connect project").click()


def test_studio_accepts_only_loopback_or_configured_proxy_hosts(page, tmp_path, monkeypatch):
    with running(tmp_path / "volume") as base:
        assert page.goto(base).status == 200
        for host in ("localhost:8000", "[::1]:8000"):
            assert page.request.get(base, headers={"Host": host}).status == 200
        host = "studio.example.test"
        headers = {"Host": host, "Origin": f"http://{host}"}
        assert page.request.get(base, headers=headers).status == 400
        assert page.request.post(base + "/projects", headers=headers).status == 400
    monkeypatch.setenv("STUDIO_TRUSTED_HOSTS", "studio.example.test,studio.internal")
    with running(tmp_path / "volume") as base:
        assert page.request.get(base, headers={"Host": "studio.example.test:8443"}).status == 200
        assert page.request.get(base, headers={"Host": "other.example.test"}).status == 400


@pytest.fixture
def deployment(tmp_path, private_remote):
    """Optionally run the same journey with real disposable Linux containers."""
    image = os.environ.get("STUDIO_TEST_IMAGE")
    if not image:
        yield lambda: running(tmp_path / "volume")
        return
    volume = f"studio-test-{uuid4().hex}"
    subprocess.run(["docker", "volume", "create", volume], check=True)

    @contextmanager
    def container():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        ca = os.environ["GIT_SSL_CAINFO"]
        cid = subprocess.check_output(
            [
                "docker",
                "run",
                "-d",
                "--network=host",
                "-v",
                f"{volume}:/data",
                "-v",
                f"{ca}:/fixture-ca.pem:ro",
                "-e",
                "GIT_SSL_CAINFO=/fixture-ca.pem",
                image,
                "uvicorn",
                "studio.app:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            text=True,
        ).strip()
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(80):
                try:
                    with urllib.request.urlopen(base, timeout=1):
                        break
                except OSError:
                    time.sleep(0.1)
            yield base
        finally:
            subprocess.run(["docker", "rm", "-f", cid], check=True)

    try:
        yield container
    finally:
        subprocess.run(["docker", "volume", "rm", volume], check=True)


def test_author_reopens_private_skill_after_replacement(page, tmp_path, private_remote, deployment):
    url, token = private_remote
    with deployment() as first:
        page.goto(first)
        connect(page, url, token, "skills/triage")
        playwright.expect(page.get_by_role("heading", name="handbook")).to_be_visible()
        assert token not in page.content()
    with deployment() as second:
        page.goto(second)
        page.get_by_role("link", name="handbook").click()
        playwright.expect(page.get_by_text("skills/triage", exact=True)).to_be_visible()
        playwright.expect(page.get_by_text("main", exact=True)).to_be_visible()
        page.get_by_role("button", name="Check remote access").click(timeout=2000)
        playwright.expect(page.get_by_role("status")).to_have_text("Remote access confirmed.")
    volume = tmp_path / "volume"
    if volume.exists():
        assert all(
            token.encode() not in path.read_bytes()
            for path in volume.rglob("*")
            if not path.is_symlink() and path.is_file()
        )


def test_linked_skill_folder_cannot_be_connected(page, tmp_path, private_remote):
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="alias")
        playwright.expect(page.get_by_role("alert")).to_contain_text("symbolic link")
        playwright.expect(page.get_by_text("No projects yet")).to_be_visible()


def test_author_finds_project_tasks_and_returns_by_keyboard_on_phone(page, tmp_path, private_remote):
    page.set_viewport_size({"width": 360, "height": 800})
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        authoring = page.get_by_role("region", name="Authoring", exact=True)
        evaluation = page.get_by_role("region", name="Evaluation", exact=True)
        playwright.expect(authoring.get_by_role("link", name="Edit skill")).to_be_visible(timeout=2000)
        playwright.expect(evaluation.get_by_role("link", name="Provider settings")).to_be_visible()
        runs = evaluation.get_by_role("link", name="Evaluation runs")
        page.keyboard.press("Tab")
        playwright.expect(page.get_by_role("link", name="Skip to content")).to_be_focused()
        page.keyboard.press("Enter")
        for _ in range(20):
            page.keyboard.press("Tab")
            if runs.evaluate("el => el === document.activeElement"):
                break
        playwright.expect(runs).to_be_focused()
        page.keyboard.press("Enter")
        playwright.expect(page.get_by_role("heading", name="Evaluation runs")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        back = page.get_by_role("navigation", name="Breadcrumb").get_by_role("link", name="handbook")
        back.focus()
        page.keyboard.press("Enter")
        results = page.get_by_role("region", name="Results", exact=True)
        results.get_by_role("link", name="Run history").click()
        playwright.expect(page.get_by_role("heading", name="Run history")).to_be_in_viewport()


def test_extension_links_remain_discoverable_without_task_metadata(page, tmp_path, private_remote, monkeypatch):
    from fastapi import APIRouter
    from fastapi.responses import PlainTextResponse

    from studio import app

    extension = APIRouter()

    @extension.get("/projects/{project_id}/notes", name="notes", response_class=PlainTextResponse)
    def notes(project_id: str):
        return "Author notes"

    monkeypatch.setattr(app, "ROUTERS", (*app.ROUTERS, extension))
    monkeypatch.setattr(app, "PROJECT_LINKS", (*app.PROJECT_LINKS, ("Notes", "notes"), ("Journal", "notes")))
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        tools = page.get_by_role("region", name="Project tools")
        playwright.expect(tools.get_by_role("link", name="Journal")).to_be_visible()
        tools.get_by_role("link", name="Notes").click(timeout=2000)
        playwright.expect(page.get_by_text("Author notes")).to_be_visible()


@pytest.mark.parametrize("budget", ["ENTRIES", "INVENTORY_BYTES", "STORAGE_BYTES", "CHECKOUT_BYTES", "BLOB_BYTES"])
def test_import_refuses_over_budget_tree_and_removes_clone(tmp_path, private_remote, monkeypatch, budget):
    from studio.workspace import Workspace, WorkspaceError

    monkeypatch.setenv("STUDIO_GIT_MAX_" + budget, "16384" if budget == "STORAGE_BYTES" else "1")
    ws = Workspace(tmp_path / "volume")
    url, token = private_remote
    with pytest.raises(WorkspaceError, match="limit"):
        ws.connect(url, "skills/triage", "author", token)
    assert ws.projects() == []
    assert list(ws.repos.iterdir()) == []
