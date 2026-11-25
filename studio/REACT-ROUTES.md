# Author journey inventory at 53ee4ba

`P` means `/projects/{project_id}`. The first column is **both** the old URL and the React deep link. Each GET needs a versioned JSON view at `/api/v1` + path (home reads `/api/v1/projects`); mutation paths in the second column are relative to `P` unless stated otherwise. Backend modules below are in `studio/`, test modules in `tests/studio/`.

|Browser GET|Mutations / inline actions|Service|Browser contract|
|---|---|---|---|
|`/`|`POST /projects` (absolute)|workspace, gitlab|test_workspace, test_gitlab|
|`P`|`/check`|workspace, navigation|test_workspace|
|`P/gitlab`|`/gitlab/token`, `/gitlab/check`|gitlab, gitlab_routes|test_gitlab, test_gitlab_instance|
|`P/edit`|`/edit/changes`, `/edit/branch`|editing, editor_routes|test_editing|
|`P/datasets`|`/datasets` multipart; draft, generate, validate, migrate, collect, refine, import and publish|dataset_routes, dataset_drafts, dataset_tools, dataset_collection, dataset_traces|test_datasets|
|`P/assets`|`/assets/scaffold`, `/assets/qualify`|assets, grader_job|test_assets|
|`P/ci`|`/ci`, `/ci/demo`|ci_routes, ci_adapter, ci_gitlab|test_ci, test_gitlab_instance|
|`P/ci/advanced`|`/ci/advanced` (including receipt download)|ci_advanced, ci_receipts|test_ci|
|`P/installation`|`/installation`|installation, changed_files|test_installation|
|`P/providers`|`/providers/readiness/run`, `/providers/{role}`, `/providers/{role}/check`|providers, readiness, provider_snapshots|test_providers|
|`P/runs`|`/runs`|runs, static_job|test_runs|
|`P/runs/{run_id}`|`/runs/{run_id}/rerun`|runs, jobs|test_runs, test_live|
|`P/overlap`|`/overlap`|overlap, overlap_worker|test_overlap|
|`P/live`|`/live`|live_routes, live_job|test_live, test_private_trial|
|`P/expert/{action}`|`/expert/{action}`|expert, expert_options, expert_catalog|test_expert|
|`P/experiments`|`/experiments/{action}`|experiment_routes, experiment_jobs|test_experiments|
|`P/compare`|revision/retained run selection|comparison, comparison_evidence|test_comparison|
|`P/results/history`|native trends and version history; download JSON/CSV/Markdown/comparison|history|test_comparison|
|`P/results`|`/results/uploads`, `/results/uploads/{source}/remove`; filtered CSV|review, review_uploads|test_review|
|`P/results/{run_id}`|`/results/{run_id}/feedback`|review, retained, feedback|test_review|

## Non-page URLs

Keep these direct GET downloads: `P/assets/evidence/{run_id}`, `P/runs/{run_id}/exports/{kind}`, `P/overlap/{run_id}/files/{name}`, `P/expert/artifacts/{run_id}/{name:path}`. Preserve media type, filename, authorization and missing-file status. The `results` and `results/history` query downloads and advanced CI receipt are also byte responses. Never send an application document for unknown API or chunk URLs.

## Browser state contracts

Preserve `pushed` and `draft` editor state; `topic` on installation; `sha` on overlap and expert; `prior`, `current`, `prior_run`, `current_run` on compare; repeated `scope` on history; repeated dashboard filters and run IDs; inventory-key, conversation and report navigation on result details. Preserve `#main`, `#history` and extension task groups. Queued or running jobs refresh until terminal. Unknown expert actions are not executable commands.
