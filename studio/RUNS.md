# Evaluation runs

Open **Evaluation runs** on a project. The form starts with the project's
current full commit SHA; an older commit already in the project clone works
too. Queue the checks, then close the tab if desired. Follow the SHA in run
history to see progress, the frozen inputs, gate exit code, findings, and
downloadable engine JSON and Markdown. A failing gate still produces reports.

**Scope:** this keyless Tier 1 preset runs the shipped schema and Unicode
checks, together or individually, with the built-in `default` profile and
`--no-llm`. Passing certifies only the selected checks, not a complete Tier 1
publication assessment. The CLI retains its own defaults. The worker uses
an isolated Python interpreter, a minimal environment, a 180-second timeout
and a 768 MiB address-space limit. Repository scripts, external scanners,
custom policies, plugins, shell commands and host files are not inputs.

## Lifecycle and storage

Use one ASGI process per volume. A single background worker consumes queued
runs in submission order. Each gets an opaque ID and a local
`refs/studio/runs/<id>` pin so that a branch move or garbage collection
does not lose the input. The worker makes a separate detached Git worktree,
checks the selected folder and manifest, and removes the worktree when done.
It refuses linked skill inputs, links escaping the repository, and submodules
in the selected skill. Run checkouts are limited to 100,000 tree entries,
64 MiB per blob, and 512 MiB of blobs in total.

`studio.sqlite3` holds project-scoped run records, including creation time
(UTC), SHA, folder, kind, non-secret effective options, status and progress.
Terminal evaluation status, exit code and both exports are committed together.
`failed` is a gate result; `error` means the adapter could not deliver a
result. Adapters can report `incomplete`, `skipped`, `neutral` or `not_run`
without synthesizing measurements. On startup any `queued` or `running`
records become `interrupted`. No work is replayed. **Rerun saved inputs**
explicitly creates another ID with the original SHA, folder and options.
The earlier record is unchanged.

## Adding a typed evaluator

1. Define a frozen Pydantic model of effective, non-secret settings with
   `extra="forbid"`. Use enums, validated numeric bounds, project-relative
   dataset selections and stable provider configuration IDs. Freeze model,
   endpoint and dataset identity before enqueueing. If other inputs live
   outside this Git commit, use immutable references or retained snapshots.
   Never serialize a credential, argv, executable config or host path.
2. Define `evaluate(ctx: JobContext, options: YourOptions) -> Outcome`.
   Construct `JobDefinition("stable-kind-v1", YourOptions, evaluate)` and
   register the object in `studio.extensions.JOB_DEFINITIONS`. For tests,
   inject definitions via `create_app(..., job_definitions=(definition,))`.
   Use a new kind for incompatible behavior; keep old definitions registered
   while old runs must remain rerunnable.
3. After validating a feature-specific form, call
   `request.app.state.jobs.enqueue(project, full_sha, definition, options)`.
   Redirect to the named `run_detail` route with `project_id` and returned
   `run_id`. `history(project_id)`, `get(project_id, run_id)` and
   `rerun(project, run_id)` are the project-scoped read/replay interfaces.
   `history` is newest first; `get` returns a SQLite row or `None`.

`ctx.root` and `ctx.skill` belong only to this run; `ctx.revision` is its
exact commit. Use `ctx.input_file(relative)` for a regular, non-linked file
inside the detached repository, then validate its type and contents.
`ctx.workspace` and `ctx.project_id` allow trusted adapters to resolve saved
provider settings at execution time. Never mutate process-wide environment
or run untrusted repository code in the Studio process. Put optional native
evidence under `ctx.artifacts`, a private retained directory at
`artifacts/<project_id>/<run_id>/`. It is not statically served. Files there
may be partial after interruption; only the terminal record confirms results.

Call `ctx.progress("Checking …")` with safe, author-facing phase names.
Return `Outcome(status, exit_code, report, markdown)` with the actual gate
exit code and rendered strings. `report` is engine JSON with a `results`
array; use an empty array for a non-evaluation action. The UI escapes report
text. Redact sensitive provider output before returning or retaining it.
Raise `WorkspaceError` only for intentional, safe diagnostics. Other
exceptions become a generic execution error; raw stderr is not displayed.

## Live Tier 3

