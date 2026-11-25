import json
import os
import subprocess
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from test_providers import open_settings, save_profile
from test_workspace import playwright, running

pytest_plugins = ("test_workspace",)


def test_author_runs_direct_tier2_and_inspects_skipped_catalog(page, private_remote, tmp_path):
    with running(tmp_path / "volume") as base:
        settings = open_settings(page, base, private_remote)
        for role in ("Chat", "Embeddings"):
            save_profile(
                page.get_by_role("region", name=role, exact=True),
                f"https://{role.lower()}.invalid/v1",
                role + "-model",
                role + "-secret",
            )
        page.goto(base + settings.rsplit("/", 1)[0])
        page.get_by_role("link", name="Evaluate overlap").click(timeout=2000)
        page.get_by_role("button", name="Queue overlap checks").click()
        playwright.expect(page.get_by_text("catalog_comparison: skipped", exact=False)).to_be_visible(timeout=15000)
        report = page.request.get(page.get_by_role("link", name="Download JSON").get_attribute("href")).json()
        assert report["workflow"]["stages"]["catalog_comparison"]["status"] == "skipped"
        playwright.expect(page.get_by_role("link", name="overlap.html", exact=True)).to_be_visible()
        assert "Chat-secret" not in page.content()


@contextmanager
def inference(tls, redirect=None, varied=False):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, self.headers["Authorization"], body["model"]))
            if redirect:
                self.send_response(307)
                self.send_header("Location", redirect)
                self.end_headers()
                return
            if self.path.endswith("/embeddings"):
                reply = {
                    "data": [
                        {"index": i, "embedding": [0.6, 0.8] if varied and "other" in text else [1.0, 0.0]}
                        for i, text in enumerate(body["input"])
                    ]
                }
            else:
                verdict = {
                    "verdict": "DUPLICATE",
                    "confidence": 0.99,
                    "rationale": "Same steps.",
                    "suggestion": "Consolidate.",
                }
                reply = {"choices": [{"message": {"content": json.dumps(verdict)}, "finish_reason": "stop"}]}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(reply).encode())

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            yield f"https://127.0.0.1:{server.server_port}/v1", requests
        finally:
            server.shutdown()
            thread.join()


def test_adapter_runs_with_frozen_role_specific_models_and_credentials(tmp_path, loopback_tls, monkeypatch):
    from contextlib import closing

    from studio.jobs import JobContext
    from studio.overlap import evaluate, snapshot
    from studio.providers import database
    from studio.workspace import Workspace

    workspace = Workspace(tmp_path / "volume")
    root = tmp_path / "project"
    skill = root / "skill"
    skill.mkdir(parents=True)
    for name in ["SKILL.md", "guide.md"]:
        (skill / name).write_text("# Procedure\n" + "Check every request carefully. " * 20)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    ctx = JobContext(root, skill, "sha", lambda _: None, workspace, "project", "run", artifacts)
    tls, ca = loopback_tls
    monkeypatch.setenv("SSL_CERT_FILE", os.path.relpath(ca))
    with inference(tls) as (chat, calls), inference(tls) as (emb, vectors):
        with closing(database(workspace)) as db, db:
            for role, base in [("chat", chat), ("embeddings", emb)]:
                profile = {"provider": "openai", "key": role + "-key", "model": "saved-model", "base_url": base}
                db.execute(
                    "INSERT INTO provider_profiles VALUES (?,?,?)",
                    ("project", role, workspace.cipher.encrypt(json.dumps(profile).encode())),
                )
        options = snapshot(workspace, "project", "dedup", model="embedding-override", llm_model="chat-override")
        with closing(database(workspace)) as db, db:
            db.execute("DELETE FROM provider_profiles")
        outcome = evaluate(ctx, options)
        assert vectors == [("/v1/embeddings", "Bearer embeddings-key", "embedding-override")]
        assert calls == [("/v1/chat/completions", "Bearer chat-key", "chat-override")]
        assert outcome.status == "failed" and outcome.exit_code == 1
        assert "Consolidate." in outcome.report


