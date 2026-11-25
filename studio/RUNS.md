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

## Expert checks and validation

Expand **Expert checks and validation** in Evaluation runs. Pick quality,
rubric, security, PII, script lint, or harness compatibility to run that
command alone. **Tier 1 workflow** and **Tier 1 validate** use the respective
direct CLI entry points. **Validation pipeline** runs root `validate` on
the connected skill with all three tiers by default. Select `1`, `1,2`, `1,3`,
or `1,2,3` to set the tier scope explicitly. Tier 1 gates; Tier 2 defaults to
blocking and Tier 3 to advisory. Fail-fast and continue-on-failure retain their
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
also uses saved chat settings by default when configured. Measured Tier 2
needs `tier2`, an embeddings profile, and chat for model-backed judging.
With no embeddings profile root validation records the native skip. The worker snapshots each
required role privately before queueing; reruns do not pick up later key,
endpoint or model changes. Each SDK transport uses verified TLS without
redirects. Ambient provider keys and AWS identity are not inherited.
The keyless worker can use installed scanners; managed downloads are disabled.
SkillSpector's separate model transport is not enabled with a chat snapshot.
Missing scanner evidence can make a run incomplete; a keyless security
scan is not a certification that every scanner passed.

### Running root validation with Tier 3

Start with **Checks to run → unicode** and no provider profiles to try the
whole pipeline without model charges. The root command prepares a deterministic
starter if needed. Its combined JSON, HTML and benchmark record execution and
gate decisions separately: an advisory skip is not a measured pass. Use
**Prepare missing dataset → No** to require committed cases, and **Tier 3
blocking gate → Yes** to include the live result in the exit gate.

For measured trials, build and configure the [live image and dedicated Docker
daemon](README.md#live-tier-3-image), set `STUDIO_LIVE_ENABLED=1`, and save a
key-backed chat profile reachable by both Studio and the trial containers.
The worker checks Harbor, Compose and the daemon first. Choose Kata only when
that daemon has a working Kata runtime. Configure embeddings separately for
Tier 2. Budget cases × agents × attempts × arms; a USD limit requires a
committed JSON price file and excludes judge and container costs.

All tiers evaluate one private copy of the pinned skill. The CLI prepares
cases before capturing source evidence. Reruns reuse a saved generated starter,
provider snapshots, SHA and options. Measured runs use generated Harbor tasks,
isolated skill workspaces and a fresh private results directory. Repo-defined
environments, native task bundles, committed `evals/results`, group workspaces
and setup commands are outside this preset. A sandbox preflight failure is
reported by root validation alongside earlier tiers. The native root reporters
write the requested formats and compulsory benchmark with the pinned revision;
partial arm evidence is retained when the engine can authenticate the run.

Root catalog fan-out, forced non-skill content types, arbitrary source
labels and custom harness profiles are not supported by this skill-scoped
job. For static-only runs select **Record the pinned revision** to stamp the actual SHA on the
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

## Review a completed run

Open **Results dashboard** from the project. Select one or several retained
runs, filter the performance rows, or switch to paired-arm comparisons. The
tables use the engine's dashboard reader for saved JSON reports. Choose
**Native retained measurements** for the retained agent configuration, costs,
times and token counts (16 MiB per native file, 64 MiB per run). Missing
measurements remain unavailable; comparison rows explain gaps in coverage.
To compare individual evaluator scores, open a run and choose **Compare
agents** for the CLI's score matrix over that run's retained summaries.

Choose **Review artifacts and feedback** to search the file list, preview
native HTML reports as text, or inspect JSON evidence (8 MiB per file).
**View report** rebuilds missing HTML from a temporary copy of the native
evidence, using the saved feedback without another judge call.
Turn on **Retain Harbor jobs** before launching a run to keep the raw job
trajectories as well as collected trials. Select a trajectory and filter its
steps by source. Only supported files from the selected run are indexed.

**Ask about this run** sends compact canonical evidence, saved feedback and
prior turns to the project's current key-backed chat profile. Completed turns
stay in the volume's SQLite history; reopening a conversation sends nothing
until you ask another question. Provider failures do not add a turn.

## Experiments

Open **Experiments** on the project. Each form queues a separate run at its
selected commit; reopen the result from **Evaluation runs → Run history**.
Successful experiment actions are **neutral**, not passing publication gates.

- **Select decoys** ranks a committed description-mode embedding catalog using
  the saved embedding profile. Enter the repository-relative catalog JSON and
  collection root (`.` for the repository), count (default four), and optionally
  one excluded catalog member per line and a matching embedding model. Use a
  collection at, above, or below the target's parent so the manifest is portable.
  Download the native JSON and review the selected paths, hashes and scores before
  using it as a decoy manifest. Selection does not run the trials or edit Git.
- **Run interaction** selects two to 32 project skill folders, in order, and one
  fixed evaluation source. Use the [live runtime](README.md#live-tier-3-image)
  and a key-backed chat profile. The engine runs baseline, each skill alone,
  and all together. Every configuration uses the same suite and fixed attempt
  count (default one). `overall` requires custom-only grading. A complete
  interaction can be positive, negative or zero; missing comparable evidence
  is incomplete, not zero. Studio uses the live generated-task input policy
  and supports Docker or Kata; backend kwargs, native environments, host
  execution and raw Harbor job retention are not supported.
- **Import observations** accepts the engine's external-metrics JSON contract
  at a pinned project path. The JSON and Markdown preserve declared provenance,
  matched coverage and custom scores. SkillEvaluator did not execute the tests,
  verify the producer, or assign a standard score or publication verdict.

In `artifacts/<project>/<run>/`, the native files are `decoys.json`,
`interactions/interaction_*/interaction.json` (alongside configuration evidence),
or `observations/external_metrics.{json,md}`. Rerun reuses the original Git
commit, options and encrypted provider snapshot. A provider call or sandbox
trial runs again and can incur charges; reopening an export does not.

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
