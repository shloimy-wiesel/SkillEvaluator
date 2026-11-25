# Set up evaluation assets

Open **Evaluation assets** on the project branch. Choose **Custom grader** or **Native Harbor task**, then **Preview**. Review additions, replacements, deletions and executable modes before **Commit and push** publishes one commit. A stale preview cannot overwrite a moved branch. Use **Edit skill** to open or create a different branch first.

The forms run the CLI's starter generators on a temporary copy of the committed skill manifest and `evals/` blobs. Neither preview nor push executes the generated graders, test scripts, or Dockerfiles. Studio accepts up to 16 MiB / 1024 regular files in `evals/`. An existing starter requires explicit overwrite. Force can remove the old grader language or replace an entire native case; review the deletions.

| Action | CLI equivalent and defaults |
| --- | --- |
| Custom grader | `init-custom-grader` (also under `tier3`). Skill = project folder. Python, `default_plus_custom`, no force. Clearing **Update evaluation configuration** sets `--no-config`. |
| Native Harbor task | `init-harbor-task` (also under `tier3`). Python, `case-001`, `custom_only`, no force. Selecting **Update evaluation configuration** sets `--with-config`. Mode controls use canonical labels for `aces_default` / `aces_plus_custom`. |
| Check suite | `tier3 validate-grader --check-suite`. Bundled suite by default, or a committed `suite.json` under the selected skill. Verifies the engine's label assertions against recorded evidence without calling providers. |
| Run qualification | `tier3 validate-grader`. This qualifies the **shipped verifier**, not the authored grader. Uses the project chat profile, a detached revision, and the bundled reference suite. Live qualification against repository suites requires an isolated external executor and is unavailable in Studio. |

Both qualification actions support split (default `assessment`), repeated case IDs, repeats (3), concurrency (1), attempt timeout (300 seconds), optional maximum false-pass, false-fail and unjudgeable rates, and a committed qualification-policy JSON. Studio caps repeats at 20, concurrency at 4, timeout at 600 seconds and job duration at one hour. The engine enforces gate/policy compatibility. A policy preflight can return a `not_run` receipt without a provider. A successful suite check alone does not establish grader reliability.

Live rate gates compare measured rates to their limits (strictly greater fails). The JSON receipt names `threshold_failures`. With split `all`, the engine gates assessment metrics; rates without a denominator do not fail a maximum. An operator’s `SSL_CERT_FILE` can supply a private CA for an HTTPS judge.

Mount the judge CA bundle read-only and set `SSL_CERT_FILE` in Studio’s environment to its path (relative paths resolve from Studio’s working directory). The qualifier uses this bundle to verify TLS. Configure the final provider endpoint: authenticated verifier HTTP calls reject redirects.

To run an authored grader, use **Live Tier 3** with a generated task environment, a custom grading mode and **Allow the repository grader in the sandbox**. This also applies to custom grading selected by a pinned run policy. This evaluates the skill with that grader; the qualification command measures the shipped verifier.

**Evaluation runs** retains the effective options, commit, engine exit code and JSON/Markdown exports. Instead of accepting `-o/--output` host paths, Studio allocates private run storage and offers the engine's attempt evidence as a ZIP. JSON export replaces `--json` terminal output. Profile changes to provider/model/endpoint require queueing a fresh run rather than silently replaying with different settings.

Scaffolding and suite preflight work with the base Studio image. For live inference install `.[tier3]` in the Studio environment or build the image with `--build-arg STUDIO_TIER3=true`. Configure the project chat profile before running. The worker starts an isolated interpreter in a private directory; its environment does not inherit operator credentials. Use an API-key-backed profile for live qualification. No repository directory is used for Python imports or verifier execution.
