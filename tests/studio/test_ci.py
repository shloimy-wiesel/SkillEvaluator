import subprocess

import pytest
import yaml

# ruff: noqa: F811 -- shared browser and authenticated Git fixtures
from test_workspace import before_push, connect, page, playwright, private_remote, running  # noqa: F401

SCAN = ".github/workflows/skill-checks.yml"


@pytest.fixture
def github_remote(private_remote, tmp_path, monkeypatch):
    import os
    import shutil
    import sys

    url, key = private_remote
    remote = tmp_path / "server/handbook.git"
    canonical = "https://github.com/author/handbook.git"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "git").write_text(f"""#!{sys.executable}
import os,sys
args=sys.argv[1:]; normal=os.getenv('GIT_ALLOW_PROTOCOL')=='https'
args=[({url!r} if normal else {str(remote)!r}) if v=={canonical!r} and 'set-url' not in args else v for v in args]
if normal and os.getenv('GIT_CONFIG_KEY_0'): os.environ['GIT_CONFIG_KEY_0']=os.environ['GIT_CONFIG_KEY_0'].replace({canonical!r},{url!r})
os.execv({shutil.which("git")!r},['git',*args])
""")
    (bin_dir / "git").chmod(0o755)
    marker = tmp_path / "pages-api-created"
    (bin_dir / "gh").write_text(f"""#!{sys.executable}
import os,sys,json
from pathlib import Path
assert os.environ.get('GH_TOKEN')=={key!r}
a=sys.argv; marker=Path({str(marker)!r})
if a[1:3]==['pr','list']: print('[]')
elif a[1:3]==['pr','create']: print('https://github.com/author/handbook/pull/8')
else:
    assert a[1]=='api'; i=a.index('--method'); method,path=a[i+1:i+3]; status=200; data={{}}
    if path=='repos/author/handbook': data={{'private':False,'permissions':{{'admin':True}},'default_branch':'main'}}
    elif path.endswith('/pulls') and method=='POST': data={{'html_url':'https://github.com/author/handbook/pull/9'}}
    elif '/contents/' in path: status=404
    elif '/workflows/' in path and '/runs?' in path: data={{'workflow_runs':[{{'conclusion':'failure','status':'completed','html_url':'https://github.com/author/handbook/actions/runs/18'}}]}}
    elif path.endswith('/actions/permissions'): data={{'allowed_actions':'all','enabled':True}}
    elif path.endswith('/pages'):
        if method=='POST': marker.touch()
        if marker.exists(): data={{'html_url':'https://author.github.io/handbook/','build_type':'workflow'}}
        else: status=404
    elif path.endswith('/git/ref/heads/gh-pages'): status=404
    elif 'environments/github-pages' in path: pass
    else: raise AssertionError(path)
    if path=='repos/author/handbook' and marker.with_name('nonpublic').exists(): data.update(private=True,visibility='private',owner={{'type':'Organization'}})
    print('HTTP/1.1',status); print(); print(json.dumps(data))
""")
    (bin_dir / "gh").chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + ":" + os.environ["PATH"])
    return canonical, key


def test_review_checks_then_publish(page, github_remote, tmp_path):
    remote = tmp_path / "server/handbook.git"
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *github_remote, skill="skills/triage")
        page.get_by_role("link", name="Repository CI").click(timeout=1500)
        page.get_by_role("button", name="Check status").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("Workflow absent on remote branch main")
        page.get_by_label("Minimum score").fill("83")
        page.get_by_label("Scan scope").select_option("all")
        page.get_by_label("Release channel").select_option("stable")
        page.get_by_role("button", name="Review setup").click()
        review = page.get_by_label("Generated workflow").inner_text()
        assert subprocess.run(["git", "cat-file", "-e", "main:" + SCAN], cwd=remote).returncode
        page.get_by_role("button", name="Publish reviewed workflow").click()
        saved = subprocess.check_output(["git", "show", "main:" + SCAN], cwd=remote).decode()
        assert saved == review
        job = yaml.safe_load(saved)["jobs"]["skills"]
        assert job["uses"].endswith("@stable") or "stable" in job["uses"]
        assert job["with"] == {"paths": "skills/triage", "min-score": 83, "scan-mode": "all", "llm": False}
        page.get_by_role("button", name="Check status").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("Workflow present on remote branch main")
        playwright.expect(page.get_by_role("link", name="Inspect scan runs on Git host")).to_have_attribute(
            "href", github_remote[0].removesuffix(".git") + "/actions/workflows/skill-checks.yml"
        )


