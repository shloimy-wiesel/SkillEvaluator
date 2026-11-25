"""Read terminal artifacts in a private, resource-limited reader process."""

import json
import re
import subprocess
import sys
from pathlib import Path


def retained_evidence(volume, project_id, runs):
    """runs are (authorized Studio run ID, pinned SHA) or None, prior first."""
    if (
        not re.fullmatch("[0-9a-f]{32}", project_id)
        or len(runs) != 2
        or any(
            run
            and (not re.fullmatch("[0-9a-f]{32}", run[0]) or not re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", run[1]))
            for run in runs
        )
    ):
        raise ValueError("Invalid retained comparison selection")
    try:
        result = subprocess.run(
            [sys.executable, "-I", str(Path(__file__).with_name("comparison_worker.py")), str(volume), project_id],
            input=json.dumps(runs),
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
            env={"SKILLEVALUATOR_OUTPUT_PROVENANCE_KEY_FILE": str(volume / "tier3-output.key"), "LANG": "C.UTF-8"},
        )
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return {
            "history": [[], []],
            "comparison": {
                "status": "unavailable",
                "reasons": ["Retained evidence could not be read within the inspection limits."],
            },
        }
