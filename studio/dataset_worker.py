"""Private process boundary for engine calls with stdout and provider environment isolation."""

import json
import os
import sys
from contextlib import ExitStack, redirect_stdout
from functools import partial
from pathlib import Path

from skillevaluator.evaluation.results import DatasetGenerationError
from skillevaluator.tier3 import generate_dataset
from skillevaluator.tier3.dataset_coverage import dataset_coverage_result
from skillevaluator.tier3.evals_spec import validate_harbor_contract, validate_skillevaluators


def main(skill, action, options):
    if action == "validate":
        results = validate_skillevaluators(skill)
        from skillevaluator.tier3.dataset_utils import find_eval_file
        from skillevaluator.tier3.evals_spec import _validate_dataset_contents

        selected = skill / options["selected"]
        if selected.exists() and selected != find_eval_file(skill):
            _validate_dataset_contents(selected, results, skill_path=skill)
        if options["harbor_contract"]:
            results.extend(validate_harbor_contract(skill))
            from skillevaluator.tier3.evals_config import load_evals_config

            try:
                config, _ = load_evals_config(skill)
            except ValueError:
                config = {}  # validator already reported the invalid config
            if (
                config.get("harbor", {}).get("task_source") == "native_harbor"
                and config.get("grading", {}).get("mode") == "custom_only"
                and (skill / "evals/harbor").is_dir()
            ):
                results = [
                    r
                    for r in results
                    if not (r.path == "evals/evals.json" and "REQUIRED dataset file missing" in r.message)
                ]
        failures = {"error", "missing", "warning"} if options["strict"] else {"error", "missing"}
        checks = [vars(r) for r in results]
        coverage = dataset_coverage_result(skill)
        if coverage:
            checks.append(coverage)
        return {"passed": not any(r.status in failures for r in results), "checks": checks}
    # The generator constructs the public client internally. Bind its HTTP
    # transport in this single-use process, never in the shared web server.
    with ExitStack() as stack:
        if not options["no_llm"]:
            import httpx

            from skillevaluator.inference import client

            transport = stack.enter_context(
                httpx.Client(follow_redirects=False, trust_env=False, verify=os.getenv("SSL_CERT_FILE") or True)
            )
            client.LLMClient = partial(client.LLMClient, http_client=transport)
        with Path(os.devnull).open("w") as sink, redirect_stdout(sink):
            argv = [str(skill), "--dry-run"]
            for key, value in options.items():
                if value:
                    argv.append("--" + key.replace("_", "-"))
                    if value is not True:
                        argv.append(str(value))
            result = generate_dataset.main(argv)
    if result.status == "unchanged":
        raise ValueError("Dataset already exists. Select overwrite or refinement to generate a replacement.")
    return {"dataset": result.dataset}


if __name__ == "__main__":
    path, action = Path(sys.argv[1]), sys.argv[2]
    options = json.load(sys.stdin)
    for key in ("prompt", "from_results", "results_dir"):
        if key in options:
            options[key] = Path(options[key])
    try:
        response = main(path, action, options)
    except (DatasetGenerationError, ValueError) as exc:
        response = {
            "error": str(exc).replace(str(path), "skill")
            if options.get("no_llm")
            else "Engine could not prepare this preview. Check provider, grounding inputs and overwrite settings."
        }
    json.dump(response, sys.stdout)
