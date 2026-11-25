"""Author journeys against real Chromium, HTTP and Git."""

import base64
import functools
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
def private_remote(tmp_path, loopback_tls, monkeypatch):
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

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get("Authorization") == f"Basic {expected}":
                return super().do_GET()
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="git"')
            self.end_headers()
            return None

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
