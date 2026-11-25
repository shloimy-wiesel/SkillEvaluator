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

## Expert checks and validation

Expand **Expert checks and validation** in Evaluation runs. Pick quality,
rubric, security, PII, script lint, or harness compatibility to run that
command alone. **Tier 1 workflow** and **Tier 1 validate** use the respective
direct CLI entry points. **Validation pipeline** runs root `validate` on
the connected skill with explicit tiers `1` or `1,2`. Tier 1 gates; Tier 2
can be advisory or blocking. Fail-fast and continue-on-failure retain their
engine precedence. A blank check selection uses that command's own defaults
(notably, direct Tier 1 includes dependency auditing). An explicit skip is
reported by the evaluator, not simulated by removing a result.

Use **Load commit files** to load a different revision before choosing a
policy, quality configuration, scanner baseline or waiver. Choices are
regular Git blobs, YAML/JSON, at most 1 MiB, rechecked in the detached
worktree. The worker uses packaged harness profiles; it does not evaluate
custom profile expressions. Harness compatibility is advisory: JSON is a
separate opt-in export, and each selected harness can have a version.

Choose zero or more native reports. Omission preserves the CLI's default;
explicit `cli` only requests terminal presentation. The root command also
writes a benchmark card. GitHub annotations and CLI output appear under
**Evaluator output**. Native files are project/run-scoped attachments, not
inline HTML. The job captures structured findings even for terminal-only
runs without requesting extra native formats or running the check twice.

**Prerequisites.** Rubric, LLM security analysis and LLM verification need
a key-backed chat profile and the evaluator's `llm` extra. Direct Tier 1
also uses saved chat settings by default when configured. Tier 2 needs
`tier2` and both embeddings and chat profiles. The worker snapshots each
required role privately before queueing; reruns do not pick up later key,
endpoint or model changes. Each SDK transport uses verified TLS without
redirects. Ambient provider keys and AWS identity are not inherited.
The keyless worker can use installed scanners; managed downloads are disabled.
SkillSpector's separate model transport is not enabled with a chat snapshot.
Missing scanner evidence can make a run incomplete; a keyless security
scan is not a certification that every scanner passed.

### Boundary for root Tier 3 integration

Root `validate` with omitted tiers defaults to live evaluation for skills.
Studio therefore **requires** an explicit tier selection; it never silently
converts that default to a Tier 1 run. The root command's dataset preflight,
auto-generation and native Harbor launch currently operate on the target
tree directly. A standalone Tier 3 job ending in `Outcome` is not a
replacement for that stage: root validation needs its `ValidationResult`
objects, fresh output provenance, staged inputs, budgets and gate metadata
before `emit_reports`. To enable `1,3`, `1,2,3` and the unrestricted default,
integrate #8's sandbox staging and provider snapshot at that engine boundary
and verify fail-fast, advisory/blocking gates and combined exports.
Do not launch repository-authored environments in this worker.

Root catalog fan-out, forced non-skill content types, arbitrary source
labels and custom harness profiles are not supported by this skill-scoped
job. Select **Record the pinned revision** to stamp the actual SHA on the
benchmark. The option audit registers evidence for individually tested
bindings; the presence of a form is not a whole-command parity claim.

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
   one real `<native-run-id>/` directory. Ignore the `latest` alias. Use its
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
