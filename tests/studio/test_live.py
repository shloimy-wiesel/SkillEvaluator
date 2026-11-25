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
        from skillevaluator.tier3.results_location import resolve_results_root

        native = resolve_results_root(Path(args[1]), args[args.index("--results-dir") + 1]) / "20260101_120000"
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


@pytest.mark.parametrize("baseline_only", [False, True])
@pytest.mark.parametrize(
    "workflow,prefix", [("evaluate", ["tier3", "evaluate"]), ("alias", ["evaluate"]), ("direct", ["tier3"])]
)
def test_evaluate_selected_project_dataset_and_container_grader(
    page, private_remote, tmp_path, monkeypatch, workflow, prefix, baseline_only
):
    import json
    import subprocess
    from pathlib import Path

    from studio import live_job

    seed = tmp_path / "seed"
    (seed / "prices.json").write_text('{"price-marker":1}')
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

    # Exercise a namespace-bearing forge URL rather than inventing a repository label.
    (repo.parent / "team").mkdir()
    repo.rename(repo.parent / "team" / repo.name)
    image = "registry.example/studio@sha256:" + "d" * 64
    monkeypatch.setenv("STUDIO_EVALUATOR_CONTAINER_REVISION", image)

    def engine(args, cwd, env):
        from skillevaluator.cli import cli

        # Resolve the exact argv via the installed CLI, including TierGroup's
        # direct-path routing. Assert the typed policy at its public parser seam.
        tier = cli.commands["tier3"]
        command = {"direct": tier.workflow, "evaluate": tier.commands["evaluate"], "alias": cli.commands["evaluate"]}[
            workflow
        ]
        policy = {}
        with monkeypatch.context() as parser:
            parser.setattr(command, "callback", lambda **params: policy.update(params))
            cli.main(args=args, standalone_mode=False)
        for key, expected in {
            "env_mode": "kata",
            "backend": "harbor",
            "skill_workspace_mode": "isolated",
            "progress": "off",
            "n_attempts": 3,
            "n_concurrent": 2,
            "max_cases": 4,
            "max_agents": 2,
            "max_attempts_total": 12,
            "max_agent_tokens": 2000,
            "max_judge_calls": 0,
            "max_cost_usd": 0.25,
            "pass_threshold": 0.75,
            "timeout_multiplier": 1.5,
            "override_cpus": 2,
            "override_storage_mb": 4096,
            "override_memory_mb": 2048,
            "tolerate_baseline_timeouts": True,
            "stop_on_pass": False,
            "agent_runtime_preflight": True if baseline_only else None,
            "autopilot": workflow != "direct",
            "environment_kwarg": (),
            "custom_dockerfile_mode": None,
            "include_skills": (),
            "copy_repo": False,
            "harbor_keep_jobs": baseline_only,
            "progress_interval": None,
            "verbose": False,
            "skip_baseline": not baseline_only,
            "skip_with_skill": baseline_only,
            "model": "fallback",
            "agent_model": ("codex=gpt-trial", "opencode=openai/trial"),
            "evaluated_source_repository": "team/handbook",
            "evaluated_source_revision": sha,
            "evaluator_container_revision": image,
        }.items():
            assert policy[key] == expected, key
        assert policy["price_file"].read_text() == '{"price-marker":1}'

        assert args[: len(prefix)] == prefix
        skill = Path(args[len(prefix)])
        assert (skill / "evals/evals.json").read_bytes() == dataset.read_bytes()
        assert (skill / "evals/grader.py").is_file()
        assert args[args.index("--grading-mode") + 1] == "custom_only"
        assert args[args.index("--agents") + 1] == "codex,opencode"
        assert [args[i + 1] for i, flag in enumerate(args) if flag == "--agent-model"] == [
            "codex=gpt-trial",
            "opencode=openai/trial",
        ]
        assert ("--agent-runtime-preflight" in args) == baseline_only and "--no-agent-runtime-preflight" not in args
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
        settings = open_settings(
            page, base, (private_remote[0].replace("/handbook", "/team/handbook"), private_remote[1])
        )
        save_profile(
            page.get_by_role("region", name="Chat", exact=True), "https://chat.example/v1", "test", "private-key"
        )
        page.goto(base + settings.removesuffix("/providers") + "/live")
        sha = page.get_by_label("Commit SHA").input_value()
        for key, value in {
            "env_mode": "local",
            "backend": "nemo-gym",
            "environment_kwarg": "key=value",
            "custom_dockerfile_mode": "preserve",
            "skill_workspace_mode": "group",
            "include_skills": "../other",
            "copy_repo": "true",
            "results_dir": "/tmp/untrusted",
            "progress": "rich",
            "progress_interval": "1",
            "verbose": "true",
            "evaluator_revision": "forged",
        }.items():
            rejected = page.request.post(page.url, form={"sha": sha, "workflow": workflow, key: value})
            assert rejected.status == 422, key
        page.get_by_label("Workflow").select_option(workflow)
        page.get_by_label("Environment").select_option("kata")
        page.get_by_label("Comparison arms").select_option("baseline" if baseline_only else "skill")
        page.get_by_label("Dataset path").fill("bench.json")
        page.get_by_label("Grading mode").select_option("custom_only", timeout=2000)
        page.get_by_label("codex", exact=True).check()
        page.get_by_label("opencode", exact=True).check()
        page.get_by_text("Trial settings and budgets").click()
        page.get_by_label("Codex model override", exact=True).fill("gpt-trial")
        page.get_by_label("OpenCode model override", exact=True).fill("openai/trial", timeout=2000)
        for label, value in {
            "Attempts per case": "3",
            "Concurrent cases per agent": "2",
            "Maximum cases": "4",
            "Concurrent agents": "2",
            "Maximum total attempts": "12",
            "Maximum measured agent tokens": "2000",
            "Maximum judge calls": "0",
            "Maximum agent cost (USD)": "0.25",
            "Pass threshold": "0.75",
            "Timeout multiplier": "1.5",
            "CPUs per trial": "2",
            "Storage per trial (MiB)": "4096",
            "Memory per trial (MiB)": "2048",
            "Agent model override": "fallback",
        }.items():
            page.get_by_label(label, exact=True).fill(value)
        if workflow != "direct":
            page.get_by_label("Prepare missing dataset even with Evaluate").check()
        if baseline_only:
            page.get_by_label("Retain Harbor jobs").check()
            page.get_by_label("Run a paid agent preflight").select_option("true")
        page.get_by_label("Model price file").fill("prices.json")
        page.get_by_label("Tolerate baseline timeouts").select_option("true")
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


