"""Keyless static workflow; never discover tools or configuration in the repo."""

import subprocess
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from .jobs import JobContext, JobDefinition, Outcome


class StaticOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    checks: tuple[Literal["schema", "unicode"], ...] = ("schema", "unicode")
    llm: Literal[False] = False
    profile: Literal["default"] = "default"


def evaluate(ctx: JobContext, options: StaticOptions) -> Outcome:
    import json

    ctx.progress("Checking " + ", ".join(options.checks))
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            str(Path(__file__).with_name("static_worker.py")),
            str(ctx.skill.relative_to(ctx.root.parent)),
            options.model_dump_json(),
        ],
        cwd=ctx.root.parent,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        capture_output=True,
        timeout=180,
        check=True,
        text=True,
    )
    return Outcome(**json.loads(completed.stdout))


STATIC = JobDefinition("tier1-static", StaticOptions, evaluate)
