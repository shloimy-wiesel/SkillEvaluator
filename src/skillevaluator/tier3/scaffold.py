# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0


"""Generate evaluation starters without the optional live Harbor runtime."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import tomllib
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console

from skillevaluator.tier3.case_ids import safe_child, validate_case_id, validate_case_ids
from skillevaluator.tier3.dataset_utils import DATASET_EXTENSIONS, load_dataset_entries_with_format
from skillevaluator.tier3.evals_config import CONFIG_FILENAMES, _validate_config, load_evals_config
from skillevaluator.tier3.harbor import DEFAULT_LLM_VERIFIER_TIMEOUT_SEC
from skillevaluator.tier3.harbor.secure_copy import copytree_secure
from skillevaluator.tier3.toml_utils import toml_quote
from skillevaluator.utils.rich_markup import escape_markup

# emoji=False: ":name:" codes in untrusted text must print literally.
console = Console(emoji=False)

_HARBOR_RESERVED_CASE_NAMES = frozenset({"dataset.toml", "readme.md", "metric.py", "results"})


def _starter_evals_entry(skill_path: Path, case_id: str) -> dict[str, Any]:
    return {
        "id": case_id,
        "prompt": "Replace this with the eval prompt for the agent.",
        "expected_output": "Replace this with the expected outcome.",
        "expected_skill": skill_path.name,
        "assertions": [
            # The no-skill baseline is graded on the same assertions, so grade the
            # outcome, not skill use (skill_execution scores that).
            "The agent's final response completes the task in the prompt.",
        ],
    }


def _ensure_starter_evals_json(evals_dir: Path, skill_path: Path, case_id: str) -> None:
    existing = [evals_dir / f"evals{extension}" for extension in DATASET_EXTENSIONS]
    existing = [path for path in existing if path.exists()]
    if len(existing) > 1:
        raise ValueError("multiple eval datasets found: " + ", ".join(str(path) for path in existing))
    if existing:
        return
    evals_file = evals_dir / "evals.json"
    payload = {"skill_name": skill_path.name, "evals": [_starter_evals_entry(skill_path, case_id)]}
    evals_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _validate_existing_scaffold_state(private_root: Path, evals_dir: Path) -> None:
    """Validate authored dataset/config inputs before changing a private snapshot."""

    datasets = [evals_dir / f"evals{extension}" for extension in DATASET_EXTENSIONS]
    datasets = [path for path in datasets if path.exists()]
    if len(datasets) > 1:
        raise ValueError("multiple eval datasets found: " + ", ".join(str(path) for path in datasets))
    if datasets:
        entries, dataset_format = load_dataset_entries_with_format(datasets[0])
        if not entries:
            raise ValueError(f"eval dataset is empty: {datasets[0]}")
        validate_case_ids(entry.get("id") for entry in entries)
        for index, entry in enumerate(entries):
            required_text = ("prompt", "expected_output") if dataset_format == "agentskills" else ("question",)
            for field_name in required_text:
                value = entry.get(field_name)
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"invalid eval dataset entry {index}: {field_name} must be a non-empty string")
            if dataset_format == "agentskills":
                for authored_name, runtime_name in (
                    ("prompt", "question"),
                    ("expected_output", "ground_truth"),
                    ("assertions", "expected_behavior"),
                ):
                    if authored_name in entry and runtime_name in entry and entry[authored_name] != entry[runtime_name]:
                        raise ValueError(
                            f"invalid eval dataset entry {index}: conflicting {authored_name} and {runtime_name}"
                        )
            assertions = entry.get("assertions")
            if assertions is not None and (
                not isinstance(assertions, list)
                or any(not isinstance(assertion, str) or not assertion.strip() for assertion in assertions)
            ):
                raise ValueError(f"invalid eval dataset entry {index}: assertions must be a list of non-empty strings")
            question = entry.get("question")
            if not isinstance(question, str) or not question.strip():
                raise ValueError(f"invalid eval dataset entry {index}: question must be a non-empty string")
            ground_truth = entry.get("ground_truth")
            if ground_truth is not None and (
                not isinstance(ground_truth, str) or (dataset_format == "agentskills" and not ground_truth.strip())
            ):
                raise ValueError(f"invalid eval dataset entry {index}: ground_truth must be a non-empty string")
            expected_behavior = entry.get("expected_behavior")
            if expected_behavior is not None and (
                not isinstance(expected_behavior, list)
                or any(not isinstance(behavior, str) or not behavior.strip() for behavior in expected_behavior)
            ):
                raise ValueError(
                    f"invalid eval dataset entry {index}: expected_behavior must be a list of non-empty strings"
                )

    configs = [evals_dir / name for name in CONFIG_FILENAMES]
    configs = [path for path in configs if path.exists()]
    if len(configs) > 1:
        raise ValueError("multiple eval config files found: " + ", ".join(str(path) for path in configs))
    load_evals_config(private_root)


def _write_evals_config(evals_dir: Path, *, grading_mode: str, task_source: str) -> None:
    candidates = [evals_dir / name for name in CONFIG_FILENAMES]
    existing = [path for path in candidates if path.exists()]
    if len(existing) > 1:
        raise ValueError("multiple eval config files found: " + ", ".join(str(path) for path in existing))
    config_file = existing[0] if existing else candidates[0]
    if config_file.exists():
        data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        if data is None:
            data = {}
        elif not isinstance(data, dict):
            raise ValueError(f"invalid eval config in {config_file}: top level must be a mapping")
    else:
        data = {}

    data["schema_version"] = data.get("schema_version", 1)
    harbor = data.setdefault("harbor", {})
    if not isinstance(harbor, dict):
        raise ValueError(f"invalid eval config in {config_file}: harbor must be a mapping")
    harbor["task_source"] = task_source
    harbor.setdefault("n_attempts", 1)
    harbor.setdefault("pass_threshold", 0.60)
    harbor.setdefault("stop_on_pass", False)

    grading = data.setdefault("grading", {})
    if not isinstance(grading, dict):
        raise ValueError(f"invalid eval config in {config_file}: grading must be a mapping")
    grading["mode"] = grading_mode

    _validate_config(data, config_file)
    config_file.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _python_grader_template() -> str:
    return '''#!/usr/bin/env python3
"""User-owned SkillEvaluator custom grader.

