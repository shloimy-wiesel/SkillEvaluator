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

The [evaluation assets workflow](ASSETS.md) maps the two starter generators and `tier3 validate-grader`, including the execution boundary for repository suites.

[Review a completed run](RUNS.md#review-a-completed-run) covers agent score
comparison, reports, Harbor trajectory inspection, dashboard filters and
multi-turn feedback. The run picker binds these readers to retained project
evidence. `studio/bindings/review.json` records the tested equivalents and
limitations for each command and its aliases.

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

Open **Repository CI** from a connected project. Quick setup writes a GitHub
Tier 1 checks-only caller. **Advanced CI setup** uses the installed CLI's
release descriptors, discovery, validation and workflow renderers. Choose the
scan roots, runner and model settings, review each file and download the plan.
Publishing re-renders it against the same revision and checks the remote tip.

| Selection | Result / prerequisite |
| --- | --- |
| GitHub Tier 1 | Pinned or stable checks. Advanced setup defaults to hosted reports; select checks for artifact-only evaluation. |
| GitHub or GitLab all tiers | Pinned checks and trusted PR/MR feedback linking retained CI artifacts. Configure provider secrets, protected environment and runner; commit native datasets for Tier 3. Benchmark publication is GitHub-only. |
| Preview | Shows generated files without writing to the remote or changing host settings. An existing custom GitLab root gets the CLI's manual merge instructions, not an automatic replacement. |
| Save | Commits the reviewed files to the open branch. This may start CI. Unlike local CLI save, hosted workflow publication requires live privacy/ownership preflight. |
| PR | Creates a setup branch and authenticated request. GitHub Tier 1 uses the wizard's admin checks and can provision Actions, Pages, the report history and deployment environment. Private Pages must already have verified private visibility. |
| Live status | CLI status reads the live default branch, host settings and latest run or pipeline. Configuration alone is not a verified scan. |
| Demo | On the current default branch, review a comment-only change to a tracked skill under the configured scan roots; create its PR/MR without switching your project. |

Tokens come from the saved project; grant the Git and API permissions needed
for the selected action. GitHub host operations require `gh` (included in the
Studio image); GitLab uses the configured installation root (including port and path prefix),
project CA and a **separate project API token** from GitLab access. Studio
uses `studio.gitlab.instance(workspace, project)` (#18): `root`, `namespace`,
`web_url` and project-bound `request(method, suffix, query=..., payload=...)`.
Live GitLab operations require that integration. No fallback to gitlab.com
or forwarding of Git credentials to an API. Pipeline/MR links use the
configured project and numeric host IDs. Private runners also need their own CA trust. GitLab
before 18.4 requires a project Reporter/read_api admission token. Provider
credentials and protected environments belong to the CI host. Studio neither
installs runner dependencies nor verifies model execution during setup.

For a candidate release, install an operator-reviewed CLI descriptor under
`$STUDIO_DATA_DIR/ci-releases/NAME.json` (letters, digits, hyphens or underscores;
16 KiB maximum). Authors choose the name, never a host path. Only literal
repository selectors and typed runner/model options are accepted. Studio reopens an existing all-tier setup or demo request only if its base,
branch tip and complete Git tree still match the reviewed change. A failed API request after a successful push leaves the
review branch available. Hosted configuration can also finish partially; the
wizard reports confirmed steps. No live hosted evaluation is claimed by the
fixture tests.

[Experiments](RUNS.md#experiments) maps selection, fixed-suite interactions
and external metrics to pinned jobs with native JSON exports. Interaction
backend kwargs and raw Harbor jobs remain unbound. The browser interaction
proof uses a fixture at the sandbox invocation boundary, not a paid live trial.

## Installation and changed-file checks

From **Project tools → Installation and changed files**, inspect the installed
CLI version and choose contextual help for a command or tier group. Help and
version come from the same Python environment that executes checks. Expand
**Diagnostic detail** for the runtime, folder and revision; each retained run
also has a detail panel. **Include redacted evaluator detail** enables the
engine's verbose logging level for a changed-file run. Only its effective level
and path/skill counts are retained there, never the process environment or raw
debug log.

Select one or more paths from the connected commit's diff against its first
parent (all paths for the initial commit). The hidden `precommit-run` equivalent
checks each affected skill once across the repository. Unrelated paths produce
no results and a successful exit. Quality uses the evaluator defaults unless
you change the threshold or select a tracked configuration (YAML/JSON, up to
1 MiB). Paths and config stay pinned on replay; linked inputs are unsupported.

Requires Git, the installed evaluator and Studio dependencies, and a connected
project; these three checks need no provider, credentials or external service.
The Chromium integration test uses only a local private HTTPS Git fixture and
compares the rendered report and exit code with the installed CLI on the same
files. Evidence for the 11 command/option rows: `bindings/installation.json`.
