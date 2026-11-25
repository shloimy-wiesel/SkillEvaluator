"""Run the Studio option contract through the installed Click evaluator."""

import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from click.testing import CliRunner
from studio.expert_options import ExpertOptions
from studio.jobs import JobContext

from skillevaluator.cli import cli


@pytest.fixture
def evaluate(tmp_path):
    skill = tmp_path / "skills" / "sample"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Sample\n")
    counter = 0

    def run(action, **fields):
        nonlocal counter
        counter += 1
        output = tmp_path / f"reports-{counter}"
        ctx = JobContext(tmp_path, skill, "1" * 40, None, None, "project", "run", output)
        if action == "harness-check":
            output.mkdir()
            opts = ExpertOptions(action=action, write_json=True, **fields)
        else:
            opts = ExpertOptions(action=action, reports=("json",), **fields)
        result = CliRunner().invoke(cli, opts.arguments(ctx))
        files = list(output.glob("*.json"))
        assert len(files) == 1, (result.output, result.exception)
        return result.exit_code, json.loads(files[0].read_text())

    return run


def test_explicit_tiers_override_full_and_live_shortcuts(evaluate):
    _, report = evaluate(
        "validate", checks=("schema",), tiers="1", full=True, autopilot=True, agent_eval=True, dedup=True
    )
    assert "tier3" not in report
    assert not any("Deduplication" in r["validator"] for r in report["results"])
    _, report = evaluate("validate", checks=("schema",), agent_eval=False, dedup=False)
    assert "tier3" not in report
    assert not any("Deduplication" in r["validator"] for r in report["results"])


def test_managed_agent_harness_set_applies_packaged_rules(evaluate):
    _, report = evaluate("validate", tiers="1", checks=("harness",), harness_profiles="agent-clis")
    (rows,) = report["harness_compatibility"].values()
    assert {r["harness"] for r in rows} == {"claude-code", "opencode", "codex"}
    codex = next(r for r in rows if r["harness"] == "codex")
    assert codex["status"] == "not_loaded"
    assert "CX-DESC-MISSING" in str(codex["findings"])


WORKFLOWS = ("validate", "tier1", "tier1-validate")


def workflow(action, *checks):
    return {"checks": checks, **({"tiers": "1"} if action == "validate" else {"llm": False})}


def manifest(tmp_path):
    target = tmp_path / "skills/sample/SKILL.md"
    target.write_text(
        "---\nname: sample\ndescription: Summarize short notes into action items.\n"
        "metadata:\n  version: 1.2.3\n---\n# Sample\n\n## Instructions\nRead the note and list actions.\n"
    )


@pytest.mark.parametrize("action", (*WORKFLOWS, "quality-check", "tier1-quality-check"))
def test_threshold_changes_gate_and_selected_config_changes_scoring(evaluate, tmp_path, action):
    manifest(tmp_path)
    (tmp_path / "quality.yaml").write_text(
        'expected_headers:\n  - heading: "## Aftercare"\n    points: 7.5\n'
        "    message: Include aftercare instructions\n    suggestion: Describe aftercare\n"
    )
    opts = workflow(action, "quality") if action in WORKFLOWS else {}
    for threshold, expected in [(0, 0), (100, 1)]:
        code, report = evaluate(action, **opts, min_score=threshold, quality_config="quality.yaml")
        assert code == expected
        (result,) = report["results"]
        finding = next(f for f in result["findings"] if f["message"] == "Include aftercare instructions")
        assert finding["metadata"]["deduction"] == 7.5


@pytest.mark.parametrize("action", WORKFLOWS)
def test_previous_release_and_skip_change_version_gate(evaluate, tmp_path, action):
    manifest(tmp_path)
    opts = workflow(action, "version", "unicode")
    assert evaluate(action, **opts, previous_version="1.2.2")[0] == 0
    code, report = evaluate(action, **opts, previous_version="1.2.3")
    assert code == 1 and "version_monotonic" in str(report)
    code, report = evaluate(action, **opts, previous_version="1.2.3", skip=("version",))
    assert code == 0
    assert any(r["status"] == "skipped" and "Version" in r["validator"] for r in report["results"])
    if action != "validate":
        assert "--no-llm" in report["workflow"]["stages"]["llm"]["reason"]


