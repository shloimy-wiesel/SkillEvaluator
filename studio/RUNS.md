# Evaluation runs

For model-backed Tier 2 runs, see [Evaluate overlap](OVERLAP.md).

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
