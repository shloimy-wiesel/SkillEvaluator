# Studio CLI parity inventory

The [machine-readable CLI surface](../tests/golden/cli_surface.json) is the option-level inventory. Read both `commands` and `workflow`: direct tier workflows have options of their own. This audit describes requirements at `ff69db2`, not implemented controls or verification against an installed wheel.

| Workspace action | CLI surface requiring a browser equivalent |
| --- | --- |
| Plan a run | Root `validate`, direct `tier1`, `tier2`, `tier3`, `tier1 validate`, `tier3 evaluate`. Preserve scope and gate settings. Direct Tier 3 can prepare a missing dataset. |
| Inspect skill quality | `quality-check`, `rubric-eval`, `security-scan`, `pii-scan`, `lint-scripts`, `harness-check` |
| Inspect overlap | `similarity-check`, `context-optimization-check`, `dedup-scan` |
| Manage cases | `create-eval-dataset`, `tier3 validate`, `tier3 migrate-dataset`, `tier3 import-traces`, `tier3 accept-traces` |
| Set up evaluation assets | `init-custom-grader`, `init-harbor-task`, `tier3 validate-grader` |
| Run experiments | `tier3 select-decoys`, `tier3 interact`, `tier3 import-metrics` |
| Understand results | `compare`, `view`, `harbor-view`, `dashboard`, `tier3 compare-versions`, `tier3 history`, `tier3 feedback` |
| Configure services | `doctor`, `health-check`, `tier3 doctor`, `models` |
| Configure repository automation | `ci init`, `ci status`, `ci demo` |
| Inspect the installation | Global verbosity, installed version, contextual help, command-local verbosity |

## Acceptance criteria for every row

- Map every parameter to a labelled control or a documented browser equivalent, including inherited defaults, paired switches, aliases, repeated values, positional arguments, file types, and backend constraints. File selectors refer to authorized project files or artifacts.
- Keep omitted values distinct from explicit defaults. Test omitted report format versus explicit `cli`; their artifact behavior differs. Validate mutually exclusive comparison arms and baseline reuse before launch.
- Map hidden compatibility routes and flags separately from recommended actions: root `evaluate` and `precommit-run`, legacy catalog/cache flags and direct Tier 3 autopilot. Internal pre-commit invocation belongs to repository automation, not a generic process launcher.
- Compare the effective arguments/options and observable outcome. A generated control alone is not coverage. Preserve gate failures, artifacts, exit status, and diagnostics; never log credentials.
- Replace terminal-specific interactions with working browser experiences: retained reports, interactive feedback, filters, and downloads. Record unavailable runtime prerequisites rather than marking the feature complete.
- Before claiming release parity, check the target installed distribution against the inventory and exercise representative operations. Keep the golden file as the single source rather than copying thousands of parameter records into Studio.

## Running and extending the option audit

Run `python -m studio.option_audit` from the checkout for a JSON report keyed by
command path and `:parameter_name`. `root` identifies global options;
`tier3 [workflow]` is distinct from the group and its subcommands. Rows include
aliases, paired switches and defaults directly from the golden. `remaining`
means **no registered proof**, even if another slice has work in progress.
`partial` means the explanation names a tested subset and the limitation.
`implemented` applies only to that binding, not the whole command or release.

For each slice, add a JSON list in `studio/bindings/<slice>.json` (see `ci.json`).
Each entry needs a unique `key`, `status`, `equivalent` and `evidence` pointing
to a top-level behavioral test (`tests/...py::test_name`). Exercise effective
options and outcomes including meaningful non-default choices before claiming
coverage. Register a command row separately. The audit rejects unknown or
duplicate bindings and dangling test references. Run the referenced tests:
audit success checks registration, not the behavior or adequacy of the test.
Run `pytest tests/golden/test_cli_surface.py tests/studio` to check CLI drift
and behavior together. An intentional golden change requires reviewing option
bindings before updating `surface_sha256` in `studio/cli-contract.json`.
No release/wheel-complete claim is made by this report.

## Repository CI journey

On a connected GitHub-compatible project, open **Repository CI**. Review a
new Tier 1 checks-only workflow for the selected branch and skill folder,
then publish the exact generated contents. The branch push can start CI.
Existing scans are preserved. Check status compares the remote tip to your
snapshot; a configured scan or publisher is not a passing run. Inspect run
results on the Git host. From the up-to-date default branch, review the demo
comment, publish the dedicated demo branch, and confirm the PR on the host.
The demo does not switch your active checkout. If that branch already exists,
inspect it on the Git host. All transport uses the saved project's Git access.

Remaining: multiple scan roots, hosted report and Pages configuration, setup
PR automation, live provider API results, automatic demo PR creation, GitLab
and all-tier routing/options. No custom release descriptors, host paths,
commands, or submitted YAML are accepted.
