import json
import os
import subprocess

import pytest
import yaml

# ruff: noqa: F811 -- pytest discovers shared browser fixtures by name
from test_workspace import before_push, connect, page, playwright, private_remote, running  # noqa: F401


def seed_skill(tmp_path, files):
    seed = tmp_path / "seed"
    for name, content in files.items():
        path = seed / "skills/triage" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    subprocess.run(["git", "add", "."], cwd=seed, check=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=t@example.org", "commit", "-m", "inputs"],
        cwd=seed,
        check=True,
    )
    subprocess.run(["git", "push", tmp_path / "server/handbook.git", "main"], cwd=seed, check=True)


def open_draft(page, base, private_remote):
    page.goto(base)
    connect(page, *private_remote, skill="skills/triage")
    page.get_by_role("link", name="Datasets").click()
    page.get_by_role("button", name="Open draft").click()
    page.wait_for_url("**/datasets?draft=*")


def publish(page):
    page.get_by_role("button", name="Commit and push").click()
    playwright.expect(page.get_by_role("status")).to_contain_text("Pushed")


def test_two_tabs_reconcile_pending_case_against_current_version(page, tmp_path, private_remote):
    case = {"id": "urgent", "prompt": "Route incident", "expected_output": "Tier one"}
    seed_skill(tmp_path, {"evals/evals.json": json.dumps({"skill_name": "triage", "evals": [case]})})
    with running(tmp_path / "volume") as base:
        open_draft(page, base, private_remote)
        other = page.context.browser.new_page()
        other.goto(page.url)
        for tab in (page, other):
            tab.get_by_text("Edit case urgent").click()
        other.locator("article").get_by_label("Expected output", exact=True).fill("Escalate to on-call")
        page.locator("article").get_by_label("Prompt", exact=True).fill("Route critical incident")
        page.get_by_role("button", name="Update case").click()
        playwright.expect(page.locator("article p").first).to_have_text("Route critical incident")
        other.get_by_role("button", name="Update case").click()
        playwright.expect(other.locator("main").get_by_role("alert")).to_contain_text("changed in another form")
        pending = other.get_by_role("region", name="Pending submission")
        playwright.expect(pending).to_contain_text("Escalate to on-call")
        playwright.expect(pending).to_contain_text("Current draft version: 1")
        playwright.expect(other.locator("article p").first).to_have_text("Route critical incident")
        current = other.locator("article").filter(has_text="urgent")
        playwright.expect(current.get_by_role("button", name="Update case", include_hidden=True)).to_be_disabled()
        other.get_by_role("button", name="Reconcile with current draft").click()
        current.get_by_text("Edit case urgent").click()
        playwright.expect(current.get_by_label("Expected output")).to_have_value("Tier one")
        current.get_by_label("Expected output").fill("Escalate to on-call")
        current.get_by_role("button", name="Update case").click()
        publish(other)
        blob = subprocess.check_output(
            ["git", "show", "main:skills/triage/evals/evals.json"], cwd=tmp_path / "server/handbook.git"
        )
        assert json.loads(blob)["evals"] == [
            {**case, "prompt": "Route critical incident", "expected_output": "Escalate to on-call"}
        ]


def test_resumed_draft_has_versioned_scoped_conflict_view(page, tmp_path, private_remote):
    with running(tmp_path / "volume") as base:
        open_draft(page, base, private_remote)
        endpoint = page.url.replace(base, base + "/api/v1", 1)
        response = page.request.get(endpoint)
        assert response.ok
        draft = response.json()["draft"]
        assert draft["path"] == "evals/evals.json"
        stale = page.request.post(endpoint, multipart={"draft": draft["token"], "version": "-1", "action": "delete"})
        assert stale.status == 409
        assert stale.json()["detail"]["code"] == "conflict"
        assert page.request.get(endpoint.split("?")[0] + "?draft=unknown").status == 404