def test_review_demo_then_publish_separate_branch(page, github_remote, tmp_path):
    remote = tmp_path / "server/handbook.git"
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *github_remote, skill="skills/triage")
        page.get_by_role("link", name="Repository CI").click()
        page.get_by_role("button", name="Review demo").click(timeout=1500)
        playwright.expect(page.get_by_role("alert")).to_contain_text("Set up checks")
        page.get_by_role("button", name="Review setup").click()
        preview = yaml.safe_load(page.get_by_label("Generated workflow").inner_text())["jobs"]["skills"]
        assert preview["with"]["min-score"] == 70 and preview["with"]["scan-mode"] == "auto"
        assert "@stable" not in preview["uses"] and "@sha256:" in preview["with"]["image"]
        page.get_by_role("button", name="Publish reviewed workflow").click()
        page.get_by_role("button", name="Review demo").click()
        playwright.expect(page.get_by_label("Demo change")).to_contain_text("<!-- SkillEvaluator onboarding demo:")
        page.get_by_role("button", name="Publish demo branch").click()
        playwright.expect(page.get_by_role("link", name="Open pull request for review")).to_have_attribute(
            "href", github_remote[0].removesuffix(".git") + "/compare/main...ci/skillevaluator-test?expand=1"
        )
        original = subprocess.check_output(["git", "show", "main:skills/triage/SKILL.md"], cwd=remote)
        assert original == b"# Triage\n"
        assert (
            subprocess.check_output(["git", "show", "ci/skillevaluator-test:skills/triage/SKILL.md"], cwd=remote)
            == original + b"\n<!-- SkillEvaluator onboarding demo: exercise automatic PR feedback. -->\n"
        )


def test_changed_review_and_untrusted_workflow_fields_are_rejected(page, github_remote, tmp_path):
    remote = tmp_path / "server/handbook.git"
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *github_remote, skill="skills/triage")
        page.get_by_role("link", name="Repository CI").click()
        page.get_by_role("button", name="Review setup").click()
        page.get_by_label("Minimum score").fill("12")
        page.get_by_role("button", name="Publish reviewed workflow").click()
        playwright.expect(page.get_by_role("alert")).to_contain_text("Review the generated workflow")
        page.get_by_role("button", name="Review setup").click()
        status = page.get_by_label("Minimum score").evaluate("""async input => {
          const data = new FormData(input.form);
          data.set('action', 'publish'); data.set('workflow', 'unreviewed workflow');
          data.set('repo', '/other/project');
          return (await fetch(input.form.getAttribute('action'), {method:'POST', body:data})).status;
        }""")
        assert status == 422
        assert subprocess.run(["git", "cat-file", "-e", "main:" + SCAN], cwd=remote).returncode


def second_skill(tmp_path, remote):
    seed = tmp_path / "seed"
    (seed / "more-skills/other").mkdir(parents=True)
    (seed / "more-skills/other/SKILL.md").write_text("# Other\n")
    subprocess.run(["git", "add", "."], cwd=seed, check=True)
    subprocess.run(
        ["git", "-c", "user.name=a", "-c", "user.email=a@example.com", "commit", "-m", "other"], cwd=seed, check=True
    )
    subprocess.run(["git", "push", str(remote), "main"], cwd=seed, check=True)


