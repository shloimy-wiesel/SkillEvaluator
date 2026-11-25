# Evaluate overlap

Open **Evaluate overlap** on the project. The direct Tier 2 workflow reviews
overlap inside the selected skill and, optionally, compares it with a catalog.
Without a catalog the second stage is explicitly skipped. For a historical
run, enter a full commit SHA and choose **Load commit inputs** first. File
and collection selectors are built from that commit's tree.

| Evaluation | Inputs and defaults |
| --- | --- |
| Direct Tier 2 | Saved chat and embeddings. Intra-skill threshold `0.80`, similarity threshold `0.75`. Full-body mode requires a matching full-body catalog. A mismatched catalog stops the run before inference. |
| Context optimization / dedup scan | Two CLI spellings for the same intra-skill evaluator. Uses the project's skill folder, threshold `0.80`, optional separate embedding and chat model overrides. |
| Similarity check | Only the embeddings profile is needed. Select the skill or a collection directory. Content type defaults to auto; skill, rules and workflows are available. Threshold defaults to `0.75`; full-body mode is off. The default limits are 1,024 entries and 128,000,000 scalar comparisons. |

For similarity, choose a repository JSON catalog to compare a single skill,
or select **Save catalog** to build a downloadable `catalog.json` from a skill
collection. These actions are mutually exclusive. The deprecated CLI `cache`
and `save-cache` spellings map to the same selectors. Save the downloaded
catalog in Git to use it at a known revision. Links and submodules are not
collection inputs.

Direct runs default to summary + native HTML/JSON files; focused checks
default to summary only. Multi-select report formats to override these
defaults. `cli` is the run detail page; `github` downloads annotation text.
HTML, JSON, Markdown, SARIF and JUnit use the engine report writers. The
private per-run files directory replaces `--output-dir`. Studio's history
also retains its standard JSON and Markdown exports independently of these
format selections. Failed and incomplete runs retain their actual findings
and gate exit code.

The Studio image installs `skillevaluator[tier2]`. For local development
install `pip install -e '.[tier2]' -r studio/requirements.txt`. Each run freezes
effective endpoints and models plus a project-scoped encrypted credential
snapshot. Rerun reuses that snapshot, even after settings change (a revoked
key can still fail). Bedrock uses the worker's AWS identity at execution
time. Other roles use separate, non-redirecting HTTPS clients. The isolated
worker receives the snapshot over stdin, has a 10-minute time limit and a
2 GiB address-space limit. Provider responses and stderr aren't exposed as
execution diagnostics.
