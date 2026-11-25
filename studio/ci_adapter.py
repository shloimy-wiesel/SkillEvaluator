"""Isolate the CLI engine and scope host access to the connected project."""

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from .ci_gitlab import configured_instance, host_operation
from .editing import branches, commit_changes
from .operator_env import operator_env
from .workspace import WorkspaceError


def worker(ws, p, task, **params):
    lab = None
    github = urlsplit(p.remote).hostname == "github.com"
    if not github:
        lab = configured_instance(ws, p)
        if task in {"status", "admission", "existing_review", "review_request"}:
            if lab is None:
                raise WorkspaceError(
                    "Configure this project's GitLab instance and API credential for live host operations."
                )
            return host_operation(ws, p, lab, task, params)
        if params.get("mode") == "pr" and lab is None:
            raise WorkspaceError("Configure the GitLab instance before proposing a merge request.")
    # Separate HOME and repository for each operation, including gh credentials.
    with TemporaryDirectory(dir=ws.data_dir) as temp:
        env = operator_env("PATH", "LANG", "SSL_CERT_FILE", "GIT_SSL_CAINFO")
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
                        token=ws.host_token(p) if github else "",
                        gitlab_root=lab.root if lab else None,
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