@pytest.mark.parametrize("workflow", ["direct", "evaluate", "alias"])
def test_project_retained_selection_and_provenance(page, private_remote, tmp_path, monkeypatch, workflow):
    import json
    import sqlite3
    from pathlib import Path

    from studio import live_job

    sources = []
    volume = tmp_path / "volume"

    def engine(args, cwd, env, *, retained=None):
        native = Path(args[args.index("--results-dir") + 1]) / "triage" / "20260101_120000"
        sha = args[args.index("--evaluated-source-revision") + 1]
        if sources:
            assert retained == {"reuse_baseline": sources[0], "compare_to": sources[0]}
            assert args[args.index("--reuse-baseline") + 1] == native.name
            assert args[args.index("--compare-to") + 1] == native.name
        sources.append(native)
        arm = native / "codex/with-skill"
        arm.mkdir(parents=True)
        (native / "run_config.json").write_text(json.dumps({"evaluated_source": {"commit": sha}}))
        (native / "result.json").write_text(
            json.dumps({"run_id": native.name, "execution_status": "succeeded", "verdict": "neutral"})
        )
        (arm / "summary.json").write_text(
            json.dumps(
                {"metrics": ["security"], "scores": {"security": 1.0}, "execution_status": "succeeded", "num_trials": 1}
            )
        )
        return 0

    monkeypatch.setattr(live_job, "invoke_engine", engine)
    with running(volume) as base:
        settings = open_settings(page, base, private_remote)
        save_profile(
            page.get_by_role("region", name="Chat", exact=True), "https://chat.example/v1", "judge", "private-key"
        )
        live = base + settings.removesuffix("/providers") + "/live"
        page.goto(live)
        page.get_by_label("Workflow").select_option(workflow)
        if workflow != "direct":
            page.get_by_text("Trial settings and budgets").click()
            page.get_by_label("Prepare missing dataset even with Evaluate").check()
        sha = page.get_by_label("Commit SHA").input_value()
        page.get_by_role("button", name="Queue live evaluation").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("neutral")
        prior = page.url.rsplit("/", 1)[1]
        page.goto(live)
        page.get_by_label("Reuse baseline from").select_option(prior, timeout=2000)
        page.get_by_label("Compare skill to").select_option(prior)
        page.get_by_label("Workflow").select_option(workflow)
        if workflow != "direct":
            page.get_by_text("Trial settings and budgets").click()
            page.get_by_label("Prepare missing dataset even with Evaluate").check()
        page.get_by_role("button", name="Queue live evaluation").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("neutral")
        assert len(sources) == 2
        # Replay must not label a changed worker image with the old run's revision.
        monkeypatch.setenv("STUDIO_EVALUATOR_CONTAINER_REVISION", "a" * 40)
        page.get_by_role("button", name="Rerun saved inputs").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("evaluator revision")
        monkeypatch.delenv("STUDIO_EVALUATOR_CONTAINER_REVISION")
        config = sources[0] / "run_config.json"
        original = config.read_bytes()
        config.write_text(json.dumps({"evaluated_source": {"commit": "0" * 40}}))
        response = page.request.post(live, form={"sha": sha, "reuse_baseline": prior})
        assert response.status == 422 and "provenance" in response.text()
        config.write_bytes(original)
        # Simulate a stopped worker with complete-looking files still on disk.
        with sqlite3.connect(volume / "studio.sqlite3") as db:
            db.execute("UPDATE runs SET status='interrupted' WHERE id=?", (prior,))
        response = page.request.post(live, form={"sha": sha, "reuse_baseline": prior})
        assert response.status == 422
        with sqlite3.connect(volume / "studio.sqlite3") as db:
            db.execute("UPDATE runs SET status='neutral', project_id='other-project' WHERE id=?", (prior,))
        response = page.request.post(live, form={"sha": sha, "compare_to": prior})
        assert response.status == 422 and len(sources) == 2