def test_gitlab_all_tier_review(page, private_remote, tmp_path):
    remote = tmp_path / "server/handbook.git"
    second_skill(tmp_path, remote)
    # Nested GitLab project path, served by the same authenticated Git backend.
    group = remote.parent / "group"
    group.mkdir()
    (group / "handbook.git").symlink_to(remote)
    url, key = private_remote
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, url.replace("/handbook.git", "/group/handbook.git"), key, skill="skills/triage")
        page.get_by_role("link", name="Repository CI").click()
        page.get_by_role("link", name="Advanced CI setup").click(timeout=1500)
        page.get_by_label("Evaluation tiers").select_option("all")
        page.get_by_label("Attempts").fill("4")
        page.get_by_label("Runner label").fill("protected-linux")
        page.get_by_label("Scan roots").fill("more-skills")
        page.get_by_role("button", name="Review files").click()
        preview = page.get_by_label(".gitlab-ci.yml", exact=True).inner_text()
        assert yaml.safe_load(preview)["variables"]["SKILL_EVAL_N_ATTEMPTS"] == "4"
        assert yaml.safe_load(preview)["variables"]["SKILL_EVAL_RUNNER"] == "protected-linux"
        page.get_by_role("button", name="Apply reviewed setup").click()
        assert subprocess.check_output(["git", "show", "main:.gitlab-ci.yml"], cwd=remote).decode() == preview

        page.get_by_role("link", name="Repository CI").click()
        page.get_by_role("button", name="Review demo").click()
        playwright.expect(page.get_by_text("File: more-skills/other/SKILL.md", exact=False)).to_be_visible(timeout=1500)


@pytest.fixture(params=["contract", "persisted"])
def gitlab_host(page, private_remote, api_handler, tmp_path, monkeypatch, *, request):
    import json
    import ssl
    from types import SimpleNamespace
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen

    remote = tmp_path / "server/handbook.git"
    group = remote.parent / "install/gitlab/group/nested"
    group.mkdir(parents=True)
    (group / "handbook.git").symlink_to(remote)
    url, key = private_remote
    root = url.removesuffix("/handbook.git") + "/install/gitlab"
    url = root + "/group/nested/handbook.git"
    endpoint = "/install/gitlab/api/v4/projects/group%2Fnested%2Fhandbook"
    host_api = {}
    api_token = "api-only-fixture-token"

    def project_api(handler):
        if "/api/v4/" not in handler.path:
            return False
        entry = host_api.get((handler.command, handler.path))
        code, value = (
            (entry(handler) if entry else (404, {})) if handler.headers.get("PRIVATE-TOKEN") == api_token else (403, {})
        )
        handler.send_response(code)
        handler.end_headers()
        handler.wfile.write(json.dumps(value).encode())
        return True

    api_handler.append(project_api)
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "certificate.pem"))

    # #18 owns persistence and TLS transport. Exercise its public consumer contract
    # with an actual prefix/port/CA-bound HTTP server and distinct API credential.
    def api_request(method, suffix="", *, query=None, payload=None):
        address = root.split("/install/gitlab")[0] + endpoint + suffix + ("?" + urlencode(query) if query else "")
        req = Request(
            address,
            data=json.dumps(payload).encode() if payload else None,
            method=method,
            headers={"PRIVATE-TOKEN": api_token},
        )
        with urlopen(
            req, timeout=3, context=ssl.create_default_context(cafile=tmp_path / "certificate.pem")
        ) as response:
            return json.load(response)

    lab = SimpleNamespace(
        root=root, namespace="group/nested/handbook", web_url=url.removesuffix(".git"), request=api_request
    )
    transport = request.param
    if transport == "contract":
        monkeypatch.setattr("studio.ci_adapter.configured_instance", lambda _ws, p: lab if p.remote == url else None)
    else:
        pytest.importorskip(
            "studio.gitlab", reason="Requires the persistent instance settings and CA transport from #18"
        )
        monkeypatch.delenv("GIT_SSL_CAINFO")
        monkeypatch.delenv("SSL_CERT_FILE")

    def connect_project():
        if transport == "persisted":
            page.get_by_text("Self-managed GitLab", exact=True).click()
            page.get_by_label("GitLab installation URL").fill(root)
            page.get_by_label("Private CA certificate").fill((tmp_path / "certificate.pem").read_text())
        connect(page, url, key, skill="skills/triage")
        if transport == "persisted":
            detail = page.url
            page.get_by_role("link", name="GitLab access").click()
            page.get_by_label("GitLab API token").fill(api_token)
            page.get_by_role("button", name="Save API token").click()
            page.goto(detail)

    sha = subprocess.check_output(["git", "rev-parse", "main"], cwd=remote, text=True).strip()
    pipeline = {"id": 17, "project_id": 9, "sha": sha, "ref": "main", "status": "pending"}
    host_api["GET", endpoint] = lambda _: (200, {"id": 9, "default_branch": "main"})
    host_api["GET", endpoint + f"/pipelines?ref=main&sha={sha}&per_page=20"] = lambda _: (
        200,
        [pipeline, {**pipeline, "id": 16, "status": "failed"}],
    )
    host_api["GET", endpoint + "/pipelines/17/jobs?per_page=50&page=1"] = lambda _: (
        200,
        [
            {
                "id": 23,
                "pipeline": pipeline,
                "name": "verify handbook",
                "status": "success",
                "web_url": "https://gitlab.com/untrusted",
                "runner": {"description": "private runner detail"},
            }
        ],
    )
    host_api["GET", endpoint + "/pipelines/16/jobs?per_page=50&page=1"] = lambda _: (
        200,
        [{"id": 22, "pipeline": {**pipeline, "id": 16}, "name": "previous attempt", "status": "failed"}],
    )

    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect_project()
        page.get_by_role("link", name="Repository CI").click()
        page.get_by_role("link", name="Advanced CI setup").click()
        page.get_by_label("Evaluation tiers").select_option("all")
        yield SimpleNamespace(
            api=host_api,
            endpoint=endpoint,
            lab=lab,
            pipeline=pipeline,
            api_token=api_token,
            key=key,
            base=base,
            connect=connect_project,
            remote=remote,
        )


