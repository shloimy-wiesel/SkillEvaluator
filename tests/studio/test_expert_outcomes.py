"""Run the Studio option contract through the installed Click evaluator."""

import json

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
        opts = ExpertOptions(action=action, reports=("json",), **fields)
        result = CliRunner().invoke(cli, opts.arguments(ctx))
        files = list(output.glob("*.json"))
        assert len(files) == 1, (result.output, result.exception)
        return result.exit_code, json.loads(files[0].read_text())

    return run


def test_explicit_tiers_override_full_and_live_shortcuts(evaluate):
    _, report = evaluate("validate", checks=("schema",), tiers="1", full=True, agent_eval=True, dedup=True)
    assert "tier3" not in report
    assert not any("Deduplication" in r["validator"] for r in report["results"])
    _, report = evaluate("validate", checks=("schema",), agent_eval=False, dedup=False)
    assert "tier3" not in report
    assert not any("Deduplication" in r["validator"] for r in report["results"])


def test_managed_agent_harness_set_applies_packaged_rules(evaluate):
    _, report = evaluate("validate", tiers="1", checks=("harness",), harness_profiles="agent-clis")
    rows, = report["harness_compatibility"].values()
    assert {r["harness"] for r in rows} == {"claude-code", "opencode", "codex"}
    codex = next(r for r in rows if r["harness"] == "codex")
    assert codex["status"] == "not_loaded"
    assert "CX-DESC-MISSING" in str(codex["findings"])