@pytest.mark.parametrize(("padding", "limit"), [("é" * 17000, "32 KiB"), (["x"] * 1050, "2,000")])
def test_large_dataset_preview_preserves_full_commit(page, tmp_path, private_remote, padding, limit):
    document = {"skill_name": "triage", "evals": [], "padding": padding}
    seed_skill(tmp_path, {"evals/evals.json": json.dumps(document, ensure_ascii=False, indent=2)})
    with running(tmp_path / "volume") as base:
        open_draft(page, base, private_remote)
        page.get_by_text("Manage datasets").click()
        page.get_by_label("Skill identity", exact=True).fill("support")
        page.get_by_role("button", name="Update identity").click()
        page.get_by_role("button", name="Preview changes").click()
        preview = page.get_by_label("Change preview")
        playwright.expect(preview).to_contain_text("Diff omitted")
        assert limit in preview.inner_text()
        publish(page)
        blob = subprocess.check_output(
            ["git", "show", "main:skills/triage/evals/evals.json"], cwd=tmp_path / "server/handbook.git"
        )
        assert json.loads(blob) == {**document, "skill_name": "support"}


def test_edit_prompt_preserves_structured_expectations_and_conflicting_draft(page, tmp_path, private_remote):
    case = {
        "id": 37,
        "prompt": "Route incident",
        "expected_output": {"queue": "escalation", "priority": 2},
        "assertions": [{"field": "queue", "equals": "escalation"}],
        "metadata": {"labels": ["critical"]},
    }
    seed_skill(tmp_path, {"evals/evals.json": json.dumps({"skill_name": "triage", "evals": [case]})})
    with running(tmp_path / "volume") as base:
        open_draft(page, base, private_remote)
        other = page.context.browser.new_page()
        other.goto(page.url)
        other.get_by_text("Discard working copy").click()
        page.get_by_text("Edit case 37").click()
        edit = page.locator("article").filter(has=page.get_by_role("heading", name="37"))
        playwright.expect(edit.get_by_text("Structured assertions preserved")).to_be_visible()
        assert edit.get_by_label("Expected output").count() == 0
        edit.get_by_label("Prompt", exact=True).fill("Route critical incident")
        edit.get_by_role("button", name="Update case").click()
        playwright.expect(edit.locator("p").first).to_have_text("Route critical incident")
        other.get_by_role("button", name="Discard private draft").click()
        playwright.expect(other.locator("main").get_by_role("alert")).to_contain_text("changed in another form")
        playwright.expect(other.get_by_text("Route critical incident", exact=True).first).to_be_visible()
        publish(page)
        saved = subprocess.check_output(
            ["git", "show", "main:skills/triage/evals/evals.json"], cwd=tmp_path / "server/handbook.git"
        )
        assert json.loads(saved)["evals"] == [{**case, "prompt": "Route critical incident"}]