def test_selected_gitlab_pipeline_jobs(page, gitlab_host):
    host = gitlab_host
    page.get_by_role("button", name="Read live status").click()
    job = page.get_by_role("row").filter(has_text="verify handbook")
    playwright.expect(job.get_by_role("cell", name="success")).to_be_visible()
    playwright.expect(job.get_by_role("link")).to_have_attribute("href", host.lab.web_url + "/-/jobs/23")
    for private in ("private runner detail", "gitlab.com/untrusted", host.api_token, host.key):
        assert private not in page.content()
    page.get_by_label("Pipeline for this revision").select_option("16")
    page.get_by_role("button", name="Read live status").click()
    playwright.expect(page.get_by_role("row").filter(has_text="previous attempt")).to_contain_text("failed")
    playwright.expect(job).to_have_count(0)
    # A pipeline can disappear from the authorized list between selection and submit.
    sha = host.pipeline["sha"]
    host.api["GET", host.endpoint + f"/pipelines?ref=main&sha={sha}&per_page=20"] = lambda _: (200, [host.pipeline])
    page.get_by_role("button", name="Read live status").click()
    playwright.expect(page.get_by_role("alert")).to_contain_text("not available for this project and revision")
    playwright.expect(page.get_by_role("table", name="Pipeline jobs")).to_have_count(0)


def test_project_status_adapter_bounds_and_validates_jobs(gitlab_host, tmp_path):
    from studio.ci_adapter import worker
    from studio.workspace import Workspace, WorkspaceError

    host = gitlab_host
    ws = Workspace(tmp_path / "volume")
    (project,) = ws.projects()

    def inspect():
        return worker(ws, project, "status", platform="gitlab", tiers="all", pipeline_id=17)

    jobs = host.endpoint + "/pipelines/17/jobs?per_page=50&page="
    job = {"id": 1, "pipeline": host.pipeline, "name": "verify", "status": "running"}
    for number in (1, 2):
        host.api["GET", jobs + str(number)] = lambda _, n=number: (
            200,
            [{**job, "id": (n - 1) * 50 + i + 1} for i in range(50)],
        )
    rows = inspect()["jobs"]
    assert len(rows) == 100 and rows[-1]["url"] == host.lab.web_url + "/-/jobs/100"
    for changes in ({"project_id": 10}, {"sha": "0" * 40}, {"id": 16}):
        host.api["GET", jobs + "1"] = lambda _, c=changes: (200, [{**job, "pipeline": {**host.pipeline, **c}}])
        with pytest.raises(WorkspaceError, match="outside the selected pipeline"):
            inspect()
    host.api["GET", jobs + "1"] = lambda _: (200, [{**job, "id": 2**63}])
    with pytest.raises(WorkspaceError, match="invalid resource identifier"):
        inspect()