Contract:
- Read /logs/agent/trajectory.json for the agent trajectory.
- Read /tests/entry.json for eval case metadata.
- Write /logs/verifier/reward.json.
- Write /logs/verifier/reward.txt with a numeric 0.0-1.0 score.

In default_plus_custom mode, default grading runs first. Put domain-specific scores
under custom_metrics and do not overwrite reserved metric names:
security, skill_execution, skill_efficiency, accuracy, goal_accuracy,
behavior_check, overall, details, metrics, metric_set, entry_id.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

TRAJECTORY_JSON = Path(os.environ.get("HARBOR_ATIF_PATH", "/logs/agent/trajectory.json"))
ENTRY_JSON = Path(os.environ.get("HARBOR_ENTRY_JSON", "/tests/entry.json"))
REWARD_JSON = Path(os.environ.get("HARBOR_REWARD_JSON", "/logs/verifier/reward.json"))
REWARD_TXT = Path(os.environ.get("HARBOR_REWARD_TXT", "/logs/verifier/reward.txt"))


def main() -> None:
    _trajectory = json.loads(TRAJECTORY_JSON.read_text(encoding="utf-8")) if TRAJECTORY_JSON.exists() else {}
    _entry = json.loads(ENTRY_JSON.read_text(encoding="utf-8")) if ENTRY_JSON.exists() else {}

    score = 1.0
    reward = {
        "overall": score,
        "custom_metrics": {
            "custom_check": score,
        },
        "details": {
            "custom_check": {
                "score": score,
                "reason": "Replace this with real custom grading logic.",
            }
        },
    }
    REWARD_JSON.parent.mkdir(parents=True, exist_ok=True)
    REWARD_JSON.write_text(json.dumps(reward, indent=2), encoding="utf-8")
    REWARD_TXT.write_text(str(score), encoding="utf-8")


if __name__ == "__main__":
    main()
