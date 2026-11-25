# Author evaluation cases

Open **Datasets → Open draft** from a project. Studio copies the selected
skill’s committed regular files into a private working directory on the Studio
volume. Bookmark the draft URL to resume it. The branch and exact SHA stay
bound to the draft, even when a collaborator pushes. **Commit and push**
publishes all staged files together. **Discard private draft** removes the
working copy. Successful publication removes it too.

The active file initially follows the evaluator’s discovery order. Add cases
to create the default `evals/evals.json`, or use **Manage datasets** to create
and switch between named collections in `evals/datasets/`. Case edits preserve
extra fields and numeric IDs. Fixture selection distinguishes **inherit** (no
`files` field) from an explicit empty list. Use one relative path per line
for specific fixtures. Structured expected outputs and assertions are shown
read-only so editing a prompt cannot flatten them.

| Tool | Inputs and outputs |
| --- | --- |
| Validate draft | Runs the evaluator’s skill and dataset checks; optionally treats warnings as failures and includes Harbor contract checks. Shows outcomes and JSON. Also checks a selected named collection. |
| Migrate dataset | Select an existing JSON, JSONL or YAML dataset. Identity is inferred unless explicitly provided. Omit destination for preview; choose a **new** canonical or named JSON/YAML path to stage the conversion and keep the source. |
| Generate cases | Defaults to auto grounding, one case and the saved chat profile. Requires the worker’s corresponding optional model SDK (`skillevaluator[llm]`); templates are keyless. Select full buckets, overwrite, refinement, grounding, guidance and retained result inputs as needed. Paths are inside the private skill snapshot. Preview uses engine dry-run semantics. Inspect provenance, template fallback and generated fields before applying to `evals/evals.json`. |
| Collect a trajectory | Explicitly allow one paid sandbox trial for the **committed** dataset at the draft SHA. Uses the saved key-backed chat profile, one with-skill case/agent/attempt, standard grading and an isolated workspace. Requires the Studio live image (`STUDIO_LIVE_ENABLED=1`, Tier 3 extra, Docker CLI/Compose/daemon), a reachable agent-compatible provider and working agent images. A failed or disabled runtime cannot supply evidence. Reopen the same draft and choose **Preview collected refinement**: local templates refine matching cases without another agent or model call. Inspect the preview before staging it. |
| Import traces | Upload a JSON/JSONL export (up to 2 MiB). Review output is private to the draft. Dry run previews without replacing the review; force explicitly replaces an existing review. Inspect evidence, warnings, fixture names, suggestions, redactions and skipped records. |
| Accept traces | Leave candidates pending, reject, supply independent expectations and assertions, or explicitly accept successful observed output. Preview acceptance or stage accepted cases in `evals/evals.json` with their redacted fixtures. Native Harbor requires explicit opt-in. |

Collection previews accept at most 64 MiB of unlinked trial evidence. The
browser/adapter tests use a fixture trial and the real refinement engine.
`STUDIO_TEST_LIVE_RUNTIME=1` additionally checks Docker and authenticated
model discovery; it does not purchase a provider trial.

Draft snapshots support up to 4096 regular files / 64 MiB, with no symlinks
or submodules inside the selected skill. Generation and validation use a
separate interpreter; chat credentials are supplied only for model generation.

### HTTP contract

`/projects/{id}/datasets` serves the React document. Its JSON view lives at
`GET /api/v1/projects/{id}/datasets`, with the same `draft` or `pushed`
query. Submit actions to `POST` at that API path as multipart form data
(including `export` for trace uploads). `open` takes the project's branch
and revision. Subsequent actions take the private draft token and version.

An action returns the updated view or a same-origin `location` for a new
draft, collection run, discard or publication. A `409` includes the current
draft and `detail: {code, message}` so a stale tab can review the latest
state. The editor displays the submitted values alongside the current draft
version. Choose **Reconcile with current draft** to edit the current values;
Studio never replays a stale submission automatically. A validation failure
returns `422`; an unknown project or draft returns `404`.

Dataset previews omit the diff when the saved or draft
files exceed 32 KiB on either side, or both sides exceed 2,000 lines combined.
These limits apply only to the preview. **Commit and push** still publishes
the complete changes.

### Reproducing the React migration checks (#28)

Build the static export before running `python -m pytest -q
tests/studio/test_datasets.py`. The tests use real Chromium and a disposable
private HTTPS Git remote. On the pre-migration commit `8305e1b`,
`test_resumed_draft_has_versioned_scoped_conflict_view` opened the browser
draft but got `404` for its versioned view. It now checks the draft path,
the `409` stale-version envelope, and rejection of an unknown token.

The suite also reads back published blobs, drives two independent browser
pages against one draft, and checks redaction before fixture publication.
Model-generation coverage uses a test-local HTTPS OpenAI-compatible endpoint
and inspects its actual model and authorization header. Collection substitutes
a fixture sandbox invocation, then runs the real trajectory refinement.

For #33, `test_two_tabs_reconcile_pending_case_against_current_version`
failed on `fd7bdf4` because the second Chromium page lost its pending
expectation. It now checks that submission is disabled until reconciliation,
then reads the committed case from the private Git fixture to verify both
authors’ changes. `test_large_dataset_preview_preserves_full_commit` exercises
both byte and line limits; `test_large_asset_preview_still_publishes_complete_starter`
checks an oversized configuration and the generated executable mode. Before
the fix the preview assertions received full diffs instead of an omission.