def test_author_builds_catalog_from_pinned_collection_and_selects_artifacts(
    page, private_remote, tmp_path, loopback_tls, monkeypatch
):
    seed = tmp_path / "seed"
    for name in ("triage", "other"):
        folder = seed / "skills" / name
        folder.mkdir(exist_ok=True)
        (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Handle {name} tasks.\n---\n# Steps\n")
        for kind, filename in [("rules", "policy.mdc"), ("workflows", "workflow-rules.mdc")]:
            (folder / filename).write_text(f"---\ntitle: {name}-{kind}\ndescription: Handle {kind}.\n---\n# Steps\n")
    subprocess.run(["git", "add", "skills"], cwd=seed, check=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=t@example.org", "commit", "-m", "collection"],
        cwd=seed,
        check=True,
    )
    subprocess.run(["git", "push", tmp_path / "server/handbook.git", "main"], cwd=seed, check=True)
    tls, ca = loopback_tls
    monkeypatch.setenv("SSL_CERT_FILE", str(ca))
    with inference(tls) as (endpoint, calls), running(tmp_path / "volume") as base:
        settings = open_settings(page, base, private_remote)
        save_profile(
            page.get_by_role("region", name="Embeddings", exact=True), endpoint, "test-vector", "embedding-key"
        )
        page.goto(base + settings.rsplit("/", 1)[0])
        page.get_by_role("link", name="Evaluate overlap").click()
        page.get_by_label("Overlap checks").select_option("similarity")
        page.get_by_label("Collection directory").select_option("skills", timeout=2000)
        page.get_by_label("Save catalog").check()
        page.get_by_label("Content type").select_option("skill")
        page.get_by_label("Maximum entries").fill("2")
        page.get_by_label("Maximum scalar comparisons").fill("2")
        page.get_by_label("Compare full bodies").check()
        page.get_by_label("Report formats").select_option(["cli", "json", "markdown", "junit", "sarif", "github"])
        page.get_by_role("button", name="Queue overlap checks").click()
        catalog = page.get_by_role("link", name="catalog.json", exact=True)
        playwright.expect(catalog).to_be_visible(timeout=15000)
        data = page.request.get(catalog.get_attribute("href")).json()
        assert len(data["entries"]) == 2 and data["mode"] == "full-body" and data["model"] == "test-vector"
        assert calls and all(req[1] == "Bearer embedding-key" for req in calls)
        assert page.get_by_role("link", name="overlap.html", exact=True).count() == 0
        playwright.expect(page.get_by_role("link", name="overlap.junit.xml", exact=True)).to_be_visible()
        for filename, fragment in [
            ("overlap.junit.xml", "<testsuite"),
            ("overlap.sarif.json", "2.1.0"),
            ("overlap.json", "Similarity Check"),
            ("overlap.md", "Similarity"),
            ("github.txt", "::"),
        ]:
            link = page.get_by_role("link", name=filename, exact=True)
            assert fragment in page.request.get(link.get_attribute("href")).text()
        queued = page.url
        form = base + settings.rsplit("/", 1)[0] + "/overlap"
        for limit, value in [("Maximum entries", "1"), ("Maximum scalar comparisons", "1")]:
            page.goto(form)
            page.get_by_label("Overlap checks").select_option("similarity")
            page.get_by_label("Collection directory").select_option("skills")
            page.get_by_label(limit).fill(value)
            page.get_by_role("button", name="Queue overlap checks").click()
            playwright.expect(page.get_by_role("status")).to_contain_text("Results saved", timeout=12000)
            limited = page.request.get(page.get_by_role("link", name="Download JSON").get_attribute("href")).json()
            assert not limited["results"][0]["passed"]
            assert page.url != queued
        for kind in ("rules", "workflows"):
            page.goto(form)
            page.get_by_label("Overlap checks").select_option("similarity")
            page.get_by_label("Collection directory").select_option("skills")
            page.get_by_label("Content type").select_option(kind)
            page.get_by_role("button", name="Queue overlap checks").click()
            playwright.expect(page.get_by_role("status")).to_contain_text("Results saved", timeout=12000)
            report = page.request.get(page.get_by_role("link", name="Download JSON").get_attribute("href")).json()
            assert f"triage-{kind}" in report["results"][0]["findings"][0]["message"]


def test_scoped_catalog_preflight_and_incomplete_redirect(page, private_remote, tmp_path, loopback_tls, monkeypatch):
    seed = tmp_path / "seed"
    (seed / "broken.json").write_text("{}")
    (seed / "skills/triage/SKILL.md").write_text("# Main\n" + "Follow these steps. " * 30)
    (seed / "skills/triage/guide.md").write_text("# Review\n" + "Do the work. " * 40)
    subprocess.run(["git", "add", "."], cwd=seed, check=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=t@example.org", "commit", "-m", "inputs"],
        cwd=seed,
        check=True,
    )
    subprocess.run(["git", "push", tmp_path / "server/handbook.git", "main"], cwd=seed, check=True)
    tls, ca = loopback_tls
    monkeypatch.setenv("SSL_CERT_FILE", str(ca))
    with (
        inference(tls) as (chat, calls),
        inference(tls, chat + "/unexpected") as (emb, vectors),
        running(tmp_path / "volume") as base,
    ):
        settings = open_settings(page, base, private_remote)
        for role, url in [("Chat", chat), ("Embeddings", emb)]:
            save_profile(page.get_by_role("region", name=role, exact=True), url, role + "-model", role + "-key")
        page.goto(base + settings.rsplit("/", 1)[0])
        page.get_by_role("link", name="Evaluate overlap").click()
        form = page.url
        sha = page.get_by_label("Commit SHA").input_value()
        for invalid in ("../broken.json", "/etc/passwd", "alias/SKILL.md"):
            assert page.request.post(form, form={"sha": sha, "catalog": invalid}).status == 422
        page.get_by_label("Comparison catalog").select_option("broken.json")
        page.get_by_role("button", name="Queue overlap checks").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("catalog", timeout=10000)
        assert not calls and not vectors
        page.goto(form)
        page.get_by_label("Overlap checks").select_option("context")
        page.get_by_label("Intra-skill threshold").fill("0.94")
        page.get_by_role("button", name="Queue overlap checks").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("Results saved", timeout=15000)
        report = page.request.get(page.get_by_role("link", name="Download JSON").get_attribute("href")).json()
        assert report["results"][0]["incomplete_scans"]
        assert vectors and not calls


def test_direct_catalog_and_thresholds_change_the_two_engine_stages(tmp_path, loopback_tls, monkeypatch):
    from contextlib import closing
    from dataclasses import replace

    from studio.jobs import JobContext
    from studio.overlap import evaluate, snapshot
    from studio.providers import database
    from studio.workspace import Workspace

    root = tmp_path / "repo"
    skill = root / "target"
    for name in ["target", "other"]:
        folder = root / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Classify {name} work.\n---\n"
            "# Procedure\n" + "Read the request carefully. " * 20
        )
    (skill / "guide.md").write_text("# Guide\n" + "Handle other requests. " * 20)
    tls, ca = loopback_tls
    monkeypatch.setenv("SSL_CERT_FILE", str(ca))
    workspace = Workspace(tmp_path / "volume")
    ctx = JobContext(root, skill, "sha", lambda _: None, workspace, "p", "run", tmp_path / "build")
    ctx.artifacts.mkdir()
    with inference(tls, varied=True) as (base, calls):
        with closing(database(workspace)) as db, db:
            for role in ("chat", "embeddings"):
                profile = {
                    "provider": "openai-compatible",
                    "key": role + "-key",
                    "model": role + "-model",
                    "base_url": base,
                }
                db.execute(
                    "INSERT INTO provider_profiles VALUES (?,?,?)",
                    ("p", role, workspace.cipher.encrypt(json.dumps(profile).encode())),
                )
        opts = snapshot(workspace, "p", "similarity", collection="other", content_type="skill", save_catalog=True)
        evaluate(ctx, opts)
        catalog = root / "baseline.json"
        (ctx.artifacts / "catalog.json").rename(catalog)
        for threshold, expected_matches in [(0.5, 1), (0.9, 0)]:
            opts = snapshot(
                workspace,
                "p",
                "direct",
                catalog="baseline.json",
                threshold=threshold,
                similarity_threshold=threshold,
                formats=("cli",),
            )
            ctx = replace(ctx, artifacts=tmp_path / str(threshold))
            ctx.artifacts.mkdir()
            calls.clear()
            report = json.loads(evaluate(ctx, opts).report)
            assert report["studio_artifacts"] == []
            assert report["workflow"]["stages"]["catalog_comparison"]["status"] != "skipped"
            assert len(report["results"][1]["findings"]) == expected_matches
            assert len([c for c in calls if c[0].endswith("completions")]) == expected_matches