def test_guided_full_replacement_and_retained_refinement(page, tmp_path, private_remote):
    run = "history/triage/20260101_120000"
    original = json.dumps(
        {"skill_name": "triage", "evals": [{"id": "urgent", "prompt": "Route incident", "expected_output": "Tier two"}]}
    )
    seed_skill(
        tmp_path,
        {
            "evals/evals.json": original,
            "author.md": "## Negative Cases\n- What is the capital of Peru?\n",
            run + "/run_config.json": "{}",
            run + "/result.json": '{"run_id":"20260101_120000"}',
            run
            + "/codex/with-skill/trials/urgent/trajectory.json": '{"steps":[{"source":"agent","message":"Escalated"}]}',
            run
            + "/codex/with-skill/trials/triage-001/trajectory.json": '{"steps":[{"source":"agent","tool_calls":[{"function_name":"read_file","arguments":{"path":"incident.txt"}}]}]}',
        },
    )
    with running(tmp_path / "volume") as base:
        open_draft(page, base, private_remote)
        for field, path in (("Results root", "history"), ("Completed results folder", run)):
            page.get_by_text("Generate cases", exact=True).click()
            page.get_by_label("Grounding").select_option("skill" if field == "Results root" else "trace")
            page.get_by_label("Use local templates").check()
            page.get_by_label("Refine with retained trajectories").check()
            page.get_by_label(field).fill(path)
            page.get_by_role("button", name="Generate preview").click()
            page.get_by_text("All generated fields").click()
            result = json.loads(page.get_by_text("All generated fields").locator("..").locator("pre").inner_text())
            assert result["generation"]["refined"]
            if field == "Results root":
                assert "The agent read incident.txt" in result["evals"][0]["assertions"]
            else:
                assert result["evals"][0]["expected_output"] == "Tier two"
            assert next(i for i in result["generation"]["inputs"] if i["kind"] == "trajectory")["path"].startswith(run)
        for force in (False, True):
            page.get_by_text("Generate cases", exact=True).click()
            page.get_by_label("Use local templates").check()
            page.get_by_label("Generate full bucket set").check()
            page.get_by_label("Author guidance file").fill("author.md")
            page.get_by_label("Overwrite existing cases").set_checked(force)
            page.get_by_role("button", name="Generate preview").click()
            if not force:
                playwright.expect(page.locator("main").get_by_role("alert")).to_contain_text("already exists")
        playwright.expect(page.get_by_role("status")).to_contain_text("Generated 4")
        page.get_by_role("button", name="Use generated cases").click()
        publish(page)
        saved = json.loads(
            subprocess.check_output(
                ["git", "show", "main:skills/triage/evals/evals.json"], cwd=tmp_path / "server/handbook.git"
            )
        )
        assert saved["generation"]["grounding"] == "intent"
        assert any(i["path"] == "author.md" and i["kind"] == "prompt" for i in saved["generation"]["inputs"])
        assert any(c["prompt"] == "What is the capital of Peru?" for c in saved["evals"])
        assert "urgent" not in [c["id"] for c in saved["evals"]]


def test_harbor_contract_warning_changes_only_strict_verdict(page, tmp_path, private_remote):
    seed_skill(
        tmp_path,
        {
            "evals/evals.json": '{"skill_name":"triage","evals":[{"id":"one","prompt":"Route this","expected_output":"Queue"}]}',
            "evals/grader.py": "raise RuntimeError('must never execute')\n",
        },
    )
    with running(tmp_path / "volume") as base:
        open_draft(page, base, private_remote)
        for strict in (False, True):
            page.get_by_label("Check Harbor contract").check()
            page.get_by_label("Treat warnings as failures").set_checked(strict)
            page.get_by_role("button", name="Validate draft").click()
            results = page.get_by_label("Validation results")
            playwright.expect(results.get_by_role("heading")).to_have_text("Failed" if strict else "Passed")
            results.get_by_text("JSON results").click()
            checks = json.loads(results.locator("pre").inner_text())
            assert any(c["status"] == "warning" and "reward.json" in c["message"] for c in checks)


