"""Public browser journeys for immutable evaluation history."""

import multiprocessing
import socket
import subprocess
import time
import urllib.request

from test_workspace import connect, playwright, running

pytest_plugins = ("test_workspace",)


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
