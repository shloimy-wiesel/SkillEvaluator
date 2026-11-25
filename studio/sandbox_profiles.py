"""Operator authorization for optional, fixed Studio sandbox profiles."""

import os
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from .workspace import WorkspaceError

OptionalProfile = Literal["native-docker", "gym-docker"]
Profile = Literal["generated", "native-docker", "gym-docker"]
LABELS = {"native-docker": "Native Harbor · Docker", "gym-docker": "Experimental NeMo Gym · Docker"}


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    folder: str
    sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")]
    profile: OptionalProfile


def availability(project, folder, sha, profile):
    if os.getenv("STUDIO_LIVE_ENABLED") != "1":
        return "Live runtime is disabled."
    if not os.getenv("STUDIO_EVALUATOR_CONTAINER_REVISION"):
        return "The worker revision is not pinned."
    try:
        approvals = TypeAdapter(list[Approval]).validate_json(os.getenv("STUDIO_SANDBOX_APPROVALS", "[]"))
    except ValidationError:
        return "The worker sandbox approval list is invalid."
    if not any((a.project, a.folder, a.sha, a.profile) == (project, folder, sha, profile) for a in approvals):
        return "This profile is not operator-approved for this skill and commit."
    return None


def authorize(project, folder, sha, controls):
    if controls.sandbox_profile == "generated":
        return
    if reason := availability(project, folder, sha, controls.sandbox_profile):
        raise WorkspaceError(reason)
    if not controls.reviewed_inputs:
        raise WorkspaceError("Confirm review of the pinned task inputs and consent to sandbox execution.")
    if controls.env_mode != "docker" or controls.autopilot or controls.workflow == "direct" or controls.dataset:
        raise WorkspaceError(
            "This Docker profile requires Evaluate with the pinned skill inputs; no dataset generation or substitution."
        )
    if controls.sandbox_profile == "gym-docker":
        from skillevaluator.tier3.nemo_gym.backend import nemo_gym_capability_errors

        errors = nemo_gym_capability_errors(
            agents=list(controls.agents),
            env_mode="docker",
            grading_mode=controls.grading_mode,
            harbor_keep_jobs=controls.harbor_keep_jobs,
            stop_on_pass=controls.stop_on_pass,
            override_storage_mb=controls.override_storage_mb,
            agent_runtime_preflight=controls.agent_runtime_preflight,
            run_options=controls.model_dump(),
        )
        if errors:
            raise WorkspaceError("; ".join(errors))
        if controls.agents not in ((), ("codex",)):
            raise WorkspaceError("The pinned Studio Gym runtime supports the Codex profile only.")


def stage_native(source, destination):
    """Admit single-step scaffold tasks. Never hand authored orchestrator settings to Harbor."""
    import re
    import shutil
    import tomllib

    from skillevaluator.tier3.scaffold import STARTER_DOCKERFILE, starter_task_manifest

    invalid = WorkspaceError(
        "Unsupported native task: use init-harbor-task --with-config with the stock task manifest and Dockerfile; edit instructions and sandbox tests only."
    )
    if not source.is_dir():
        raise invalid
    cases = []
    for case in source.iterdir():
        if case.name in ("README.md", "dataset.toml") and case.is_file():
            continue
        if not case.is_dir() or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", case.name):
            raise invalid
        allowed = {
            "task.toml",
            "instruction.md",
            "environment",
            "environment/Dockerfile",
            "tests",
            "tests/test.sh",
            "tests/grader.py",
            "tests/grader.sh",
        }
        paths = {p.relative_to(case).as_posix() for p in case.rglob("*")}
        if paths - allowed or not {"task.toml", "instruction.md", "environment/Dockerfile", "tests/test.sh"} <= paths:
            raise invalid
        try:
            manifest = tomllib.loads((case / "task.toml").read_text())
            if (
                manifest != tomllib.loads(starter_task_manifest(case.name))
                or (case / "environment/Dockerfile").read_text() != STARTER_DOCKERFILE
            ):
                raise invalid
        except (OSError, ValueError) as exc:
            raise invalid from exc
        cases.append(case)
    if not cases:
        raise invalid
    if (dataset := source / "dataset.toml").is_file():
        try:
            manifest = tomllib.loads(dataset.read_text())
            header = manifest["dataset"]
            tasks = manifest["tasks"]
            if (
                set(manifest) != {"dataset", "tasks"}
                or set(header) - {"name", "description"}
                or not all(isinstance(value, str) for value in header.values())
                or any(set(task) != {"name"} for task in tasks)
                or sorted(task["name"] for task in tasks) != sorted("nvidia/" + case.name for case in cases)
            ):
                raise invalid
        except (TypeError, AttributeError, ValueError, KeyError, OSError) as exc:
            raise invalid from exc
    destination.mkdir()
    for name in ("dataset.toml", "README.md"):
        if (source / name).is_file():
            shutil.copyfile(source / name, destination / name)
    for case in cases:
        shutil.copytree(case, destination / case.name)
