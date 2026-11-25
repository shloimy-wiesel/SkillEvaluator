# React author workspace

## Problem statement

Authors need one browser workspace for the workflows already supported by Studio. Today, pasting a repository browsing link can fail before the author even sees a project. A replacement must keep existing projects and evidence usable on upgrade.

## Solution

Ship the existing React workspace with Studio. Preserve author URLs, private infrastructure support, and the persistent Python backend. This supersedes only the rendering decision in the original Studio spec (#1); #17 remains the authority for residual CLI parity.

## User stories

1. As an author I can correct a tree URL and select a directory containing `SKILL.md`, so connection errors tell me what to change.
2. As a private GitLab user I can connect using my installation prefix, port and nested groups and reopen the project after restart.
3. As an editor I can create a branch, preview changes, and resolve a stale edit without overwriting someone else's work.
4. As a dataset owner I can edit cases, validate, generate drafts and review imports before saving.
5. As an operator I can configure separate private inference and embedding endpoints, discover models and check readiness without reading keys back.
6. As an evaluator I can launch keyless and live tiers, changed-file checks, and overlap analyses with supported options, distinguishing omitted inputs from explicit settings.
7. As an author I can leave a queued run and return to its pinned inputs, progress and findings.
8. As a reviewer I can compare revisions and compatible retained runs, record feedback and safely inspect or export evidence.
9. As a GitLab maintainer I can configure CI, review jobs and receipts and diagnose private host integration errors.
10. As an expert I can use the implemented catalog, experiment, asset and advanced workflows without entering commands.
11. As a keyboard or narrow-screen user I can navigate every screen and recover from errors without losing drafts.
12. As an operator I can replace the container while preserving projects, encrypted credentials, edited branches and historical evidence.

## Implementation decisions

- Export the existing Next app at build time; FastAPI serves it and same-origin, versioned `/api/v1` endpoints. Route known author GETs explicitly, preserving deep links. Keep missing APIs, downloads and missing assets distinct from the application document.
- JSON endpoints delegate to existing project-scoped services. Preserve origin and host guards, bounded transfers, encrypted write-only keys, immutable run inputs, and inert report viewing. Use consistent structured errors including validation, conflicts and unavailable prerequisites.
- Retain the standard/live image capability split and existing volume. Replace legacy screens only when their replacements pass corresponding journeys. No remote fonts or production frontend CDN.

## Testing decisions

Test at the public Chromium journey (navigation, persistence, outcomes), HTTP API (scope, validation, and conflict behavior), and evaluator boundary (actual effective inputs). Exercise fixture-backed private Git and inference separately from real integrations. Test an existing volume and pinned run at A after saving B and replacing the container. Record commit, commands and exact evidence. Run frontend checks, Python tests, and CLI golden/option coverage checks.

## Out of scope

Changing evaluator algorithms, promising new CLI parity, replacing the standalone reports or Streamlit viewer, and migrating project storage formats without a demonstrated need.
