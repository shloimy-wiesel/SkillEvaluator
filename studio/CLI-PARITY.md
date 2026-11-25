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

The [Tier 2 overlap guide](OVERLAP.md) describes the implemented direct
workflow, focused routes/aliases, catalog inputs, provider prerequisites
and report equivalents. Option-level evidence: `bindings/overlap.json`.

## Acceptance criteria for every row

- Map every parameter to a labelled control or a documented browser equivalent, including inherited defaults, paired switches, aliases, repeated values, positional arguments, file types, and backend constraints. File selectors refer to authorized project files or artifacts.
- Keep omitted values distinct from explicit defaults. Test omitted report format versus explicit `cli`; their artifact behavior differs. Validate mutually exclusive comparison arms and baseline reuse before launch.
- Map hidden compatibility routes and flags separately from recommended actions: root `evaluate` and `precommit-run`, legacy catalog/cache flags and direct Tier 3 autopilot. Internal pre-commit invocation belongs to repository automation, not a generic process launcher.
- Compare the effective arguments/options and observable outcome. A generated control alone is not coverage. Preserve gate failures, artifacts, exit status, and diagnostics; never log credentials.
- Replace terminal-specific interactions with working browser experiences: retained reports, interactive feedback, filters, and downloads. Record unavailable runtime prerequisites rather than marking the feature complete.
- Before claiming release parity, check the target installed distribution against the inventory and exercise representative operations. Keep the golden file as the single source rather than copying thousands of parameter records into Studio.
