"""Studio Tier 3 author journeys."""

import os

import pytest
from test_providers import open_settings, save_profile
from test_workspace import connect, playwright, running

pytest_plugins = ("test_workspace", "test_providers")


def test_live_requires_project_chat_profile(page, private_remote, tmp_path):
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Live Tier 3").click(timeout=2000)
        page.get_by_role("button", name="Queue live evaluation").click()
        playwright.expect(page.get_by_role("alert")).to_contain_text("chat provider")


def test_direct_workflow_retains_evidence_and_reruns_original_profile(page, private_remote, tmp_path, monkeypatch):
    import json
    import subprocess
    from pathlib import Path

    from studio import live_job

    calls = []

    def engine(args, cwd, env):
        calls.append((args, env))
        assert args[:1] == ["tier3"] and "evaluate" not in args
        assert args[args.index("--n-attempts") + 1] == "3"
        assert args[args.index("--max-attempts-total") + 1] == "6"
        assert args[args.index("--env-mode") + 1] == "docker"
        assert env["SKILL_EVAL_LLM_API_KEY"] == "chat-secret"
        assert "GITHUB_TOKEN" not in env
        assert (Path(args[1]) / "SKILL.md").read_text() == "# Triage\n"
        from skillevaluator.utils.path_security import resolve_repo_context_root

        assert resolve_repo_context_root(Path(args[1])) == Path(args[1]).parent
        generated = Path(args[1]) / "evals/evals.json"
        if len(calls) == 1:
            assert not generated.exists()
            generated.write_text('{"skill_name":"triage","evals":[]}')
        else:
            assert generated.read_text() == '{"skill_name":"triage","evals":[]}'
        native = Path(args[args.index("--results-dir") + 1]) / "20260101_120000"
        native.mkdir(parents=True)
        native.with_name("latest").symlink_to(native.name)
        arm = native / "codex/with-skill"
        arm.mkdir(parents=True)
        (arm / "summary.json").write_text(
            json.dumps(
                {
                    "metrics": ["security"],
                    "scores": {"security": 1.0},
                    "execution_status": "succeeded",
                    "expected_attempts": 1,
                    "scored_attempts": 1,
                    "num_trials": 1,
                }
            )
        )
        (native / "result.json").write_text(json.dumps({"execution_status": "succeeded", "verdict": "neutral"}))
        (native / "tier3-benchmark.md").write_text("# No measured lift")
        return 0

    monkeypatch.setattr(live_job, "invoke_engine", engine)
    monkeypatch.setenv("GITHUB_TOKEN", "ambient-secret")
    # Local development may place STUDIO_DATA_DIR below an unrelated Git repository.
    subprocess.run(["git", "init", "-q", tmp_path / "volume"], check=True)
    with running(tmp_path / "volume") as base:
        settings = open_settings(page, base, private_remote)
        panel = page.get_by_role("region", name="Chat", exact=True)
        save_profile(panel, "https://chat.example/v1", "model-one", "chat-secret")
        page.goto(base + settings.removesuffix("/providers") + "/live")
        page.get_by_label("Workflow").select_option("direct")
        page.get_by_text("Trial settings and budgets").click()
        page.get_by_label("Attempts per case").fill("3")
        page.get_by_label("Maximum total attempts").fill("6")
        page.get_by_role("button", name="Queue live evaluation").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("neutral")
        report = page.request.get(page.get_by_role("link", name="Download JSON").get_attribute("href")).json()
        assert (
            report["tier3"]["evaluated_source"]["commit"]
            == calls[0][0][calls[0][0].index("--evaluated-source-revision") + 1]
        )
        assert (
            page.request.get(page.get_by_role("link", name="Download Markdown").get_attribute("href")).text()
            == "# No measured lift"
        )
        original = page.url
        page.goto(base + settings)
        save_profile(panel, "https://chat.example/v1", "model-two", "replacement")
        page.goto(original)
        page.get_by_role("button", name="Rerun saved inputs").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("neutral")
        assert len(calls) == 2
        assert "chat-secret" not in page.content()