@pytest.mark.parametrize("action", (*WORKFLOWS, "pii-scan", "tier1-pii-scan"))
def test_reviewed_waiver_suppresses_only_matching_evidence(evaluate, tmp_path, action):
    from skillevaluator.validators.pii_waivers import pii_evidence_sha256, today_utc

    contact = tmp_path / "skills/sample/contact.md"
    address = "boss@company.com"
    contact.write_text(address + "\n")
    waiver = {
        "id": "approved-contact",
        "file": "skills/sample/contact.md",
        "line": 1,
        "category": "emails",
        "evidence_sha256": pii_evidence_sha256("emails", address),
        "owner": "docs",
        "reason": "Published support address",
        "created": today_utc().isoformat(),
        "expires": (today_utc() + timedelta(days=30)).isoformat(),
    }
    (tmp_path / "approved.json").write_text(json.dumps({"version": 1, "waivers": [waiver]}))
    opts = workflow(action, "pii") if action in WORKFLOWS else {}
    _, report = evaluate(action, pii_waivers="approved.json", **opts)
    findings = report["results"][0]["findings"]
    assert any(
        f["check_name"] == "applied-pii-waiver" and f["metadata"]["waiver_id"] == "approved-contact" for f in findings
    )
    contact.write_text("other@company.com\n")
    _, report = evaluate(action, pii_waivers="approved.json", **opts)
    assert any(f["category"] == "PII" for f in report["results"][0]["findings"])


def test_continue_overrides_fail_fast(evaluate):
    opts = {"tiers": "1", "checks": ("schema", "unicode"), "fail_fast": True}
    stopped, report = evaluate("validate", **opts)
    assert stopped == 1 and len(report["results"]) == 1
    continued, report = evaluate("validate", **opts, continue_on_failure=True)
    assert continued == 1 and any("Unicode" in r["validator"] for r in report["results"])


def test_native_evidence_records_only_canonical_source_labels(evaluate):
    from pydantic import ValidationError

    image = "ghcr.io/team/evaluator@sha256:" + "a" * 64
    opts = {"tiers": "1", "checks": ("unicode",), "include_revision": True}
    _, report = evaluate(
        "validate", **opts, evaluated_source_repository="team/notes", evaluator_container_revision=image
    )
    assert report["evaluated_source"] == {
        "repository": "team/notes",
        "commit": "1" * 40,
        "evaluator_container_revision": image,
    }
    with pytest.raises(ValidationError):
        evaluate("validate", **opts, evaluated_source_repository="https://user:secret@example.org/notes")


@pytest.mark.parametrize("action", WORKFLOWS)
def test_overlay_changes_registry_identity_requirement(evaluate, tmp_path, action):
    manifest(tmp_path)
    opts = workflow(action, "schema")
    _, report = evaluate(action, **opts, profile="registry")
    assert any(f["check_name"] == "metadata_id_missing" for f in report["results"][0]["findings"])
    (tmp_path / "team.yaml").write_text("identity:\n  metadata_id_requirement: ignore\n")
    _, report = evaluate(action, **opts, profile="registry", policy="team.yaml")
    assert not any(f["check_name"] == "metadata_id_missing" for f in report["results"][0]["findings"])


def test_harness_model_and_invocation_change_loader_findings(evaluate, tmp_path):
    path = tmp_path / "skills/sample/SKILL.md"
    path.write_text("---\nname: sample\ndescription: Summarize notes\nallowed-tools: Read\n---\n" + "x" * 20_000)

    def findings(**settings):
        code, report = evaluate("harness-check", harness=("codex", "openclaw", "claude-code"), **settings)
        assert code == 0
        (rows,) = report["harness_compatibility"].values()
        return {f["id"] for row in rows for f in row["findings"]}

    base = findings()
    assert "OW-READ-BUDGET" in base and "CX-SHELL-READ" not in base
    assert "OW-READ-BUDGET" not in findings(context_tokens=150_000)
    assert "CX-SHELL-READ" in findings(custom_provider=True)
    assert "CX-SHELL-READ" not in findings(custom_provider=True, explicit_invocation=True)
    assert "CC-ALLOWED-TOOLS-HEADLESS" not in base and "CC-ALLOWED-TOOLS-HEADLESS" in findings(headless=True)
    assert "VERSION-UNVERIFIED" not in base and "VERSION-UNVERIFIED" in findings(harness_versions=("codex=0.1",))