def test_read_gitlab_pipeline_and_create_review_requests(page, gitlab_host):
    import json

    host = gitlab_host
    lab, host_api, endpoint, remote = host.lab, host.api, host.endpoint, host.remote
    requests = []

    def create(req):
        payload = json.loads(req.rfile.read(int(req.headers["Content-Length"])))
        requests.append(payload)
        return 201, {"iid": 7, "web_url": "https://gitlab.com/untrusted"}

    host_api["POST", endpoint + "/merge_requests"] = create
    page.get_by_label("Publication mode").select_option("pr")
    page.get_by_role("button", name="Read live status").click()
    playwright.expect(page.get_by_role("status")).to_contain_text("Latest pipeline: pending")
    playwright.expect(page.get_by_role("status")).to_contain_text(lab.web_url + "/-/pipelines/17")
    page.get_by_role("button", name="Review files").click()
    feedback = yaml.safe_load(page.get_by_label(".gitlab/skill-feedback.yml", exact=True).inner_text())["include"][0][
        "inputs"
    ]
    assert feedback["api-url"] == lab.root + "/api/v4" and feedback["project-id"] == "group/nested/handbook"
    assert not requests
    page.get_by_role("button", name="Apply reviewed setup").click()
    playwright.expect(page.get_by_role("status")).to_contain_text("/merge_requests/7", timeout=3000)
    branch = requests[0]["source_branch"]
    assert requests[0]["target_branch"] == "main"
    subprocess.run(["git", "update-ref", "refs/heads/main", branch], cwd=remote, check=True)
    # Reconnect at the merged default branch.
    page.goto(host.base)
    host.connect()
    page.get_by_role("link", name="Repository CI").click()
    page.get_by_role("button", name="Review demo").click()
    page.get_by_role("button", name="Create reviewed PR/MR").click()
    playwright.expect(page.get_by_role("status")).to_contain_text("/merge_requests/7")
    assert requests[1]["source_branch"] == "ci/skillevaluator-all-tiers-test"
    assert b"onboarding demo" in subprocess.check_output(
        ["git", "show", requests[1]["source_branch"] + ":skills/triage/SKILL.md"], cwd=remote
    )

    demo_head = requests[1]["source_branch"]
    sha = subprocess.check_output(["git", "rev-parse", demo_head], cwd=remote, text=True).strip()
    host_api["GET", endpoint + "/merge_requests?state=opened&source_branch=ci%2Fskillevaluator-all-tiers-test"] = (
        lambda _: (
            200,
            [
                {
                    "iid": 7,
                    "source_branch": demo_head,
                    "target_branch": "main",
                    "sha": sha,
                    "source_project_id": 17,
                    "target_project_id": 17,
                    "web_url": lab.web_url + "/-/merge_requests/7",
                }
            ],
        )
    )
    page.get_by_role("button", name="Review demo").click()
    page.get_by_role("button", name="Create reviewed PR/MR").click()
    playwright.expect(page.get_by_role("status")).to_contain_text("/merge_requests/7", timeout=1500)
    assert len(requests) == 2


