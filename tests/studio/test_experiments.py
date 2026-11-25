"""Pinned experiment inputs and native evidence through Chromium."""

import hashlib
import json
import subprocess

from test_workspace import connect, playwright, running

pytest_plugins = ("test_workspace", "test_providers")


def publish(tmp_path):
    seed = tmp_path / "seed"
    repo = tmp_path / "server/handbook.git"
    for args in (
        ["add", "."],
        ["-c", "user.name=test", "-c", "user.email=t@example.org", "commit", "-m", "experiment"],
        ["push", repo, "main"],
    ):
        subprocess.run(["git", *args], cwd=seed, check=True)
    subprocess.run(["git", "update-server-info"], cwd=repo, check=True)


def export(page, label="JSON"):
    return page.request.get(page.get_by_role("link", name=f"Download {label}").get_attribute("href"))


def test_imported_observations_preserve_source_and_never_assign_a_gate(page, private_remote, tmp_path):
    src = tmp_path / "seed/observations.json"
    src.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "evaluation": dict.fromkeys(
                    (
                        "dataset_id",
                        "dataset_version",
                        "skill_id",
                        "skill_version",
                        "agent",
                        "agent_version",
                        "model",
                        "environment",
                    ),
                    "external-fixture",
                ),
                "provenance": {"producer": "lab", "run_id": "123", "created_at": "2026-10-01T12:00:00Z"},
                "metric_definitions": {
                    "credits": {
                        "version": "1",
                        "unit": "fraction",
                        "direction": "higher_is_better",
                        "aggregation": "mean",
                    }
                },
                "observations": [
                    {"case_id": "a", "attempt": 1, "arm": "with_skill", "custom_metrics": {"credits": 0.4}}
                ],
            }
        )
    )
    publish(tmp_path)
    volume = tmp_path / "volume"
    with running(volume) as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Experiments").click(timeout=2000)
        page.get_by_label("Observations JSON").fill("observations.json")
        page.get_by_role("button", name="Import observations").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("neutral")
        playwright.expect(page.get_by_text("External observations", exact=False).first).to_be_visible()
        report = export(page).json()
        assert report["executed_by_skillevaluator"] is False
        assert report["source_sha256"] == hashlib.sha256(src.read_bytes()).hexdigest()
        assert report["custom_lift"]["credits"]["delta"] is None
        assert export(page).body() == next(volume.rglob("external_metrics.json")).read_bytes()
        assert "NO SCORE" in export(page, "Markdown").text()


