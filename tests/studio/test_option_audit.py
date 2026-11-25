"""Verify the public report authors use to review each browser binding."""

import json
import subprocess
import sys


def test_golden_audit_includes_direct_workflows_aliases_and_partial_bindings():
    rows = json.loads(subprocess.check_output([sys.executable, "-m", "studio.option_audit"]))
    assert rows["ci init:min_score"]["status"] == "implemented"
    assert rows["ci init:min_score"]["evidence"].endswith("::test_review_checks_then_publish")
    # Inventory is driven by the shipped golden, including newly added CI flags.
    for key, row in rows.items():
        if key == "ci" or key.startswith("ci "):
            assert row["status"] == "implemented", key
    assert rows["ci init:runner"]["status"] == "implemented"
    assert rows["tier3 [workflow]:environment_kwarg"]["contract"]["opts"] == ["--ek", "--environment-kwarg"]
    assert rows["tier3 [workflow]:environment_kwarg"]["contract"]["multiple"]
    assert rows["tier3 evaluate:skill_path"]["contract"]["required"]
    assert "root:version" in rows and "ci demo" in rows
