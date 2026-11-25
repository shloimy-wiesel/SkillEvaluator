"""Public browser journeys for immutable evaluation history."""

import multiprocessing
import re
import socket
import subprocess
import time
import urllib.request

from test_providers import save_profile
from test_workspace import connect, playwright, running

pytest_plugins = ("test_workspace",)


def test_author_reopens_run_from_before_skill_and_dataset_branch_advanced(page, private_remote, deployment):
    expect = playwright.expect
    branch = "author/triage"
    fixed = "---\nname: triage\ndescription: Sort incoming requests.\n---\n# Triage\n"
    revision_a_text = fixed.replace("description:", "description: Draft wording.\ndescription:")
    finding = "Duplicate frontmatter key 'description'"

    def overview():
        page.get_by_role("navigation", name="Breadcrumb").get_by_role("link", name="handbook").click()

    def link(name):
        return page.get_by_role("link", name=name, exact=True)

    def press(name):
        page.get_by_role("button", name=name, exact=True).click()

    def checkout_sha():
        return page.get_by_text("Checkout revision", exact=True).locator("+ dd").inner_text()

    with deployment() as first:
        page.goto(first)
        connect(page, *private_remote, skill="skills/triage")
        link("Edit skill").click()
        page.get_by_label("New branch name").fill(branch)
        press("Create branch")
        expect(page.get_by_role("heading", name=f"Edit {branch}")).to_be_visible()
        page.get_by_label("SKILL.md").fill(revision_a_text)
        press("Save and push")
        overview()
        skill_sha = checkout_sha()

        link("Datasets").click()
        press("Open draft")
        page.get_by_label("Case ID").fill("route-ticket")
        page.get_by_label("Prompt", exact=True).fill("Route an urgent ticket")
        page.get_by_label("Expected output", exact=True).fill("Urgent queue")
        press("Add case")
        press("Commit and push")
        expect(page.get_by_role("status")).to_contain_text(f"Pushed dataset changes to {branch}")
        overview()
        sha_a = checkout_sha()
        assert re.fullmatch(r"[0-9a-f]{40}", sha_a) and sha_a != skill_sha
        link("Provider settings").click()
        roles = ("Chat", "Embeddings")
        for role in roles:
            panel = page.get_by_role("region", name=role, exact=True)
            save_profile(panel, f"https://{role.lower()}.private/v1", f"{role}-fixture", f"{role}-secret")
            expect(panel.get_by_text("Key stored", exact=True)).to_be_visible()
        overview()
        link("Evaluation runs").click()
        expect(page.get_by_label("Commit SHA")).to_have_value(sha_a)
        page.get_by_label("Static checks").select_option(label="Schema only")
        press("Queue static checks")
        expect(page.get_by_role("heading", name="tier1-static")).to_be_visible()
        original_run = page.url.removeprefix(first)

        overview()
        link("Edit skill").click()
        page.get_by_label("SKILL.md").fill(fixed)
        press("Save and push")
        overview()
        sha_b = checkout_sha()
        assert sha_b != sha_a
        link("Run history").click()
        link(sha_a).click()
        expect(page.get_by_text(finding, exact=False)).to_be_visible(timeout=30000)

    with deployment() as second:
        page.goto(second)
        link("handbook").click()
        assert checkout_sha() == sha_b
        link("Provider settings").click()
        profile_response = page.request.get(page.url.replace(second, second + "/api/v1"))
        assert profile_response.ok
        for role in roles:
            panel = page.get_by_role("region", name=role, exact=True)
            expect(panel.get_by_label("Model", exact=True)).to_have_value(f"{role}-fixture")
            expect(panel.get_by_label("Base URL")).to_have_value(f"https://{role.lower()}.private/v1")
            expect(panel.get_by_text("Key stored", exact=True)).to_be_visible()
            expect(panel.get_by_label("API key")).to_have_value("")
            assert f"{role}-secret" not in page.content()
            assert f"{role}-secret" not in profile_response.text()
            public_profile = profile_response.json()["profiles"][role.lower()]
            assert public_profile["has_key"] and "key" not in public_profile
        overview()
        link("Edit skill").click()
        expect(page.get_by_label("SKILL.md")).to_have_value(fixed)
        overview()
        link("Datasets").click()
        press("Open draft")
        expect(page.get_by_role("heading", name="route-ticket")).to_be_visible()
        overview()
        link("Run history").click()
        expect(page.get_by_label("Commit SHA")).to_have_value(sha_b)
        link(sha_a).click()
        assert page.url == second + original_run
        expect(page.get_by_text("Commit", exact=True).locator("+ dd")).to_have_text(sha_a)
        expect(page.get_by_role("status")).to_contain_text("failed")
        expect(page.get_by_text(finding, exact=False)).to_be_visible()

        # A separate connection to the very same remote must not inherit this history.
        page.get_by_role("navigation", name="Workspace").get_by_role("link", name="Projects").click()
        connect(page, *private_remote, skill="skills/triage")
        expect(page.get_by_text("main", exact=True)).to_be_visible()
        link("Run history").click()
        expect(page.get_by_text("No runs yet.")).to_be_visible()
        expect(link(sha_a)).to_have_count(0)
        foreign_detail = page.url.split("#")[0] + "/" + original_run.rsplit("/", 1)[1]
        assert page.request.get(foreign_detail).status == 404
        assert page.request.get(foreign_detail.replace(second, second + "/api/v1")).status == 404