def test_select_decoys_retains_ranked_manifest_from_project_catalog(page, private_remote, tmp_path, loopback_tls):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from types import SimpleNamespace
    from unittest.mock import Mock

    from test_providers import open_settings, save_profile

    from skillevaluator.embedding.registry import EmbeddingRegistry

    seen = []

    class Gateway(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(
                (
                    self.headers["Authorization"],
                    json.loads(self.rfile.read(int(self.headers["Content-Length"])))["model"],
                )
            )
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"data":[{"embedding":[1,0],"index":0}]}')

    tls, ca = loopback_tls
    with ThreadingHTTPServer(("127.0.0.1", 0), Gateway) as server:
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        endpoint = f"https://127.0.0.1:{server.server_port}/v1"
        seed = tmp_path / "seed"
        for name in ("triage", "logs", "release"):
            folder = seed / "skills" / name
            folder.mkdir(exist_ok=True)
            (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Help with {name}.\n---\n\n# {name}\n")
        client = Mock(model="catalog-model")
        client._resolved_config.return_value = SimpleNamespace(provider="openai-compatible", base_url=endpoint)
        client.embed.return_value = [[1, 0], [1, 0], [1, 0]]
        registry = EmbeddingRegistry(client)
        registry.build_from_directory(seed / "skills", "skill")
        registry.save_catalog(seed / "catalog.json")
        publish(tmp_path)
        import os
        from unittest.mock import patch

        try:
            with patch.dict(os.environ, SSL_CERT_FILE=str(ca)), running(tmp_path / "volume") as base:
                settings = open_settings(page, base, private_remote)
                save_profile(
                    page.get_by_role("region", name="Embeddings", exact=True),
                    endpoint,
                    "default-model",
                    "embedding-secret",
                )
                page.goto(base + settings.removesuffix("/providers") + "/experiments")
                page.get_by_label("Catalog JSON").fill("catalog.json", timeout=2000)
                page.get_by_label("Catalog root").fill("skills")
                page.get_by_label("Decoy count").fill("1")
                page.get_by_label("Exclude paths").fill("release\ntriage")
                page.get_by_label("Embedding model override").fill("catalog-model")
                page.get_by_role("button", name="Select decoys").click()
                playwright.expect(page.get_by_role("status")).to_contain_text("neutral", timeout=20000)
                report = export(page).json()
                assert report["catalog_root"] == "." and report["exclude"] == ["release", "triage"]
                assert [(s["path"], s["score"]) for s in report["selected"]] == [("logs", 1.0)]
                assert seen == [("Bearer embedding-secret", "catalog-model")]
                assert export(page).body() == next((tmp_path / "volume/artifacts").rglob("decoys.json")).read_bytes()
        finally:
            server.shutdown()
            thread.join()


def test_interaction_pins_suite_and_retains_incomplete_evidence(page, private_remote, tmp_path, monkeypatch):
    from pathlib import Path

    from test_providers import open_settings, save_profile

    from studio import live_job

    seed = tmp_path / "seed"
    for name in ("logs", "suite"):
        folder = seed / "skills" / name
        folder.mkdir()
        (folder / "SKILL.md").write_text(f"# {name}\n")
    (folder / "evals").mkdir()
    dataset = folder / "evals/evals.json"
    dataset.write_text('{"skill_name":"suite","evals":[]}')
    (folder / "evals/config.yml").write_text("schema_version: 1\ngrading:\n  mode: default_plus_custom\n")
    (folder / "evals/grader.py").write_text("raise RuntimeError('sandbox only')\n")
    (seed / "skills/logs/evals").mkdir()
    (seed / "skills/logs/evals/config.yml").write_text("must not be loaded")
    publish(tmp_path)
    calls = []

    def engine(args, cwd, env):
        calls.append(1)
        from skillevaluator.utils.path_security import resolve_repo_context_root

        # The engine freezes each member again underneath TMPDIR. A volume
        # inside an operator checkout must never become the trial repo context.
        frozen = Path(env["TMPDIR"]) / "native-snapshot" / "skill-1" / "triage"
        frozen.mkdir(parents=True)
        assert resolve_repo_context_root(frozen) == frozen.parent
        assert env["SKILL_EVAL_LLM_API_KEY"] == "chat-secret"
        assert args[:2] == ["tier3", "interact"] and [Path(p).name for p in args[2:4]] == ["triage", "logs"]
        assert not (Path(args[3]) / "evals/config.yml").exists()

        def value(flag):
            return args[args.index("--" + flag) + 1]

        from skillevaluator.tier3.evals_config import parse_environment_kwarg_overrides

        overrides = [args[i + 1] for i, arg in enumerate(args) if arg == "--environment-kwarg"]
        assert parse_environment_kwarg_overrides(overrides, env_mode="kata") == {
            "kata_runtime": "kata-qemu",
            "kata_dns": ["192.0.2.1", "2001:db8::1"],
        }
        assert (Path(value("eval-source")) / "evals/evals.json").read_bytes() == dataset.read_bytes()
        assert (Path(value("eval-source")) / "evals/grader.py").is_file()
        assert [value(k) for k in ("metric", "n-attempts", "n-concurrent", "env-mode", "model", "agents")] == [
            "accuracy",
            "2",
            "3",
            "kata",
            "agent-v2",
            "opencode",
        ]
        native = Path(value("results-dir")) / "interaction_20260101_030405"
        native.mkdir(parents=True)
        assert "--harbor-keep-jobs" in args
        job = native / "baseline/run1/_harbor-jobs/trial"
        job.mkdir(parents=True)
        (job / "trial.log").write_text("No outcome; chat-secret")
        (native / "interaction.json").write_text(
            json.dumps(
                {
                    "kind": "skill_interaction",
                    "status": "incomplete",
                    "configurations": [],
                    "metric": "accuracy",
                    "reasons": ["Missing paired trials", "chat-secret"],
                }
            )
        )
        return 1

    monkeypatch.setattr(live_job, "invoke_engine", engine)
    subprocess.run(["git", "init", "-q", tmp_path / "volume"], check=True)
    with running(tmp_path / "volume") as base:
        settings = open_settings(page, base, private_remote)
        save_profile(
            page.get_by_role("region", name="Chat", exact=True), "https://chat.example/v1", "judge", "chat-secret"
        )
        url = base + settings.removesuffix("/providers") + "/experiments"
        page.goto(url)
        page.get_by_label("Selected skill folders").fill("skills/triage\nskills/logs", timeout=2000)
        page.get_by_label("Fixed evaluation source").fill("skills/suite")
        page.get_by_role("button", name="Run interaction").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("consent", timeout=8000)
        assert not calls
        page.goto(url)
        page.get_by_label("Selected skill folders").fill("skills/triage\nskills/logs")
        page.get_by_label("Fixed evaluation source").fill("skills/suite")
        page.get_by_label("Allow the repository grader in the sandbox").check()
        page.get_by_label("Outcome metric").select_option("accuracy")
        page.get_by_label("Environment").select_option("kata")
        page.get_by_label("Kata runtime").select_option("kata-qemu", timeout=2000)
        page.get_by_label("Kata DNS").fill("192.0.2.1\n2001:db8::1")
        page.get_by_label("Keep Harbor jobs").check(timeout=2000)
        page.get_by_label("Attempts per case").fill("2")
        page.get_by_label("Concurrent trials").fill("3")
        page.get_by_label("Agent model override").fill("agent-v2")
        page.get_by_label("opencode", exact=True).check()
        page.get_by_role("button", name="Run interaction").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("incomplete")
        assert export(page).json()["reasons"] == ["Missing paired trials", "[REDACTED]"]
        assert "baseline/run1/_harbor-jobs" in export(page, "Markdown").text()
        assert next((tmp_path / "volume/artifacts").rglob("trial.log")).read_text() == "No outcome; [REDACTED]"
        assert export(page).body() == next((tmp_path / "volume/artifacts").rglob("interaction.json")).read_bytes()
        for field, bad in [
            ("env_mode", "local"),
            ("environment_kwarg", "anything"),
            ("kata_runtime", "kata-qemu"),  # Docker accepts no overrides.
            ("skills", "../outside\nskills/logs"),
        ]:
            data = {
                "skills": "skills/triage\nskills/logs",
                "eval_source": "skills/suite",
                "sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=seed, text=True).strip(),
            }
            data[field] = bad
            assert page.request.post(url + "/interaction", form=data).status == 422
        data = dict(data, skills="skills/triage\nskills/logs", env_mode="kata")
        for field, bad in [("kata_runtime", "runc"), ("kata_dns", "resolver.example"), ("kata_dns", "fe80::1%eth0")]:
            assert page.request.post(url + "/interaction", form=dict(data, **{field: bad})).status == 422
        assert len(calls) == 1


def test_interaction_rerun_reuses_defaults_and_original_profile(page, private_remote, tmp_path, monkeypatch):
    from pathlib import Path

    from test_providers import open_settings, save_profile

    from studio import live_job

    seed = tmp_path / "seed"
    suite = seed / "skills/triage/evals"
    suite.mkdir()
    (suite / "evals.json").write_text('{"skill_name":"triage","evals":[]}')
    second = seed / "skills/audit"
    second.mkdir()
    (second / "SKILL.md").write_text("# Audit")
    publish(tmp_path)
    observed = []

    def engine(args, cwd, env):
        observed.append((env["SKILL_EVAL_LLM_MODEL"], env["SKILL_EVAL_LLM_API_KEY"]))
        assert [args[args.index("--" + k) + 1] for k in ("env-mode", "metric", "n-attempts")] == [
            "docker",
            "goal_accuracy",
            "1",
        ]
        assert not {"--model", "--agents", "--n-concurrent", "--harbor-keep-jobs", "--environment-kwarg"}.intersection(
            args
        )
        native = Path(args[args.index("--results-dir") + 1]) / "interaction_example"
        native.mkdir(parents=True)
        (native / "interaction.json").write_text(
            json.dumps(
                {
                    "kind": "skill_interaction",
                    "status": "complete",
                    "agents": {"codex": {"classification": "additive", "interaction": 0, "status": "complete"}},
                }
            )
        )
        return 0

    monkeypatch.setattr(live_job, "invoke_engine", engine)
    with running(tmp_path / "volume") as base:
        settings = open_settings(page, base, private_remote)
        chat = page.get_by_role("region", name="Chat", exact=True)
        save_profile(chat, "https://chat.example/v1", "original", "old-key")
        page.goto(base + settings.removesuffix("/providers") + "/experiments")
        page.get_by_label("Selected skill folders").fill("skills/triage\nskills/audit")
        page.get_by_role("button", name="Run interaction").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("neutral")
        playwright.expect(page.get_by_text("additive", exact=False)).to_be_visible()
        prior = page.url
        page.goto(base + settings)
        save_profile(chat, "https://chat.example/v1", "replacement", "new-key")
        page.goto(prior)
        page.get_by_role("button", name="Rerun saved inputs").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("neutral")
        assert observed == [("original", "old-key")] * 2
        assert "old-key" not in page.content()