def test_collect_then_refine_only_the_pinned_case(page, tmp_path, private_remote, monkeypatch):
    from pathlib import Path

    from test_providers import open_settings, save_profile

    from studio import live_job

    repo = tmp_path / "seed"
    cases = repo / "skills/triage/evals/evals.json"
    cases.parent.mkdir()
    cases.write_text(
        json.dumps(
            {
                "skill_name": "triage",
                "evals": [{"id": "urgent", "prompt": "Route this incident", "expected_output": "Tier two escalation"}],
            }
        )
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=t@example.org", "commit", "-m", "cases"], cwd=repo, check=True
    )
    subprocess.run(["git", "push", tmp_path / "server/handbook.git", "main"], cwd=repo, check=True)
    calls = []

    def sandbox(args, cwd, env):
        calls.append(args)
        assert env["SKILL_EVAL_LLM_API_KEY"] == "collection-key"
        assert "--no-agent-runtime-preflight" in args
        assert "--skip-baseline" in args and args[args.index("--grading-mode") + 1] == "default"
        assert args[args.index("--skill-workspace-mode") + 1] == "isolated"
        assert (Path(args[2]) / "evals/evals.json").read_bytes() == cases.read_bytes()
        result = Path(args[args.index("--results-dir") + 1]) / "triage/20260101_120000"
        trial = result / "codex/with-skill/trials/urgent"
        trial.mkdir(parents=True)
        (trial.parent.parent / "summary.json").write_text(
            json.dumps(
                {
                    "execution_status": "succeeded",
                    "num_trials": 1,
                    "expected_attempts": 1,
                    "scored_attempts": 1,
                    "metrics": ["security"],
                    "scores": {"security": 1},
                }
            )
        )
        (trial / "trajectory.json").write_text(json.dumps({"steps": [{"source": "agent", "message": "Escalated."}]}))
        (result / "result.json").write_text('{"execution_status":"succeeded","verdict":"neutral"}')
        return 0

    monkeypatch.setattr(live_job, "invoke_engine", sandbox)
    with running(tmp_path / "volume") as base:
        settings = open_settings(page, base, private_remote)
        save_profile(
            page.get_by_role("region", name="Chat", exact=True), "https://chat.example/v1", "model", "collection-key"
        )
        page.goto(base + settings.removesuffix("/providers") + "/datasets")
        page.get_by_role("button", name="Open draft").click()
        page.wait_for_url("**/datasets?draft=*")
        draft = page.url
        page.get_by_role("button", name="Collect trajectory").click(timeout=1500)
        playwright.expect(page.locator("main").get_by_role("alert")).to_contain_text("consent")
        assert not calls
        page.get_by_label("Allow one paid sandbox trial").check()
        page.get_by_role("button", name="Collect trajectory").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("neutral", timeout=10000)
        page.goto(draft)
        page.get_by_role("button", name="Preview collected refinement").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("Generated 1")
        page.get_by_text("All generated fields").click()
        playwright.expect(page.locator("pre").filter(has_text='"refined": true')).to_contain_text("Tier two escalation")
        trials = next((tmp_path / "volume/artifacts").rglob("trials"))
        (trials / "urgent/foreign.log").symlink_to(cases)
        page.get_by_role("button", name="Preview collected refinement").click()
        playwright.expect(page.locator("main").get_by_role("alert")).to_contain_text("linked sandbox evidence")
        assert len(calls) == 1


def test_author_cases_and_publish_only_after_preview(page, tmp_path, private_remote):
    remote = tmp_path / "server/handbook.git"
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Datasets").click(timeout=1500)
        page.get_by_role("button", name="Open draft").click()
        page.get_by_label("Case ID").fill("first")
        page.get_by_label("Prompt", exact=True).fill("Classify the ticket")
        page.get_by_label("Expected output", exact=True).fill("An urgency level")
        page.get_by_label("Assertions").fill("Names the urgency\nExplains the evidence")
        page.get_by_role("button", name="Add case").click()
        playwright.expect(page.get_by_role("heading", name="first")).to_be_visible()
        page.get_by_role("button", name="Preview changes").click()
        playwright.expect(page.get_by_label("Change preview")).to_contain_text("+")
        assert subprocess.check_output(["git", "rev-list", "--count", "main"], cwd=remote).strip() == b"1"
        publish(page)
        saved = json.loads(subprocess.check_output(["git", "show", "main:skills/triage/evals/evals.json"], cwd=remote))
        assert saved["evals"] == [
            {
                "id": "first",
                "prompt": "Classify the ticket",
                "expected_output": "An urgency level",
                "assertions": ["Names the urgency", "Explains the evidence"],
            }
        ]