SECURITY = (*WORKFLOWS, "security-scan", "tier1-security-scan")


def replay_scanner(monkeypatch, payload, *, baseline=False):
    from skillevaluator.utils.tool_runner import ToolResult, Tools

    def scan(args, **kwargs):
        body = {**payload, "skill": {**payload["skill"], "source": args[1]}}
        if baseline and "--baseline" in args:
            assert Path(args[args.index("--baseline") + 1]).read_text().startswith("version: 2")
            body.update(
                suppressed_count=1,
                suppressed=[{"id": "PE5", "severity": "HIGH", "suppressed": True, "suppression_reason": "Reviewed"}],
            )
            body["analysis_completeness"] = {
                **body["analysis_completeness"],
                "findings_before_filtering": 1,
                "findings_after_filtering": 1,
            }
        return ToolResult(True, json.dumps(body), "", 0)

    monkeypatch.setattr(
        Tools,
        "skillspector",
        Mock(
            is_available=True,
            version=payload["metadata"]["skillspector_version"],
            run=scan,
            resolution_source="fixture",
        ),
    )


@pytest.mark.parametrize("action", SECURITY)
def test_selected_baseline_changes_scanner_receipt(evaluate, tmp_path, monkeypatch, action):
    from tests.validators.test_security import _skillspector_json_report

    replay_scanner(monkeypatch, _skillspector_json_report(), baseline=True)
    (tmp_path / "baseline.yaml").write_text(
        "version: 2\nrules:\n  - id: PE5\n    path: SKILL.md\n    reason: Reviewed\n"
    )
    opts = workflow(action, "security") if action in WORKFLOWS else {}
    _, report = evaluate(action, **opts, skillspector_baseline="baseline.yaml")
    state = report["results"][0]["skillspector_baseline"]
    assert (state["status"], state["suppressed_by_severity"], state["suppressed_rule_ids"]) == (
        "applied",
        {"HIGH": 1},
        ["PE5"],
    )
    (tmp_path / "baseline.yaml").write_text('version: 2\nrules:\n  - id: "*"\n    reason: Too broad\n')
    code, report = evaluate(action, **opts, skillspector_baseline="baseline.yaml")
    assert code == 1 and report["results"][0]["skillspector_baseline"]["status"] == "not_applied"


@pytest.mark.parametrize("action", SECURITY)
def test_hook_review_is_bound_to_plugin_bytes(evaluate, tmp_path, monkeypatch, action):
    from tests.validators.test_skillspector_hook_surface import _REVIEW_REPORT, _report, _review_plugin, _review_waiver

    plugin = _review_plugin(tmp_path)
    (plugin / "SKILL.md").write_text("# Bundled\n")
    waiver = _review_waiver(plugin, tmp_path / "approval.json")
    replay_scanner(monkeypatch, _report(_REVIEW_REPORT))
    opts = workflow(action, "security") if action in WORKFLOWS else {}
    if action == "validate":
        opts["content_type"] = "plugin"
    _, report = evaluate(action, target=plugin.name, hook_waivers=waiver.name, **opts)
    assert "skillspector_hook_waiver_applied" in str(report["results"][0]["findings"])
    if action == "validate":
        code, broader = evaluate(action, target=plugin.name, catalog_root=".", hook_waivers=waiver.name, **opts)
        assert code == 1 and "require a scan of the complete plugin root" in str(broader["results"])
    (plugin / "hooks/count-builds.sh").write_text("# revised script\n")
    code, report = evaluate(action, target=plugin.name, hook_waivers=waiver.name, **opts)
    assert code == 1 and "skillspector_hook_waiver_applied" not in str(report["results"][0]["findings"])


