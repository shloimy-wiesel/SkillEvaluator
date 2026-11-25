# Studio React acceptance evidence

The standard image serves the production export and FastAPI on one origin.
The CLI surface remains 456 implemented and 127 partial bindings; all 583
are registered. This is the inherited coverage classification, not a claim
that partial features have acquired new capabilities.

| Check | Pinned revision | Result and boundary |
|---|---|---|
| Upgrade from the pre-React image | `087eaa3` | Chromium connected to authenticated fixture Git with `studio-public-verify:2e7f543`; the new standard image opened its named volume and authenticated again. Passed in 7.69 s. |
| Immutable history across container replacement | `087eaa3` | New standard image on both sides. Chromium authored a branch and dataset, configured separate private provider profiles, queued keyless evaluation at A, saved B and replaced the container. Original run and findings still identified A; editing opened B and another project could not read the run. Passed in 14.78 s. |
| Live runtime and private inference | `087eaa3` | Five opt-in checks passed in 81.47 s, including an actual Docker/Harbor/OpenCode trial and private TLS fixture inference/judge, native preflight and CA validation. Gym used the rollout fixture rather than the vendor executable. |
| Live image | `087eaa3` | Production `live` target built; the exported workspace loaded from disk and the installed Docker Compose and Harbor versions were v2.40.3 and 0.25.0. |
| Real GitLab | `3454930` | Private GitLab CE: reviewed CI publication produced a successful runner job; a separate branch edit/push produced a merge request. |
| Small screens | `64f47b3` | Real Chromium at 320, 375 and 1440 px; no page overflow or off-origin requests on the library, overview and provider views. [Desktop](../docs/studio/screenshots/project-desktop.png) · [Phone](../docs/studio/screenshots/projects-phone.png). |

## Reproduce

Build the frontend before local tests as in [DEVELOPMENT.md](DEVELOPMENT.md).
From a clean, pinned worktree with Studio test dependencies installed:

```sh
python -m pytest -q tests/golden tests/studio
docker build --target standard -f studio/Dockerfile -t studio-react:verify .
STUDIO_TEST_IMAGE=studio-react:verify python -m pytest -q \
  tests/studio/test_runs.py -k author_reopens_run
STUDIO_TEST_PREVIOUS_IMAGE="$OLD_STUDIO_IMAGE" STUDIO_TEST_IMAGE=studio-react:verify \
  python -m pytest -q tests/studio/test_workspace.py -k author_reopens_private_skill
```

The two Docker journeys use disposable volumes. [GitLab](GITLAB.md) and
[live trials](RUNS.md) have separate opt-in infrastructure requirements.
