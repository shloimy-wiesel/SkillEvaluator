"""Private isolated interpreter entry point (no Python imports from the checkout)."""

import json
import resource
import sys
from pathlib import Path

from skillevaluator.constants import QUALITY_DEFAULT_MIN_SCORE
from skillevaluator.reporting.json_reporter import JSONReporter
from skillevaluator.reporting.markdown import MarkdownReporter
from skillevaluator.reporting.run_status import resolve_run_status
from skillevaluator.tier_workflows import run_tier1_workflow
from skillevaluator.validators.policy import load_profile


def main():
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024**2, 768 * 1024**2))
    skill = Path(sys.argv[1])
    options = json.loads(sys.argv[2])
    results = run_tier1_workflow(
        skill,
        checks=",".join(options["checks"]),
        llm=False,
        min_score=QUALITY_DEFAULT_MIN_SCORE,
        quality_config=None,
        profile=load_profile(options["profile"]),
        previous_version=None,
    )
    status = resolve_run_status(results)
    json.dump(
        {
            "status": status.tiers[1].status.value,
            "exit_code": int(status.headline.value != "passed"),
            "report": JSONReporter(explicit_skill_name=skill.name).render_all(results),
            "markdown": MarkdownReporter().render_all(results),
        },
        sys.stdout,
    )


if __name__ == "__main__":
    main()