@pytest.mark.parametrize("action", ["validate", "pii-scan", "tier1-pii-scan"])
def test_verifier_downgrades_reviewed_finding(evaluate, tmp_path, monkeypatch, action):
    import httpx

    from skillevaluator.embedded import chat_transport

    monkeypatch.setenv("SKILL_EVAL_LLM_PROVIDER", "openai")
    monkeypatch.setenv("SKILL_EVAL_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    (tmp_path / "skills/sample/contact.md").write_text("boss@company.com\n")
    opts = workflow(action, "pii") if action == "validate" else {}

    def judge(request):
        verdict = {"index": 0, "verdict": "false_positive", "confidence": "high", "rationale": "Documentation example."}
        return httpx.Response(
            200,
            json={
                "id": "fixture",
                "object": "chat.completion",
                "created": 0,
                "model": "fixture-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": json.dumps(verdict)},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(judge)) as client:
        token = chat_transport.set(client)
        try:
            _, report = evaluate(action, llm_verify=True, **opts)
        finally:
            chat_transport.reset(token)
    finding = next(f for f in report["results"][0]["findings"] if f["category"] == "PII")
    assert finding["severity"] == "info" and finding["metadata"]["llm_verdict"] == "false_positive"


def test_external_shortcut_has_default_policy_outcome(evaluate, tmp_path):
    manifest(tmp_path)
    opts = workflow("validate", "schema")
    for fields in ({"external": True}, {"profile": "external"}, {"profile": "default"}):
        _, report = evaluate("validate", **opts, **fields)
        assert report["policy"]["profile"] == "default"
        assert "metadata_id_missing" not in str(report["results"])
    strict, report = evaluate("validate", **opts, profile="registry")
    assert strict == 1 and "metadata_id_missing" in str(report["results"])


@pytest.mark.parametrize(
    "kind,filename,expected",
    [
        ("rules", "sample.mdc", "Rules"),
        ("workflows", "workflow-rules.mdc", "Workflow"),
        ("plugin", "agent_plugin.yaml", "Plugin"),
    ],
)
def test_non_skill_target_runs_its_schema(evaluate, tmp_path, kind, filename, expected):
    folder = tmp_path / "artifact"
    folder.mkdir()
    (folder / filename).write_text("missing manifest fields\n")
    if kind != "plugin":
        # Auto would choose the SKILL.md, not the requested rules/workflow schema.
        (folder / "SKILL.md").write_text("# Unrelated skill\n")
    code, report = evaluate(
        "validate", target="artifact", content_type=kind, **workflow("validate", "schema", "quality")
    )
    assert code == 1
    assert any(expected in r["validator"] and r["status"] == "failed" for r in report["results"])
    assert not any("Quality" in r["validator"] and r["status"] == "passed" for r in report["results"])


@pytest.mark.parametrize("action", WORKFLOWS)
def test_report_selection_emits_requested_formats_for_same_failure(tmp_path, action):
    import xml.etree.ElementTree as ET

    skill = tmp_path / "sample"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# Missing frontmatter\n")
    output = tmp_path / "native"
    ctx = JobContext(tmp_path, skill, "a" * 40, None, None, "project", "run", output)
    options = ExpertOptions(
        action=action, **workflow(action, "schema"), reports=("github", "html", "json", "markdown", "junit", "sarif")
    )
    result = CliRunner().invoke(cli, options.arguments(ctx))
    assert result.exit_code == 1 and "::error" in result.output
    files = [p for p in output.iterdir() if p.name != "BENCHMARK.md"]
    assert len(files) == 5

    def read(suffix):
        return next(p.read_text() for p in files if p.name.endswith(suffix))

    assert "SKILL.md must have YAML frontmatter" in read(".md")
    assert "SKILL.md must have YAML frontmatter" in read(".html")
    assert json.loads(read(".sarif.json"))["runs"][0]["results"]
    assert ET.fromstring(read(".junit.xml")).find(".//failure") is not None


@pytest.mark.parametrize(
    "action",
    ["quality-check", "tier1-quality-check", "pii-scan", "tier1-pii-scan", "lint-scripts", "tier1-lint-scripts"],
)
def test_focused_collection_evaluates_both_selected_members(evaluate, tmp_path, action):
    for name in ("first-member", "second-member"):
        path = tmp_path / "collection" / name
        (path / "scripts").mkdir(parents=True)
        (path / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Help route requests.\n---\nWrite to boss@company.com\n"
        )
        (path / "scripts/invalid.py").write_text("def no_paren:\n")
    _, report = evaluate(action, target="collection")
    rows = str(report["results"])
    assert "first-member" in rows and "second-member" in rows
    assert "skills/sample" not in rows