def test_generate_and_validate_local_draft(page, tmp_path, private_remote):
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Datasets").click()
        page.get_by_role("button", name="Open draft").click()
        page.get_by_text("Generate cases", exact=True).click(timeout=1500)
        page.get_by_label("Grounding").select_option("skill")
        page.get_by_label("Use local templates").check()
        page.get_by_role("button", name="Generate preview").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("Generated 1")
        page.get_by_role("button", name="Use generated cases").click()
        page.get_by_role("button", name="Validate draft").click()
        playwright.expect(page.get_by_label("Validation results")).to_contain_text("Dataset has 1 entry")


def test_review_export_before_publishing_redacted_fixtures(page, tmp_path, private_remote):
    remote = tmp_path / "server/handbook.git"
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Datasets").click()
        page.get_by_role("button", name="Open draft").click()
        page.get_by_text("Import traces", exact=True).click(timeout=1500)
        record = {
            "session_id": "one",
            "prompt": "Classify this incident",
            "outcome": "success",
            "final_output": "Priority two",
            "files": [{"path": "ticket.txt", "content": "person@real-domain.com"}],
        }
        page.get_by_label("Trace export").set_input_files(
            {
                "name": "export.jsonl",
                "mimeType": "application/json",
                "buffer": json.dumps(record).encode(),
            }
        )
        page.get_by_role("button", name="Import for review").click()
        page.get_by_label("Review decision").select_option("accept")
        page.get_by_label("Reviewer expectation").fill("Assigns severity two")
        page.get_by_role("button", name="Preview acceptance").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("1 addition")
        page.get_by_role("button", name="Stage accepted cases").click()
        publish(page)
        saved = json.loads(subprocess.check_output(["git", "show", "main:skills/triage/evals/evals.json"], cwd=remote))
        (case,) = saved["evals"]
        assert case["trace_source"]["decision"] == "accept"
        assert case["expected_output"] == "Assigns severity two"
        content = subprocess.check_output(["git", "show", "main:skills/triage/evals/" + case["files"][0]], cwd=remote)
        assert content and b"real-domain.com" not in content


def test_replace_trace_review_and_explicit_native_acceptance(page, tmp_path, private_remote):
    seed_skill(tmp_path, {"evals/config.yml": "schema_version: 1\nharbor:\n  task_source: native_harbor\n"})
    with running(tmp_path / "volume") as base:
        open_draft(page, base, private_remote)

        def upload(prompt, *, force=False, dry=False, outcome="success"):
            page.get_by_text("Import traces", exact=True).click()
            data = {"session_id": prompt, "prompt": prompt, "outcome": outcome, "final_output": "Queue two"}
            page.get_by_label("Trace export").set_input_files(
                {
                    "name": "export.jsonl",
                    "mimeType": "application/json",
                    "buffer": json.dumps(data).encode(),
                }
            )
            page.get_by_label("Dry run (preview only)").set_checked(dry)
            page.get_by_label("Replace existing review").set_checked(force)
            page.get_by_role("button", name="Import for review").click()

        upload("Original case")
        upload("Replacement")
        playwright.expect(page.locator("main").get_by_role("alert")).to_contain_text("already exists")
        upload("Replacement", force=True, dry=True)
        playwright.expect(page.get_by_label("Import preview")).to_contain_text("Replacement")
        playwright.expect(page.get_by_role("heading", name="Original case")).to_be_visible()
        upload("Failed case", force=True, outcome="failure")
        page.get_by_label("Review decision").select_option("accept_observed")
        page.get_by_label("Allow acceptance for native Harbor tasks").check()
        page.get_by_role("button", name="Stage accepted cases").click()
        playwright.expect(page.locator("main").get_by_role("alert")).to_contain_text("requires success")
        upload("Replacement", force=True)
        page.get_by_label("Review decision").select_option("accept_observed")
        page.get_by_role("button", name="Stage accepted cases").click()
        playwright.expect(page.locator("main").get_by_role("alert")).to_contain_text("allow-native-harbor")
        playwright.expect(page.get_by_label("Review decision")).to_have_value("pending")
        page.get_by_label("Review decision").select_option("accept_observed")
        page.get_by_label("Allow acceptance for native Harbor tasks").check()
        page.get_by_role("button", name="Stage accepted cases").click()
        publish(page)
        saved = json.loads(
            subprocess.check_output(
                ["git", "show", "main:skills/triage/evals/evals.json"], cwd=tmp_path / "server/handbook.git"
            )
        )
        (case,) = saved["evals"]
        assert (case["prompt"], case["expected_output"], case["trace_source"]["decision"]) == (
            "Replacement",
            "Queue two",
            "accept_observed",
        )