def test_github_hosted_setup_review_and_receipt(page, github_remote, tmp_path):
    """The real wizard provisions Pages and pushes two branches via isolated git/gh transports."""
    import json
    from pathlib import Path

    canonical, key = github_remote
    remote = tmp_path / "server/handbook.git"
    marker = tmp_path / "pages-api-created"
    second_skill(tmp_path, remote)
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, canonical, key, skill="skills/triage")
        page.get_by_role("link", name="Repository CI").click()
        page.get_by_role("link", name="Advanced CI setup").click()
        page.get_by_label("Hosted reports").select_option("hosted")
        page.get_by_label("Publication mode").select_option("pr")
        page.get_by_label("Scan roots").fill("skills\nmore-skills")
        page.get_by_label("GitHub Pages report URL").fill("https://author.github.io/handbook/")
        page.get_by_role("button", name="Review files").click()
        path = ".github/workflows/publish-skill-reports.yml"
        reviewed = page.get_by_label(path, exact=True).inner_text(timeout=5000)
        assert not marker.exists()
        with page.expect_download() as event:
            page.get_by_role("button", name="Download reviewed plan").click()
        receipt = json.loads(Path(event.value.path()).read_text())
        assert receipt["selected_roots"] == ["skills", "more-skills"] and receipt["requested_action"] == "pr"
        page.get_by_role("button", name="Apply reviewed setup").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("https://github.com/author/handbook/pull/8")
        assert marker.exists()
        assert subprocess.check_output(["git", "show", "gh-pages:history.json"], cwd=remote) == b"[]\n"
        assert (
            subprocess.check_output(["git", "show", "ci/skillevaluator-setup:" + path], cwd=remote).decode() == reviewed
        )


def test_github_all_tier_routing_and_release_controls(page, github_remote, tmp_path):
    import json
    from pathlib import Path

    volume = tmp_path / "volume"
    releases = volume / "ci-releases"
    releases.mkdir(parents=True)
    descriptor = json.loads(Path("src/skillevaluator/ci-release-all-tiers.json").read_text())
    descriptor["workflow_ref"] = "a" * 40
    (releases / "candidate.json").write_text(json.dumps(descriptor))
    with running(volume) as base:
        page.goto(base)
        connect(page, *github_remote, skill="skills/triage")
        page.get_by_role("link", name="Repository CI").click()
        page.get_by_role("link", name="Advanced CI setup").click()
        for label, option in [
            ("Host platform", "github"),
            ("Evaluation tiers", "all"),
            ("Pinned release descriptor", "candidate"),
            ("Execution environment", "local"),
            ("Chat provider", "openai-compatible"),
            ("Embedding provider", "openai-compatible"),
            ("Tier 1 provider", "anthropic"),
            ("Tier 3 provider", "openai-compatible"),
        ]:
            page.get_by_label(label, exact=True).select_option(option, timeout=1200)
        for label, value in [
            ("Default branch override", "release"),
            ("Chat model", "chat/m"),
            ("Embedding model", "emb/m"),
            ("Chat base URL", "https://chat.example/v1"),
            ("Embedding base URL", "https://emb.example/v1"),
            ("Tier 1 model", "claude"),
            ("Tier 3 model", "live"),
            ("Tier 3 base URL", "https://live.example/v1"),
            ("Native agents (comma separated)", "codex,opencode"),
            ("Agent model overrides (one AGENT=MODEL per line)", "codex=x\nopencode=y"),
            ("Protected environment name", "evaluation"),
            ("Gateway secret name (not its value)", "CHAT_KEY"),
            ("Concurrency", "3"),
            ("Timeout minutes", "23"),
        ]:
            page.get_by_label(label, exact=True).fill(value)
        page.get_by_label("Protected Tier 1 LLM checks").check()
        page.get_by_label("Publish benchmark update PR").check()
        page.get_by_role("button", name="Review files").click()
        scan = yaml.safe_load(
            page.get_by_label(".github/workflows/skill-checks-all-tiers.yml", exact=True).inner_text()
        )
        job = scan["jobs"]["skills"]
        opts = job["with"]
        assert job["uses"].endswith("@" + "a" * 40) and scan["on"]["push"]["branches"] == ["release"]
        assert job["secrets"]["LLM_API_KEY"] == "${{ secrets.CHAT_KEY }}"
        expected = {
            "env-mode": "local",
            "provider": "openai-compatible",
            "embedding-provider": "openai-compatible",
            "model": "chat/m",
            "embedding-model": "emb/m",
            "tier1-provider": "anthropic",
            "tier1-model": "claude",
            "tier1-llm": True,
            "tier3-provider": "openai-compatible",
            "tier3-model": "live",
            "base-url": "https://chat.example/v1",
            "embedding-base-url": "https://emb.example/v1",
            "tier3-base-url": "https://live.example/v1",
            "agents": "codex,opencode",
            "agent-models": "codex=x\nopencode=y",
            "environment": "evaluation",
            "n-concurrent": 3,
            "timeout-minutes": 23,
        }
        assert {k: opts[k] for k in expected} == expected
        assert (
            "benchmarks"
            in yaml.safe_load(page.get_by_label(".github/workflows/feedback-all-tiers.yml", exact=True).inner_text())[
                "jobs"
            ]
        )
        page.get_by_label("Tier 3 model", exact=True).fill("${{ secrets.OTHER }}")
        page.get_by_role("button", name="Apply reviewed setup").click()
        assert "string_pattern_mismatch" in page.locator("body").inner_text()


