# Self-managed GitLab (#18)

For `https://git.example.net:8443/forge/team/subgroup/handbook.git`, enter
`https://git.example.net:8443/forge` in **Self-managed GitLab → GitLab
installation URL**. Use the final HTTPS clone URL; redirects aren't followed.
The host and port must match. Studio cannot infer a self-managed hostname or
distinguish an installation prefix from a group. Leave the root blank only
for generic Git transport or the actual `gitlab.com` origin.

Paste the issuing CA's **public PEM certificate** if the installation uses
private PKI. It applies to Git and API connections for this project. Without
it, the deployment's `GIT_SSL_CAINFO` bundle or system trust is used.
The volume retains the installation, CA bundle and encrypted credentials.

* **Private repository credentials**: supply an HTTPS Git username and
  `read_repository` token to clone; use `write_repository` to push.
  Protected branches and membership still apply.
* **Project details → GitLab access**: save a separate personal or project
  access token with `read_api` to inspect project and pipeline status.
  An API operation that creates a merge request needs `api` plus a suitable
  project role. The API check verifies project read access only. Save a
  blank API token to remove it. Studio never substitutes the Git token.

## CI adapter

CI consumer contract: `from studio.gitlab import instance`. Call
`lab = instance(workspace, project)`; `None` means no configured GitLab.
`lab.root` is the HTTPS installation root, `lab.namespace` the complete
namespace/project, `lab.web_url` the canonical project URL.
`lab.request(method, suffix="", *, query=None, payload=None)` returns decoded
GitLab project API JSON (or `None` for an empty successful response). `suffix`
is a server-owned endpoint such as `/pipelines` or `/merge_requests`, not a
URL. Use `query` for filters and `payload` for POST JSON.
`lab.web_url + "/-/pipelines"` and `lab.web_url + "/-/merge_requests"` are
safe link bases; construct individual links using validated numeric IDs.
Failures raise author-displayable `WorkspaceError`. Do not follow URLs
returned by a remote or retry against a public host.

In **Advanced CI setup → Read live status**, the latest pipeline for the
open default-branch revision is selected first. To inspect another attempt,
choose **Pipeline for this revision** and read status again. Studio lists
up to 20 pipelines and the first 100 jobs of the selected pipeline. Each
row shows the job name, status and a link on the configured GitLab project.
Job traces, runner details, variables and artifacts are not fetched separately
or displayed.

## Verification

`python -m pytest -q tests/studio/test_gitlab.py` runs Chromium, real smart
HTTPS Git and a small local GitLab API **protocol fixture**. For real GitLab
use a disposable private project containing a `SKILL.md`:

```
STUDIO_GITLAB_SMOKE_CONFIG=/secure/disposable.json python -m pytest -q tests/studio/test_gitlab_instance.py
```

The mode-0600 JSON file needs `root`, `remote`, `username`, `git_token`,
`api_token`, optional `ca_pem` and `folder`. The smoke creates and pushes a
unique branch, creates an MR, and queries pipelines at that commit. It does
not require a runner or verify runner execution. Delete the disposable project
and revoke its credentials afterwards.

Verified 2026-11-25 with `gitlab/gitlab-ce:18.11.3-ce.0`: the browser
connected to `https://localhost:24873/forge/engineering/platform/handbook.git`
using a project-specific private trust bundle and separate Git/API tokens,
created a branch and pushed an edit. The project API created MR `!1` at
the pushed SHA; the pipeline query returned an empty list. This smoke used
a real self-managed GitLab container and did not exercise a CI runner.

### Reviewed push → real runner (#13 / #18)

From the repository root on a **Linux host that can reach its local Docker
bridge addresses**, use a Studio test environment with pytest, Playwright
and Chromium installed. Choose an unused private subnet that does not
overlap a host/VPN route or another Docker network. No GitLab account,
model provider or external CI credentials are needed.

```sh
# In a fresh Python environment, if needed:
python -m pip install -e '.[dev]' -r studio/requirements.txt
python -m playwright install chromium

docker pull gitlab/gitlab-ce:18.11.3-ce.0
docker pull gitlab/gitlab-runner:alpine-v18.11.0
python scripts/studio/gitlab_runner_smoke.py --subnet 192.168.237.0/28
```

The launcher creates a new HTTPS `/forge` installation, a private
`engineering/platform/handbook` project, and a tagged project runner. It
publishes no host ports. Only CE and Runner join the internal bridge.
The shell executor runs **inside the dedicated Runner container** as
`gitlab-runner`. Its only host bind mount is the public test certificate,
read-only. No privileged mode, host checkout or Docker socket is used.
The launcher removes its containers, anonymous volumes, network, test
workspace and temporary credentials on normal exit (including test failure);
the pulled images stay cached.

The browser selects **Advanced CI setup → All tiers → Save → Review files
→ Apply reviewed setup**. GitLab runs the fixture's `smoke-ci.yml` when
the reviewed `.gitlab-ci.yml` appears. The job checks out the private repo,
checks for the generated file and skill, and checks its UID and socket
isolation. **Read live status** must show the successful pipeline for that
exact pushed SHA and a `studio-smoke` job row with status `success`. The
test also checks the job's commit and assigned runner ID through the
project-bound Studio API adapter with a separate `read_api` token.

The project-level CI file override is intentional: this verifies the
reviewed push, runner execution and status transport. It does **not**
execute the generated evaluator includes, call a model, run MR feedback,
or verify reports or artifacts. The test remains skipped in ordinary
pytest runs.

Observed 2026-11-25 on CE 18.11.3 with Runner 18.11.0: for
`/forge/engineering2/platform/handbook`, Chromium showed pipeline `#1`
as `success`. The Studio adapter returned job `#1` (`studio-smoke`),
`success`, runner ID `2`, commit `cd99d55f3ed5f45b4f98cbc886d95fc863fefb94`.
These IDs belonged only to the disposable instance.
