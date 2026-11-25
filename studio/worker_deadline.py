"""Monotonic worker deadline shared by sandbox checks and evaluator execution."""

import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from contextvars import ContextVar
from functools import wraps
from pathlib import Path

from .workspace import WorkspaceError

_deadline = ContextVar("evaluator_deadline", default=None)


class WorkerTimeout(WorkspaceError):
    pass


def new_deadline():
    try:
        seconds = int(os.getenv("STUDIO_EVALUATOR_TIMEOUT_SECONDS", "3600"))
        if not 1 <= seconds <= 86400:
            raise ValueError
    except ValueError:
        raise WorkspaceError("Set STUDIO_EVALUATOR_TIMEOUT_SECONDS to 1-86400 seconds.") from None
    return time.monotonic() + seconds


def bounded_worker(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        token = _deadline.set(_deadline.get() or new_deadline())
        try:
            return function(*args, **kwargs)
        finally:
            _deadline.reset(token)

    return wrapped


def _cleanup_projects(ledger, cwd, env):
    end = time.monotonic() + 30
    docker_env = {
        k: env[k] for k in ("PATH", "HOME", "DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH") if k in env
    }

    def docker(*args):
        return subprocess.run(
            ["docker", *args],
            cwd=cwd,
            env=docker_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=max(0, end - time.monotonic()),
            text=True,
        ).stdout

    for entry in ledger.iterdir():
        project = entry.name
        if not re.fullmatch(r"studio-[0-9a-f]{32}", project):
            raise WorkerTimeout("Evaluator deadline expired; unrecognized sandbox ownership record.")
        for kind, flags in (("container", ["-f", "-v"]), ("network", []), ("volume", [])):
            try:
                ids = docker(
                    kind,
                    "ls",
                    *(["-a"] if kind == "container" else []),
                    "-q",
                    "--filter",
                    f"label=com.docker.compose.project={project}",
                ).split()
                if ids:
                    docker(kind, "rm", *flags, "--", *ids)
            except (OSError, subprocess.SubprocessError) as exc:
                raise WorkerTimeout(f"Evaluator deadline expired; verify sandbox cleanup for {project}.") from exc


def run_evaluator(command, *, cwd, env, sandbox, limit=None, **io):
    remaining = (_deadline.get() or new_deadline()) - time.monotonic()
    if remaining <= 0:
        raise WorkerTimeout("Evaluator wall-clock deadline expired.")
    timeout = min(remaining, limit) if limit else remaining
    with ExitStack() as stack:
        if sandbox:
            ledger = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="compose-", dir=cwd)))
            env = {**env, "SKILLEVALUATOR_COMPOSE_LEDGER": str(ledger)}
        result = subprocess.run(
            [sys.executable, "-I", str(Path(__file__).with_name("process_supervisor.py")), str(timeout), *command],
            cwd=cwd,
            env=env,
            **io,
        )
        if result.returncode == -signal.SIGALRM:
            if sandbox:
                _cleanup_projects(ledger, cwd, env)
            raise WorkerTimeout("Evaluator wall-clock deadline expired.")
        return result