def test_evaluate_selected_project_dataset_and_container_grader(page, private_remote, tmp_path, monkeypatch):
    import json
    import subprocess
    from pathlib import Path

    from studio import live_job

    seed = tmp_path / "seed"
    dataset = seed / "bench.json"
    dataset.write_text('{"skill_name":"triage","evals":[]}')
    graders = seed / "skills/triage/evals"
    graders.mkdir()
    (graders / "grader.py").write_text("raise RuntimeError('never import a grader into Studio')")
    repo = tmp_path / "server/handbook.git"
    subprocess.run(["git", "add", "."], cwd=seed, check=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=t@example.org", "commit", "-m", "cases"], cwd=seed, check=True
    )
    subprocess.run(["git", "push", repo, "main"], cwd=seed, check=True)
    subprocess.run(["git", "update-server-info"], cwd=repo, check=True)

    def engine(args, cwd, env):
        assert args[:2] == ["tier3", "evaluate"] and "--autopilot" not in args
        skill = Path(args[2])
        assert (skill / "evals/evals.json").read_bytes() == dataset.read_bytes()
        assert (skill / "evals/grader.py").is_file()
        assert args[args.index("--grading-mode") + 1] == "custom_only"
        assert args[args.index("--agents") + 1] == "opencode"
        assert args[args.index("--agent-model") + 1] == "opencode=openai/trial"
        assert args[args.index("--override-memory-mb") + 1] == "2048"
        assert "--no-stop-on-pass" in args
        native = Path(args[args.index("--results-dir") + 1]) / "20260101_130000"
        native.mkdir(parents=True)
        (native / "result.json").write_text(
            json.dumps(
                {"execution_status": "failed", "execution_errors": ["agent unavailable", env["SKILL_EVAL_LLM_API_KEY"]]}
            )
        )
        return 1

    monkeypatch.setattr(live_job, "invoke_engine", engine)
    with running(tmp_path / "volume") as base:
        settings = open_settings(page, base, private_remote)
        save_profile(
            page.get_by_role("region", name="Chat", exact=True), "https://chat.example/v1", "test", "private-key"
        )
        page.goto(base + settings.removesuffix("/providers") + "/live")
        page.get_by_label("Dataset path").fill("bench.json")
        page.get_by_label("Grading mode").select_option("custom_only", timeout=2000)
        page.get_by_role("button", name="Queue live evaluation").click()
        playwright.expect(page.get_by_role("alert")).to_contain_text("consent")
        page.get_by_label("Dataset path").fill("bench.json")
        page.get_by_label("Grading mode").select_option("custom_only")
        page.get_by_label("Allow the repository grader in the sandbox").check()
        page.get_by_label("opencode", exact=True).check()
        page.get_by_text("Trial settings and budgets").click()
        page.get_by_label("OpenCode model override", exact=True).fill("openai/trial", timeout=2000)
        page.get_by_label("Memory per trial (MiB)").fill("2048")
        page.get_by_label("Stop remaining attempts after a pass").select_option("false")
        page.get_by_role("button", name="Queue live evaluation").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("incomplete")
        playwright.expect(page.get_by_text("agent unavailable", exact=True)).to_be_visible()
        assert "private-key" not in page.content()
        assert "private-key" not in next((tmp_path / "volume/artifacts").rglob("result.json")).read_text()


@pytest.mark.skipif(os.getenv("STUDIO_TEST_LIVE_RUNTIME") != "1", reason="requires Harbor and a Docker daemon")
def test_real_engine_docker_and_authenticated_catalog_preflight(tmp_path, gateway, monkeypatch):
    import sys
    from pathlib import Path

    from studio.live_job import invoke_engine

    endpoint, calls = gateway
    monkeypatch.setenv("STUDIO_LIVE_ENABLED", "1")
    env = {
        "HOME": str(tmp_path),
        "PATH": f"{Path(sys.executable).parent}:/usr/local/bin:/usr/bin:/bin",
        "SSL_CERT_FILE": os.environ["SSL_CERT_FILE"],
        "SKILL_EVAL_LLM_PROVIDER": "openai-compatible",
        "SKILL_EVAL_LLM_BASE_URL": endpoint + "/v1",
        "SKILL_EVAL_LLM_API_KEY": "chat-secret",
        "SKILL_EVAL_LLM_MODEL": "private-chat",
    }
    code = invoke_engine(
        [
            "tier3",
            "doctor",
            "--env-mode",
            "docker",
            "--verify-models",
            "--agents",
            "codex",
            "--agent-model",
            "codex=private-chat",
        ],
        tmp_path,
        env,
    )
    assert calls and calls[0] == ("/v1/models", "Bearer chat-secret")
    assert code == 0
