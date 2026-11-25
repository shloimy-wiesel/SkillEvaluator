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


def scoped_run_directory(root, skill):
    """Resolve one flat or skill-nested reservation, including unfinished history."""
    if root.resolve(strict=True) != root:
        raise ValueError("Linked artifact directory")
    candidate = _single_directory(root)
    if candidate.name == skill and not (candidate / "run_config.json").exists():
        return _single_directory(candidate)
    return candidate


def bounded_directory(root, skill=None):
    """Bound the artifact tree; skill-scoped history may include unfinished runs."""
    directory = native_directory(root) if skill is None else scoped_run_directory(root, skill)
    entries = 0
    pending = [directory]
    total = 0
    while pending:
        with os.scandir(pending.pop()) as scan:
            for entry in scan:
                entries += 1
                if entries > 16000 or entry.is_symlink():
                    raise ValueError("Linked or oversized artifact tree")
                if entry.is_dir(follow_symlinks=False):
                    pending.append(entry.path)
                    continue
                meta = entry.stat(follow_symlinks=False)
                if not entry.is_file(follow_symlinks=False) or meta.st_nlink != 1:
                    raise ValueError("Unsupported artifact type")
                if entry.name.endswith(".json") or entry.name.startswith("."):
                    total += meta.st_size
                    if meta.st_size > 8 * 1024**2 or total > 64 * 1024**2:
                        raise ValueError("Oversized retained evidence")
    return directory
