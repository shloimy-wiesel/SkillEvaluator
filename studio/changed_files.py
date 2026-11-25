"""Bind changed paths and offline hook options to a detached evaluator job."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .jobs import JobDefinition, Outcome


class ChangedOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    paths: tuple[str, ...] = Field(min_length=1, max_length=1000)
    check: Literal["quality", "schema", "lint-scripts"]
    verbose: bool = False
    min_score: int = Field(70, ge=0, le=100)
    quality_config: str | None = None


def changed_paths(ws, project):
    sha = project.revision
    history = ws.git(project, ["rev-list", "--parents", "-1", sha]).split()
    revisions = [history[1], sha] if len(history) > 1 else ["--root", sha]
    raw = ws.git(
        project, ["diff-tree", "--no-commit-id", "--no-renames", "--name-only", "-r", "-z", *revisions, "--"], raw=True
    )
    paths = []
    for item in raw.split(b"\0"):
        name = item.decode("utf-8", errors="surrogateescape")
        if name.isprintable() and name and all(p.lower() not in ("", ".", "..", ".git") for p in name.split("/")):
            paths.append(name)
    return paths


def evaluate(ctx, options):
    config = ctx.input_file(options.quality_config) if options.quality_config else None
    ctx.progress("Checking changed paths: " + options.check)
    result = subprocess.run(
        [sys.executable, "-I", str(Path(__file__).with_name("changed_worker.py"))],
        input=json.dumps(
            dict(options.model_dump(), root=str(ctx.root), quality_config=str(config) if config else None)
        ),
        cwd=ctx.root.parent,
        env={"LANG": "C.UTF-8", "PATH": "/usr/bin:/bin"},
        text=True,
        capture_output=True,
        check=True,
        timeout=180,
    )
    code, lines, detail = json.loads(result.stdout)
    text = "\n".join(lines).replace(str(ctx.root) + "/", "") or "No affected skills."
    return Outcome("failed" if code else "passed", code, json.dumps({"output": text, "diagnostics": detail}), text)


CHANGED = JobDefinition("changed-files-v1", ChangedOptions, evaluate)