def test_create_named_dataset_then_edit_and_delete(page, tmp_path, private_remote):
    remote = tmp_path / "server/handbook.git"
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Datasets").click()
        page.get_by_role("button", name="Open draft").click()
        page.get_by_text("Manage datasets", exact=True).click(timeout=1500)
        page.get_by_label("New dataset name").fill("routing")
        page.get_by_role("button", name="Create dataset").click()
        page.get_by_label("Case ID").fill("one")
        page.get_by_label("Prompt", exact=True).fill("Route this task")
        page.get_by_label("Expected output", exact=True).fill("A route")
        page.get_by_label("Fixture selection").select_option("explicit")
        page.get_by_role("button", name="Add case").click()
        page.get_by_text("Edit case one", exact=True).click()
        page.get_by_label("Expected output", exact=True).first.fill("Route A")
        page.get_by_role("button", name="Update case").click()
        publish(page)
        path = "main:skills/triage/evals/datasets/routing.json"
        (case,) = json.loads(subprocess.check_output(["git", "show", path], cwd=remote))["evals"]
        assert case["files"] == [] and case["expected_output"] == "Route A"
        page.get_by_role("button", name="Open draft").click()
        page.get_by_text("Manage datasets", exact=True).click()
        page.get_by_label("Dataset file").select_option("evals/datasets/routing.json")
        page.get_by_role("button", name="Switch dataset").click()
        page.get_by_text("Delete dataset", exact=True).click()
        page.get_by_role("button", name="Stage dataset deletion").click()
        publish(page)
        assert subprocess.run(["git", "cat-file", "-e", path], cwd=remote).returncode != 0


@pytest.mark.parametrize("dest", ["evals/evals.json", "evals/datasets/dispatch.yaml"])
def test_migrate_legacy_then_review_routing_without_losing_authored_fields(page, tmp_path, private_remote, dest):
    from skillevaluator.tier3.dataset_utils import load_dataset_entries

    seed = tmp_path / "seed"
    remote = tmp_path / "server/handbook.git"
    source = seed / "skills/triage/eval/dataset.jsonl"
    source.parent.mkdir()
    source.write_text(
        json.dumps(
            {
                "id": 42,
                "question": "Identify routing",
                "ground_truth": "A route",
                "expected_skill": "triage",
                "metadata": {"origin": "maintainer"},
            }
        )
    )
    subprocess.run(["git", "add", "."], cwd=seed, check=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=t@example.org", "commit", "-m", "legacy"],
        cwd=seed,
        check=True,
    )
    subprocess.run(["git", "push", str(remote), "main"], cwd=seed, check=True)
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Datasets").click()
        page.get_by_role("button", name="Open draft").click()
        page.get_by_text("Migrate dataset", exact=True).click()
        page.get_by_label("Target skill identity").fill("dispatch")
        page.get_by_label("New destination").fill(dest)
        page.get_by_role("button", name="Run migration").click()
        page.get_by_text("Edit case 42", exact=True).click()
        page.get_by_label("Should this skill trigger?").first.select_option("no", timeout=1500)
        page.get_by_role("button", name="Update case").click()
        publish(page)
        path = tmp_path / dest.split("/")[-1]
        path.write_bytes(subprocess.check_output(["git", "show", f"main:skills/triage/{dest}"], cwd=remote))
        assert yaml.safe_load(path.read_bytes())["skill_name"] == "dispatch"
        (case,) = load_dataset_entries(path)
        assert case["should_trigger"] is False and case["id"] == 42 and "files" not in case
        assert case["metadata"] == {"origin": "maintainer"}
        assert (
            subprocess.check_output(["git", "show", "main:skills/triage/eval/dataset.jsonl"], cwd=remote)
            == source.read_bytes()
        )