Open **Live Tier 3** from a project. Select a full commit, the dataset (blank
discovers the skill's conventional dataset at that commit), agent(s), grading
and comparison arms. Blank numeric fields preserve engine/config defaults;
zero is an explicit budget. A USD limit also needs a committed model price
JSON path. The chat profile selects the judge; the agent model override is
independent. Use a key-backed provider whose saved credential can serve every
selected agent; Studio does not borrow unrelated ambient keys.

**Evaluate** requires cases unless you explicitly enable autopilot. **Direct
Tier 3** runs the native workflow: preflight options and environment, then use
existing cases or prepare one starter. Generated cases are private run inputs;
they do not change Git. Rerun reuses the retained generated dataset once it is
available and always uses the original encrypted profile, commit and options.
Use a fresh submission to evaluate a new profile or generate a new starter.

The Harbor preset supports Docker and Kata (requires a configured Kata runtime),
isolated skill workspaces, standard and in-container custom grading, pinned
`evals/files` inputs, and safe declarative trial settings in `evals/config.yml`.
It does not accept host execution, repository-defined environments, arbitrary
setup commands, or native task bundles. A partial or unscored run is not a
measured failure. A neutral skill verdict can have CLI exit code zero.

### Finding evidence for comparison, feedback and experiments

1. Look up the Studio run with `jobs.get(project_id, run_id)`. Require
   `kind == "tier3-live-v1"` and a terminal row with `report` before using
   files. The Studio run ID and the native engine run ID are different.
2. Parse `row["report"]`: scored runs use `JSONReporter` and its canonical
   `tier3` payload, including the engine summary, agent/arm evidence and
   `evaluated_source.commit`. Missing measurements are absent. Preflight or
   incomplete outputs can have no canonical evaluation payload.
3. Under the private `artifacts/<project_id>/<run_id>/tier3/` root there is
   one real `<skill-name>/<native-run-id>/` directory (older adapters use
   `<native-run-id>/`). Use `studio.native_location.native_directory(root)`
   to resolve the native run in place; its generated marker binds it to its
   original path. Ignore the `latest` alias. Use its
   `result.json`, `run_config.json`, `<agent>/<arm>/summary.json`, engine
   feedback, report and dataset snapshot with the existing native readers.
   The selected/generated source dataset is also retained as `dataset.<ext>`
   beside `tier3/`. Use only authorized paths resolved under this run's root.
4. Compare actual dataset identities, agents/models, grading, arms, attempt
   policy, execution status and coverage from native evidence. The opaque
   `profile_id` is a private credential snapshot reference, not a benchmark
   dimension. The engine provenance key is `<volume>/tier3-output.key`; for
   a trusted offline reader use `SKILLEVALUATOR_OUTPUT_PROVENANCE_KEY_FILE`
   pointing to that file. Do not download it or copy it into trial containers.

See [the live image instructions](README.md#live-tier-3-image) to enable the
backend. A deterministic browser suite uses a fixture runner. With the Tier 3
extra and an accessible local Docker daemon, exercise the real authenticated
engine catalog and Docker preflight without a paid trial:

```sh
STUDIO_TEST_LIVE_RUNTIME=1 python -m pytest -q tests/studio/test_live.py
```

## Compare retained evidence

Open **Results → Compare revisions**. Choose the prior and current source.
Each side starts with the newest Studio run at that exact commit. When a
commit has multiple runs, choose the intended runs and select **Compare
selected runs**. The resulting URL pins both SHAs and Studio run IDs. Each
card links back to the original findings, settings and exports.

**Paired baseline lift** is the native history measurement for one agent
within one run (with skill versus without skill). **With-skill change** is
the native version comparison between runs (current minus prior). Its
eligibility and paired scores come from the same reader as `tier3
compare-versions`, including custom grading and unchanged skill identity.
Two passing gates alone do not establish a score change. Unknown coverage,
skipped arms, different settings and missing evidence stay visible.

Only terminal, project- and revision-matched live reports authorize native
artifact inspection. The isolated reader ignores `latest`, rejects linked
artifacts, and limits inspection to 16,000 entries, 8 MiB per JSON or marker
file and 64 MiB total of those files per run. Timeout: 30 seconds. No reader
starts trials or accesses provider credentials.