def test_existing_gitlab_pipeline_gets_manual_merge_preview(page, private_remote, tmp_path):
    remote = tmp_path / "server/handbook.git"
    group = remote.parent / "group"
    group.mkdir()
    (group / "handbook.git").symlink_to(remote)
    original = "build:\n  script: [echo existing-pipeline]\n"
    seed = tmp_path / "seed"
    (seed / ".gitlab-ci.yml").write_text(original)
    subprocess.run(["git", "add", ".gitlab-ci.yml"], cwd=seed, check=True)
    subprocess.run(
        ["git", "-c", "user.name=a", "-c", "user.email=a@example.com", "commit", "-m", "existing pipeline"],
        cwd=seed,
        check=True,
    )
    subprocess.run(["git", "push", str(remote), "main"], cwd=seed, check=True)
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(
            page,
            private_remote[0].replace("/handbook.git", "/group/handbook.git"),
            private_remote[1],
            skill="skills/triage",
        )
        page.get_by_role("link", name="Repository CI").click()
        page.get_by_role("link", name="Advanced CI setup").click()
        page.get_by_label("Evaluation tiers").select_option("all")
        page.get_by_role("button", name="Review files").click()
        assert "skill-evaluation" in page.get_by_label(".gitlab-ci.yml", exact=True).inner_text(timeout=1500)
        playwright.expect(page.get_by_role("alert")).to_contain_text("manual merge")
        assert not page.get_by_role("button", name="Apply reviewed setup").count()
        assert subprocess.check_output(["git", "show", "main:.gitlab-ci.yml"], cwd=remote).decode() == original


def test_private_pages_never_published_without_access_control(page, github_remote, tmp_path):
    (tmp_path / "nonpublic").touch()
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *github_remote, skill="skills/triage")
        page.get_by_role("link", name="Repository CI").click()
        page.get_by_role("link", name="Advanced CI setup").click()
        page.get_by_role("button", name="Review files").click()
        if page.get_by_role("button", name="Apply reviewed setup").count():
            page.get_by_role("button", name="Apply reviewed setup").click()
        playwright.expect(page.get_by_role("alert")).to_contain_text("private Pages", timeout=1000)
        assert subprocess.run(
            ["git", "cat-file", "-e", "main:" + SCAN], cwd=tmp_path / "server/handbook.git"
        ).returncode


def test_live_github_status_and_authenticated_demo(page, github_remote, tmp_path):
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *github_remote, skill="skills/triage")
        page.get_by_role("link", name="Repository CI").click()
        page.get_by_role("button", name="Review setup").click()
        page.get_by_role("button", name="Publish reviewed workflow").click()
        page.get_by_role("button", name="Review demo").click()
        page.get_by_role("button", name="Create reviewed PR/MR").click()
        playwright.expect(page.get_by_role("link", name="Open pull request for review")).to_have_attribute(
            "href", "https://github.com/author/handbook/pull/9"
        )
        page.get_by_role("link", name="Advanced CI setup").click()
        page.get_by_role("button", name="Read live status").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("Latest scan: failure")
        playwright.expect(page.get_by_role("status")).to_contain_text("Latest publication: failure")
