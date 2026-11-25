"""Resolve a Studio run's native result in place (generated markers are path-bound)."""

import os
import re


def _single_directory(root):
    candidates = []
    with os.scandir(root) as scan:
        for index, entry in enumerate(scan):
            if index >= 64:
                raise ValueError("Too many native directories")
            if entry.name == "latest" and entry.is_symlink():
                continue
            if entry.is_symlink():
                raise ValueError("Linked entry in native result root")
            if entry.is_dir(follow_symlinks=False):
                candidates.append(root / entry.name)
    if len(candidates) != 1:
        raise ValueError("Expected exactly one retained native run")
    return candidates[0]


def native_directory(root):
    if root.resolve(strict=True) != root:
        raise ValueError("Linked artifact directory")
    candidate = _single_directory(root)
    if not (candidate / "result.json").exists():
        # --results-dir/<skill>/<native-id>; older adapters used a flat root.
        candidate = _single_directory(candidate)
    result = candidate / "result.json"
    if result.resolve(strict=True) != result or not result.is_file():
        raise ValueError("No canonical native result")
    return candidate


def validate_agent_names(result, config):
    """Native readers may use recorded agent names as path components."""
    identity = result.get("comparison_identity", {})
    for source in (config, result, result.get("run_config", {}), identity.get("config", {})):
        agents = source.get("agents", {})
        if (
            not isinstance(agents, dict)
            or len(agents) > 32
            or any(not re.fullmatch(r"[\w-][\w.-]{0,127}", name) for name in agents)
        ):
            raise ValueError("Invalid retained agent names")
