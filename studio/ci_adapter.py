"""Isolate the CLI engine and scope host access to the connected project."""

import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from .editing import branches, commit_changes
from .workspace import WorkspaceError


def worker(ws, p, task, **params):
    # Separate HOME and repository for each operation, including gh credentials.
    with TemporaryDirectory(dir=ws.data_dir) as temp:
        env = {k: os.environ[k] for k in ("PATH", "LANG", "SSL_CERT_FILE", "GIT_SSL_CAINFO") if k in os.environ}
        root = Path(__file__).resolve().parents[1]
        env.update(HOME=temp, PYTHONPATH=str(root / "src"), GH_PROMPT_DISABLED="1", NO_COLOR="1")
        try:
            result = subprocess.run(
                [sys.executable, str(root / "studio/ci_worker.py")],
                cwd=temp,
                env=env,
                input=json.dumps(
                    dict(
                        task=task,
                        checkout=str(ws.checkout(p)),
                        revision=p.revision,
                        branch=p.branch,
                        remote=p.remote,
                        token=ws.host_token(p),
                        **params,
                    )
                ),
                text=True,
                capture_output=True,
                timeout=200,
                check=True,
            )
            value = json.loads(result.stdout)
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            raise WorkspaceError("CI adapter interrupted; inspect the Git host before retrying.") from exc
        if "error" in value:
            raise WorkspaceError(value["error"])
        return value


def review_branch(ws, p, files, head, title, *, repo_root=False):
    worker(ws, p, "admission")
    existing = branches(ws, p).get(head)
    commit_changes(ws, p, files, title, new_branch=head, repo_root=repo_root, matching_tip=existing)
    if existing:
        return worker(ws, p, "existing_review", head=head, tip=existing)["notice"]
    try:
        return worker(ws, p, "review_request", head=head, title=title)["notice"]
    except WorkspaceError as exc:
        raise WorkspaceError(
            f"Branch {head} was published. Inspect it on the host to complete the request. {exc}"
        ) from exc
