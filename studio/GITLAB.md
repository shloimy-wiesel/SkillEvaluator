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