def test_failed_gate_and_exports_survive_reopening_at_exact_commit(page, private_remote, tmp_path):
    seed = tmp_path / "seed"
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=seed, text=True).strip()
    manifest = seed / "skills/triage/SKILL.md"
    manifest.write_text("---\nname: triage\ndescription: Sort incoming requests.\n---\n# Triage\n")
    repo = tmp_path / "server/handbook.git"
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=t@example.org", "commit", "-am", "fix"], cwd=seed, check=True
    )
    subprocess.run(["git", "push", repo, "main"], cwd=seed, check=True)
    subprocess.run(["git", "update-server-info"], cwd=repo, check=True)
    volume = tmp_path / "volume"
    with running(volume) as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Evaluation runs").click(timeout=2000)
        assert page.get_by_label("Commit SHA").input_value() != sha
        page.get_by_label("Commit SHA").fill(sha)
        page.get_by_label("Static checks").select_option("schema", timeout=2000)
        page.get_by_role("button", name="Queue static checks").click()
        page.goto("about:blank")
        page.goto(base)
        page.get_by_role("link", name="handbook").click()
        page.get_by_role("link", name="Evaluation runs").click()
        page.get_by_role("link", name=sha).click()
        playwright.expect(page.get_by_role("status")).to_contain_text("failed")
        path = page.url.removeprefix(base)
    with running(volume) as base:
        page.goto(base + path)
        playwright.expect(
            page.get_by_text("SKILL.md must have YAML frontmatter between --- markers", exact=False).first
        ).to_be_visible()
        report = page.request.get(page.get_by_role("link", name="Download JSON").get_attribute("href")).json()
        assert len(report["results"]) == 1
        assert "SKILL.md must have YAML frontmatter" in str(report["results"])
        assert (
            "SKILL.md must have YAML frontmatter"
            in page.request.get(page.get_by_role("link", name="Download Markdown").get_attribute("href")).text()
        )


def slow_app(volume, port):
    """Independent ASGI process so a worker really can be interrupted."""
    import uvicorn
    from fastapi import APIRouter, Request
    from fastapi.responses import RedirectResponse
    from pydantic import BaseModel
    from studio.app import create_app
    from studio.jobs import JobDefinition, Outcome

    class Trial(BaseModel):
        trials: int

    def evaluate(ctx, options):
        ctx.progress(f"Evaluating {options.trials} trials")
        if not (volume / "ready").exists():
            time.sleep(90)
        project = ctx.workspace.get(ctx.project_id)
        notes = ctx.input_file(project.folder + "/SKILL.md").read_text()
        (ctx.artifacts / "notes.md").write_text(notes)
        return Outcome("passed", 0, '{"results":[]}', notes)

    definition = JobDefinition("trial-fixture", Trial, evaluate)
    router = APIRouter()

    @router.post("/projects/{project_id}/trial")
    def trial(request: Request, project_id: str):
        project = request.app.state.workspace.get(project_id)
        run_id = request.app.state.jobs.enqueue(project, project.revision, definition, Trial(trials=7))
        return RedirectResponse(request.url_for("run_detail", project_id=project_id, run_id=run_id), 303)

    uvicorn.run(create_app(volume, routers=(router,), job_definitions=(definition,)), host="127.0.0.1", port=port)


def test_unavailable_submodule_is_not_reported_as_evaluated(page, private_remote, tmp_path):
    seed = tmp_path / "seed"
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=seed, text=True).strip()
    repo = tmp_path / "server/handbook.git"
    subprocess.run(
        ["git", "update-index", "--add", "--cacheinfo", f"160000,{sha},skills/triage/nested"], cwd=seed, check=True
    )
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=t@example.org", "commit", "-m", "nested"],
        cwd=seed,
        check=True,
    )
    subprocess.run(["git", "push", repo, "main"], cwd=seed, check=True)
    subprocess.run(["git", "update-server-info"], cwd=repo, check=True)
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Evaluation runs").click()
        page.get_by_role("button", name="Queue static checks").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("submodule")
        assert page.get_by_role("link", name="Download JSON").count() == 0


def test_interrupted_job_requires_explicit_rerun_with_saved_inputs(page, private_remote, tmp_path):
    from contextlib import contextmanager

    volume = tmp_path / "volume"

    @contextmanager
    def worker():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        process = multiprocessing.get_context("spawn").Process(target=slow_app, args=(volume, port))
        process.start()
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                try:
                    with urllib.request.urlopen(base, timeout=1):
                        break
                except OSError:
                    time.sleep(0.05)
            yield base
        finally:
            process.kill()
            process.join(5)

    with worker() as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("heading", name="handbook").wait_for()
        response = page.request.post(page.url + "/trial")
        page.goto(response.url)
        playwright.expect(page.get_by_role("status")).to_contain_text("Evaluating 7 trials")
        path = page.url.removeprefix(base)
    (volume / "ready").touch()
    with worker() as base:
        page.goto(base + path)
        playwright.expect(page.get_by_role("status")).to_contain_text("interrupted")
        assert page.get_by_role("link", name="Download JSON").count() == 0
        page.get_by_role("button", name="Rerun saved inputs").click(timeout=2000)
        playwright.expect(page.get_by_role("status")).to_contain_text("passed")
        assert page.url != base + path
        playwright.expect(page.get_by_text('{"trials":7}', exact=True)).to_be_visible()
        assert (
            page.request.get(page.get_by_role("link", name="Download Markdown").get_attribute("href")).text()
            == "# Triage\n"
        )
        page.goto(base + path)
        playwright.expect(page.get_by_role("status")).to_contain_text("interrupted")