def test_stale_publish_keeps_reviewable_draft_at_its_original_revision(page, tmp_path, private_remote):
    from test_editing import publish_from_seed

    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Datasets").click()
        page.get_by_role("button", name="Open draft").click()
        page.get_by_label("Case ID").fill("retained")
        page.get_by_label("Prompt", exact=True).fill("Classify incident")
        page.get_by_label("Expected output", exact=True).fill("Severity two")
        page.get_by_role("button", name="Add case").click()
        publish_from_seed(tmp_path, "main", "# Collaborator\n")
        with page.expect_response(lambda r: r.request.method == "POST" and r.status == 409):
            page.get_by_role("button", name="Commit and push").click()
        playwright.expect(page.locator("main").get_by_role("alert")).to_contain_text("remote branch changed")
        page.goto(page.url)
        playwright.expect(page.get_by_role("heading", name="retained")).to_be_visible(timeout=1500)


def test_invalid_case_keeps_author_input_for_correction(page, tmp_path, private_remote):
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Datasets").click()
        page.get_by_role("button", name="Open draft").click()
        page.get_by_label("Case ID").fill("bad/id")
        page.get_by_label("Prompt", exact=True).fill("A carefully authored question")
        page.get_by_label("Expected output", exact=True).fill("Expected response")
        page.get_by_role("button", name="Add case").click()
        playwright.expect(page.locator("main").get_by_role("alert")).to_contain_text("case id")
        playwright.expect(page.get_by_label("Prompt", exact=True)).to_have_value(
            "A carefully authored question", timeout=1500
        )


def test_model_preview_uses_only_saved_chat_credentials(page, tmp_path, private_remote, loopback_tls, monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    import pytest
    from test_providers import open_settings, save_profile

    pytest.importorskip("openai")
    calls = []
    candidate = {
        "id": "model-one",
        "question": "Which queue owns this ticket?",
        "expected_skill": "triage",
        "expected_script": None,
        "ground_truth": "Support queue",
        "expected_behavior": ["Names the queue"],
    }

    class Gateway(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["content-length"])))
            calls.append((self.path, self.headers["Authorization"], payload["model"]))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "choices": [
                            {
                                "finish_reason": "stop",
                                "index": 0,
                                "message": {"role": "assistant", "content": json.dumps([candidate])},
                            }
                        ]
                    }
                ).encode()
            )

    tls, ca = loopback_tls
    monkeypatch.setenv("SSL_CERT_FILE", os.path.relpath(ca))
    monkeypatch.setenv("OPENAI_API_KEY", "ambient")
    with ThreadingHTTPServer(("127.0.0.1", 0), Gateway) as server, running(tmp_path / "volume") as base:
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            settings = open_settings(page, base, private_remote)
            save_profile(
                page.get_by_role("region", name="Chat", exact=True),
                f"https://127.0.0.1:{server.server_port}/v1",
                "fixture-chat",
                "saved-chat",
            )
            page.goto(base + settings.rsplit("/", 1)[0])
            page.get_by_role("link", name="Datasets").click()
            page.get_by_role("button", name="Open draft").click()
            page.get_by_text("Generate cases", exact=True).click()
            page.get_by_label("Grounding").select_option("skill")
            page.get_by_role("button", name="Generate preview").click()
            playwright.expect(page.get_by_role("status")).to_contain_text("Mode: llm", timeout=2000)
            assert calls == [("/v1/chat/completions", "Bearer saved-chat", "fixture-chat")]
            playwright.expect(page.get_by_text(candidate["question"], exact=True)).to_be_visible()
        finally:
            server.shutdown()
            thread.join()
