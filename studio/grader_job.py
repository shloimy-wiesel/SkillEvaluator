"""Qualification uses the installed verifier, never authored scripts or Harbor configs."""

import json
import os
import signal
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from zipfile import ZIP_DEFLATED, ZipFile

from pydantic import BaseModel, ConfigDict, Field

from .jobs import JobDefinition, Outcome
from .providers import worker_environment
from .workspace import WorkspaceError


class GraderOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    suite: str = ""  # selected skill-relative suite.json; omitted means the shipped suite
    policy: str = ""
    split: Literal["assessment", "all", "tuning"] = "assessment"
    cases: tuple[str, ...] = ()
    chat: tuple[str, str, str] | None = None
    check_suite: bool = True
    repeats: int = Field(default=3, ge=1, le=20)
    concurrency: int = Field(default=1, ge=1, le=4)
    timeout: float = Field(default=300, gt=0, le=600)
    max_false_pass_rate: float | None = Field(default=None, ge=0, le=1)
    max_false_fail_rate: float | None = Field(default=None, ge=0, le=1)
    max_unjudgeable_rate: float | None = Field(default=None, ge=0, le=1)


def evaluate(ctx, options):
    args = [
        "--json",
        "--split",
        options.split,
        "--repeats",
        str(options.repeats),
        "--concurrency",
        str(options.concurrency),
        "--timeout",
        str(options.timeout),
    ]
    for case in options.cases:
        args.extend(["--case", case])
    for gate in ("max_false_pass_rate", "max_false_fail_rate", "max_unjudgeable_rate"):
        if (limit := getattr(options, gate)) is not None:
            args.extend(["--" + gate.replace("_", "-"), str(limit)])

    def selected(name):
        if Path(name).suffix != ".json" or name.startswith("/"):
            raise WorkspaceError("Select a JSON file in the skill.")
        return ctx.input_file((ctx.skill.relative_to(ctx.root) / name).as_posix())

    if options.policy:
        args.extend(["--qualification-policy", str(selected(options.policy))])
    if options.suite:
        manifest = selected(options.suite)
        if manifest.name != "suite.json":
            raise WorkspaceError("Select a suite.json manifest.")
        args.append(str(manifest.parent))
    with TemporaryDirectory() as temp:
        env = {
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "HOME": temp,
            "PYTHONNOUSERSITE": "1",
            "PYTHON_DOTENV_DISABLED": "1",
        }
        code, payload = invoke([*args, "--check-suite"], temp, env)
        if not options.check_suite and code != 2:
            if options.suite:
                raise WorkspaceError("Live qualification requires the bundled reference suite on this host.")
            # A failed policy preflight must emit the CLI's not_run receipt, even without credentials.
            if code == 0:
                if options.chat is None:
                    raise WorkspaceError("Configure a chat provider in Provider settings before live qualification.")
                if find_spec("harbor") is None:
                    raise WorkspaceError("Install the evaluator tier3 extra for live qualification.")
                current = worker_environment(ctx.workspace, ctx.project_id, "chat")
                if public_identity(current) != options.chat:
                    raise WorkspaceError("Chat settings changed since this run was queued.")
                env.update(current)
            code, payload = invoke([*args, "--output", str(Path(temp) / "output")], temp, env, live=True)
            output = Path(temp) / "output"
            with ZipFile(ctx.artifacts / "qualification.zip", "w", ZIP_DEFLATED) as archive:
                for path in sorted(output.rglob("*")):
                    if path.is_file() and path.suffix in {".json", ".txt"}:
                        archive.writestr(path.relative_to(output).as_posix(), redact(path.read_text(), env))
    status = "not_run" if payload.get("execution_status") == "not_run" else "passed" if code == 0 else "failed"
    report = json.dumps(payload, indent=2)
    return Outcome(status, code, report, "# Grader validation\n\n```json\n" + report + "\n```\n")


def public_identity(env):
    return tuple(env.get("SKILL_EVAL_LLM_" + field, "") for field in ("PROVIDER", "MODEL", "BASE_URL"))


def invoke(args, cwd, env, live=False):
    # Run from an empty private directory. Only the trusted installed Python module is executable.
    command = [
        sys.executable,
        "-I",
        "-c",
        "from skillevaluator.tier3.grader_validation import validate_grader; validate_grader()",
        *args,
    ]
    with subprocess.Popen(
        command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True
    ) as child:
        try:
            output, diagnostic = child.communicate(timeout=3600 if live else 120)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.communicate()
            raise WorkspaceError("Qualification exceeded the Studio time limit.") from None
    if child.returncode not in {0, 1} or not output.strip():
        # Live stderr can contain SDK diagnostics. Never expose credentials or a provider response.
        message = diagnostic.partition("Error: ")[2].strip()[:1000] if not live else ""
        if message and child.returncode == 2:
            return 2, {"status": "invalid", "diagnostic": message.replace(cwd, "[work area]")}
        raise WorkspaceError("Qualification could not finish. Check the installed evaluator and provider settings.")
    return child.returncode, json.loads(redact(output, env))


def redact(text, env):
    for key, value in env.items():
        if key.endswith("API_KEY") and value:
            text = text.replace(json.dumps(value)[1:-1], "[redacted]").replace(value, "[redacted]")
    return text


GRADER = JobDefinition("validate-grader", GraderOptions, evaluate)
