import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel
from studio.jobs import JobDefinition, Jobs
from studio.workspace import Project, Workspace


def test_timeout_reaps_owned_descendants_and_releases_single_worker(tmp_path, monkeypatch):
    from studio import expert

    monkeypatch.setenv("STUDIO_EVALUATOR_TIMEOUT_SECONDS", "1")
    workspace = Workspace(tmp_path / "volume")
    project = Project("fixture", "repo", "", ".", "main", "")
    repo = workspace.checkout(project)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "SKILL.md").write_text("# Fixture")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=t@example.org", "commit", "-qm", "fixture"],
        cwd=repo,
        check=True,
    )
    sha = workspace.git(project, ["rev-parse", "HEAD"]).strip()
    pids = tmp_path / "pids"
    script = """
import subprocess, sys, time
if sys.argv[1] == 'quick':
    sys.exit(0)
children = [subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(12)'], start_new_session=new)
            for new in (True, False)]
open(sys.argv[1], 'w').write(' '.join(str(p.pid) for p in children))
time.sleep(12)
"""
    (tmp_path / "expert_worker.py").write_text(script)
    monkeypatch.setattr(expert, "__file__", str(tmp_path / "expert.py"))

    class Options(BaseModel):
        hang: bool

    def evaluate(ctx, options):
        return expert.invoke(
            ctx,
            [str(pids) if options.hang else "quick"],
            ctx.root.parent,
            ctx.artifacts,
            chat={},
            embeddings={},
            runtime={"HOME": str(ctx.root.parent)},
            reason=None,
        )

    definition = JobDefinition("fixture", Options, evaluate)
    jobs = Jobs(workspace, [definition])
    with subprocess.Popen(["sleep", "30"]) as unrelated:
        try:
            slow, next_job = [jobs.enqueue(project, sha, definition, Options(hang=h)) for h in (True, False)]
            jobs.pool.shutdown(wait=True)
            record = jobs.get(project.id, slow)
            assert (record["status"], record["exit_code"]) == ("timed_out", 124)
            assert "deadline" in record["progress"]
            assert jobs.get(project.id, next_job)["status"] == "passed"
            assert all(not Path(f"/proc/{p}").exists() for p in pids.read_text().split())
            assert unrelated.poll() is None
        finally:
            unrelated.terminate()


def test_live_prerequisite_spends_the_evaluator_deadline(tmp_path, monkeypatch):
    from studio.live_job import invoke_engine
    from studio.worker_deadline import WorkerTimeout

    monkeypatch.setenv("STUDIO_LIVE_ENABLED", "1")
    monkeypatch.setenv("STUDIO_EVALUATOR_TIMEOUT_SECONDS", "1")
    harbor = tmp_path / "harbor"
    harbor.write_text("#!/bin/sh\nexec /bin/sleep 12\n")
    harbor.chmod(0o700)
    with pytest.raises(WorkerTimeout, match="deadline"):
        invoke_engine(["--version"], tmp_path, {"PATH": str(tmp_path)})


def test_timeout_removes_only_resources_with_recorded_compose_project(tmp_path, monkeypatch):
    from studio.worker_deadline import WorkerTimeout, run_evaluator

    monkeypatch.setenv("STUDIO_EVALUATOR_TIMEOUT_SECONDS", "1")
    project = "studio-" + "a" * 32
    docker = tmp_path / "docker"
    docker.write_text(f"""#!{sys.executable}
import sys
from pathlib import Path
kind, action, *args = sys.argv[1:]
if action == 'ls':
    assert 'label=com.docker.compose.project={project}' in args
    print('owned-' + kind)
elif action == 'rm':
    assert args[-1] == 'owned-' + kind
    Path(kind).write_text('cleaned')
else:
    sys.exit(1)
""")
    docker.chmod(0o700)
    script = """
import os, sys, time
from pathlib import Path
Path(os.environ['SKILLEVALUATOR_COMPOSE_LEDGER'], sys.argv[1]).touch()
time.sleep(12)
"""
    with pytest.raises(WorkerTimeout, match="deadline"):
        run_evaluator([sys.executable, "-c", script, project], cwd=tmp_path, env={"PATH": str(tmp_path)}, sandbox=True)
    assert all((tmp_path / kind).read_text() == "cleaned" for kind in ("container", "network", "volume"))
