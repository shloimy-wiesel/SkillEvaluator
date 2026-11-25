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

Draft snapshots support up to 4096 regular files / 64 MiB, with no symlinks
or submodules inside the selected skill. Generation and validation use a
separate interpreter; chat credentials are supplied only for model generation.