'''


def _shell_grader_template() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

# User-owned SkillEvaluator custom grader.
#
# Contract:
# - Read /logs/agent/trajectory.json for the agent trajectory.
# - Read /tests/entry.json for eval case metadata.
# - Write /logs/verifier/reward.json.
# - Write /logs/verifier/reward.txt with a numeric 0.0-1.0 score.
#
# In default_plus_custom, default grading runs first. Put domain-specific scores
# under custom_metrics and do not overwrite reserved metric names.

REWARD_JSON="${HARBOR_REWARD_JSON:-/logs/verifier/reward.json}"
REWARD_TXT="${HARBOR_REWARD_TXT:-/logs/verifier/reward.txt}"
score="1.0"

mkdir -p "$(dirname "$REWARD_JSON")"
cat > "$REWARD_JSON" <<EOF
{
  "overall": ${score},
  "custom_metrics": {
    "custom_check": ${score}
  },
  "details": {
    "custom_check": {
      "score": ${score},
      "reason": "Replace this with real custom grading logic."
    }
  }
}
EOF

printf "%s" "$score" > "$REWARD_TXT"
"""


def _write_grader_file(path: Path, *, language: str) -> None:
    # LF only: graders run inside a Linux container, and Windows' default CRLF
    # breaks the shebang and `set -euo pipefail`.
    if language == "shell":
        path.write_text(_shell_grader_template(), encoding="utf-8", newline="\n")
    else:
        path.write_text(_python_grader_template(), encoding="utf-8", newline="\n")
    path.chmod(0o755)


def _native_test_sh(language: str) -> str:
    command = 'bash "${tests_dir}/grader.sh"' if language == "shell" else 'python3 "${tests_dir}/grader.py"'
    return f'#!/bin/bash\nset -euo pipefail\ntests_dir="${{HARBOR_TESTS_DIR:-/tests}}"\n{command}\n'


def _write_harbor_dataset(harbor_dir: Path, case_id: str) -> None:
    """Add one quoted task to a private Harbor dataset manifest."""
    dataset_file = harbor_dir / "dataset.toml"
    task_name = f"nvidia/{case_id}"
    if dataset_file.exists():
        content = dataset_file.read_text(encoding="utf-8")
        try:
            parsed = tomllib.loads(content)
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"invalid Harbor dataset manifest {dataset_file}: {exc}") from exc
        tasks = parsed.get("tasks", [])
        if not isinstance(tasks, list) or any(
            not isinstance(task, dict) or not isinstance(task.get("name"), str) for task in tasks
        ):
            raise ValueError(f"invalid Harbor dataset manifest {dataset_file}: tasks must contain string names")
        if any(task["name"] == task_name for task in tasks):
            return
        separator = "" if not content or content.endswith("\n\n") else "\n" if content.endswith("\n") else "\n\n"
        content = f"{content}{separator}[[tasks]]\nname = {toml_quote(task_name)}\n"
    else:
        content = (
            "[dataset]\n"
            f"name = {toml_quote('custom-skillevaluator')}\n"
            f"description = {toml_quote('User-owned Harbor task set for SkillEvaluator')}\n\n"
            "[[tasks]]\n"
            f"name = {toml_quote(task_name)}\n"
        )
    try:
        tomllib.loads(content)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"generated invalid Harbor dataset manifest: {exc}") from exc
    dataset_file.write_text(content, encoding="utf-8")


def init_custom_grader(
    skill_path: Path,
    *,
    mode: str,
    language: str,
    force: bool,
    no_config: bool,
    console: Console = console,
) -> int:
    """Create a BYOG custom grader starter under evals/."""
    skill_path = skill_path.expanduser().resolve()
    evals_dir = skill_path / "evals"
    if evals_dir.is_symlink():
        raise ValueError(f"evals directory must not be a symlink: {evals_dir}")
    if os.path.lexists(evals_dir) and not evals_dir.is_dir():
        raise ValueError(f"evals path must be a directory: {evals_dir}")

    with tempfile.TemporaryDirectory(prefix="skillevaluator-custom-grader-") as temporary:
        private_root = Path(temporary).resolve(strict=True)
        private_evals = private_root / "evals"
        if evals_dir.exists():
            copytree_secure(evals_dir, private_evals, allowed_root=skill_path)
        else:
            private_evals.mkdir(mode=0o700)

        grader_py = private_evals / "grader.py"
        grader_sh = private_evals / "grader.sh"
        existing = [path for path in (grader_py, grader_sh) if path.exists()]
        if existing and not force:
            names = ", ".join(str(evals_dir / path.name) for path in existing)
            console.print(
                f"[red]Error:[/red] custom grader already exists: {escape_markup(names)}. "
                "Re-run with --force to overwrite."
            )
            return 1
        if force:
            for existing_path in existing:
                existing_path.unlink()

        private_grader = grader_sh if language == "shell" else grader_py
        _write_grader_file(private_grader, language=language)
        _ensure_starter_evals_json(private_evals, skill_path, "case-001")
        if not no_config:
            _write_evals_config(private_evals, grading_mode=mode, task_source="evals_json")

        copytree_secure(private_evals, evals_dir, replace_existing=True, allowed_root=private_root)

    grader_path = evals_dir / private_grader.name
    console.print(f"Created SkillEvaluator custom grader starter at [cyan]{escape_markup(str(grader_path))}[/cyan]")
    return 0


def init_harbor_task(
    skill_path: Path,
    *,
    force: bool,
    case_id: str,
    mode: str,
    language: str,
    with_config: bool,
    console: Console = console,
) -> int:
    """Create a BYOT Harbor starter template under evals/harbor/."""
    requested_skill_path = skill_path.expanduser()
    if requested_skill_path.is_symlink():
        raise ValueError(f"skill path must not be a symlink: {requested_skill_path}")
    skill_path = requested_skill_path.resolve()
    skill_file = skill_path / "SKILL.md"
    if not skill_path.is_dir() or not skill_file.is_file() or skill_file.is_symlink():
        raise ValueError(f"skill path must be a directory containing a regular SKILL.md: {skill_path}")

    case_id = validate_case_id(case_id)
    if case_id.casefold() in _HARBOR_RESERVED_CASE_NAMES:
        raise ValueError(f"case id {case_id!r} is reserved in the Harbor dataset root")

    evals_dir = skill_path / "evals"
    if evals_dir.is_symlink():
        raise ValueError(f"evals directory must not be a symlink: {evals_dir}")
    if os.path.lexists(evals_dir) and not evals_dir.is_dir():
        raise ValueError(f"evals path must be a directory: {evals_dir}")

    with tempfile.TemporaryDirectory(prefix="skillevaluator-scaffold-") as temporary:
        private_root = Path(temporary).resolve(strict=True)
        private_evals = private_root / "evals"
        if evals_dir.exists():
            copytree_secure(evals_dir, private_evals, allowed_root=skill_path)
        else:
            private_evals.mkdir(mode=0o700)
        _validate_existing_scaffold_state(private_root, private_evals)

        private_harbor = private_evals / "harbor"
        if os.path.lexists(private_harbor) and not private_harbor.is_dir():
            raise ValueError(f"Harbor scaffold root must be a directory: {evals_dir / 'harbor'}")
        private_harbor.mkdir(exist_ok=True)
        collision = next(
            (
                child.name
                for child in private_harbor.iterdir()
                if child.name != case_id and child.name.casefold() == case_id.casefold()
            ),
            None,
        )
        if collision is not None:
            raise ValueError(f"case id {case_id!r} conflicts with existing Harbor entry {collision!r}")
        private_case = safe_child(private_harbor, case_id)
        public_case = evals_dir / "harbor" / case_id
        if os.path.lexists(private_case):
            if not force:
                console.print(
                    f"[red]Error:[/red] {escape_markup(str(public_case))} already exists. "
                    "Re-run with --force to overwrite."
                )
                return 1
            if not private_case.is_dir() or private_case.is_symlink():
                raise ValueError(f"existing Harbor case must be a real directory: {public_case}")
            shutil.rmtree(private_case)

        tests_dir = private_case / "tests"
        env_dir = private_case / "environment"
        tests_dir.mkdir(parents=True)
        env_dir.mkdir()

        _ensure_starter_evals_json(private_evals, skill_path, case_id)
        if with_config:
            _write_evals_config(private_evals, grading_mode=mode, task_source="native_harbor")
        _write_harbor_dataset(private_harbor, case_id)

        task_content = f"""schema_version = {toml_quote("1.3")}

[task]
name = {toml_quote(f"nvidia/{case_id}")}
description = {toml_quote("Custom SkillEvaluator Harbor task")}

[metadata]
entry_id = {toml_quote(case_id)}

[agent]
timeout_sec = 300.0

[verifier]
timeout_sec = {DEFAULT_LLM_VERIFIER_TIMEOUT_SEC}

[environment]
cpus = 2
memory_mb = 4096
storage_mb = 2048
network_mode = {toml_quote("public")}
skills_dir = {toml_quote("/workspace/skills")}
"""
        tomllib.loads(task_content)
        (private_case / "task.toml").write_text(task_content, encoding="utf-8")
        (private_case / "instruction.md").write_text(
            "Replace this with the user-facing task instruction for the agent.\n", encoding="utf-8"
        )
        (env_dir / "Dockerfile").write_text(
            """FROM python:3.12-slim

RUN apt-get -o Acquire::Retries=3 update && \\
    apt-get -o Acquire::Retries=3 install -y --no-install-recommends bash curl git jq procps ripgrep && \\
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /workspace/skills /logs/agent /logs/verifier
WORKDIR /workspace
""",
            encoding="utf-8",
        )
        grader_path = tests_dir / ("grader.sh" if language == "shell" else "grader.py")
        _write_grader_file(grader_path, language=language)
        test_sh = tests_dir / "test.sh"
        test_sh.write_text(_native_test_sh(language), encoding="utf-8", newline="\n")
        test_sh.chmod(0o755)
        (private_harbor / "README.md").write_text(
            """# SkillEvaluator BYOT Harbor Tasks

This directory is user-owned. SkillEvaluator stages copies under eval
results and does not mutate these source files in place.

Keep the result contract stable:

- trajectory path: `/logs/agent/trajectory.json`
- reward JSON: `/logs/verifier/reward.json`
- reward text: `/logs/verifier/reward.txt`
- score range: `0.0` to `1.0`
- case IDs should match `evals/evals.json` when using `default` or `default_plus_custom`
""",
            encoding="utf-8",
        )

        copytree_secure(private_evals, evals_dir, replace_existing=True, allowed_root=private_root)

    console.print(f"Created Harbor BYOT starter at [cyan]{escape_markup(str(evals_dir / 'harbor'))}[/cyan]")
    return 0
