"""Read terminal artifacts in a private, resource-limited reader process."""

import json
import re
import subprocess
import sys
from pathlib import Path


def retained_evidence(volume, project_id, runs, skill):
    """runs are (authorized Studio run ID, pinned SHA) or None, prior first."""
    if len(runs) != 2:
        raise ValueError("Invalid retained comparison selection")
    try:
        return retained_catalog(volume, project_id, runs, skill, action="pair")
    except (OSError, subprocess.SubprocessError, ValueError):
        return {
            "history": [[], []],
            "comparison": {
                "status": "unavailable",
                "reasons": ["Retained evidence could not be read within the inspection limits."],
            },
        }


def retained_catalog(volume, project_id, runs, skill, *, action, **options):
    """Inspect only the retained run IDs authorized by the project catalog."""
    if not re.fullmatch("[0-9a-f]{32}", project_id) or any(
        not re.fullmatch("[0-9a-f]{32}", run[0]) or not re.fullmatch("[0-9a-f]{40}(?:[0-9a-f]{24})?", run[1])
        for run in runs
        if run is not None
    ):
        raise ValueError("Invalid project catalog")
    result = subprocess.run(
        [sys.executable, "-I", str(Path(__file__).with_name("comparison_worker.py")), str(volume), project_id],
        input=json.dumps(dict(runs=runs, skill=skill, action=action, **options)),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
        env={"SKILLEVALUATOR_OUTPUT_PROVENANCE_KEY_FILE": str(volume / "tier3-output.key"), "LANG": "C.UTF-8"},
    )
    return json.loads(result.stdout)
