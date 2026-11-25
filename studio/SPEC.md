# SkillEvaluator Studio: a persistent workspace for skill authors

## Problem Statement

An author can write a skill but cannot evaluate or compare it without navigating CLI flags, configuring providers, and keeping track of result directories. A branch name alone cannot identify the skill evaluated last week.

## Solution

Open a self-hosted browser workspace, pick a project and branch, edit the skill and dataset, save changes to GitHub or GitLab, run an evaluation, and compare the evidence. Offer common tasks first and the full developer option set through labelled advanced controls.

## User Stories

1. As an author, I want to connect a GitHub or GitLab repository and choose a skill directory, so I can work in an existing repository or monorepo.
2. As an author, I want to open or create a branch, so a new version starts from the revision I choose.
3. As an author, I want a browser editor, change preview, and save action, so I can commit and push without learning Git.
4. As a collaborator, I want stale edits identified, so saving never silently overwrites a remote change.
5. As an author, I want to create, edit, delete, and validate datasets and cases using forms, so I need not edit JSON.
6. As an author, I want to generate and preview cases or import and review traces before saving, so I control what enters my evaluation.
7. As an operator, I want independent endpoint, model, and credential settings for chat and embeddings, so our private services work after restart.
8. As an author, I want readiness checks and model discovery, so I can fix setup problems before a costly run.
9. As an author, I want static checks without credentials and optional model-backed checks, so I can choose cost and depth.
10. As an author, I want catalog and similarity controls, so I can check overlap inside and across skills.
11. As an evaluator, I want agent, backend, grading, budget and trial controls, so live evaluation is reproducible.
12. As an author, I want to close my browser during a run, then return to its status, findings and exports.
13. As an author, I want to compare two saved revisions and their compatible runs, so a changed dataset or configuration is not mistaken for skill improvement.
14. As an advanced user, I want each CLI capability reachable without entering commands, including experiments, scaffolding, CI setup, artifact review, and external metrics.
15. As a maintainer, I want an inventory checked against the shipped CLI, so new options cannot silently go missing.
16. As an operator, I want one documented container deployment with persistent storage, so recreating a container preserves projects, secrets, and history.

## Implementation Decisions

- Server-rendered FastAPI/Jinja pages with progressive enhancement, keyboard-accessible forms and responsive layouts. No separate React build.
- Git branches are editable versions. Freeze the commit SHA, selected dataset and effective non-secret run configuration before enqueueing. Use a detached workspace per run. Never force-push stale edits.
- Git owns authored content. A persistent volume owns SQLite metadata, encrypted credentials, job state, and retained artifacts. An interrupted job must never be displayed as completed or silently retried at the user's expense.
- Reuse the existing engine, validators and report contracts. Distinguish skipped, incomplete, failed and passed; missing measurements are not zero.
- Present first-class workflows plus an advanced option catalogue. Translate terminal presentation switches to browser equivalents. Aliases may share a control. Do not expose arbitrary shell commands, host paths or executable configuration as substitutes for forms.
- Track capability coverage individually, including prerequisites, incompatible settings, defaults, inputs, exports, and browser equivalents. Inventory alone does not count as implementation.
- Revision review pairs two immutable source snapshots with independently selected retained run IDs. Keep within-run baseline lift separate from across-version with-skill change; display a reason when pairing is unavailable.

## Testing Decisions

- Drive each vertical slice red then green through author-visible behavior. Use the browser journey and evaluator adapter as the primary seams.
- Use a disposable Git remote to exercise branch creation, pushes and conflicting saves; reopen the same persistent volume to verify continuity.
- Use deterministic provider/runner fixtures to verify settings, status, immutable inputs and results; exercise a real keyless Tier 1 run as a smoke test. Keep live-provider tests explicitly opt-in.
- Compare the coverage matrix against the existing CLI golden contract. Verify form-to-engine behavior, not merely the presence of labels.

## Out of Scope

Replacing the CLI, implementing new evaluation algorithms, and a hosted SaaS offering.

## Further Notes

Build on `feat/ui`. Keep runtime prerequisites visible per action, especially for live trials and repository integrations.
