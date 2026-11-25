"""Private native reader. Only completed, immutable Studio artifact trees enter here."""

import json
import os
import re
import resource
import sys
from pathlib import Path

from skillevaluator.tier3.history import collect_history, history_directories
from skillevaluator.tier3.version_comparison import compare_versions

# Isolated Python omits the script directory; import only trusted Studio code.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_location import native_directory


def bounded_directory(root):
    directory = native_directory(root)
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


def safe_reason(reason):
    # Native read errors and configuration values can contain absolute run paths.
    return re.sub(r"(?<!\w)/[^\s'\",;)\]]+", "[path]", str(reason))[:320]


def inspect(root, sha):
    directory = bounded_directory(root)
    root = directory.parent
    result = json.loads((directory / "result.json").read_bytes())
    config_path = directory / "run_config.json"
    config = json.loads(config_path.read_bytes()) if config_path.exists() else {}
    identity = result.get("comparison_identity", {})
    for source in (config, result, result.get("run_config", {}), identity.get("config", {})):
        agents = source.get("agents", {})
        if (
            not isinstance(agents, dict)
            or len(agents) > 32
            or any(not re.fullmatch(r"[\w-][\w.-]{0,127}", name) for name in agents)
        ):
            raise ValueError("Invalid retained agent names")
    if directory not in history_directories(root):
        raise ValueError("Unrecognized run directory")
    # The primary root is populated above; do not allow native fallback discovery.
    rows = collect_history(root, results_dir=root.parent)["rows"]
    if len(rows) > 32:
        raise ValueError("Too many native history rows")
    summary = [
        {
            **{k: row[k] for k in ("with_skill_score", "without_skill_score", "lift_delta", "coverage")},
            **{k: str(row[k])[:256] if isinstance(row[k], str) else None for k in ("agent", "model", "status")},
            "lift_reasons": [safe_reason(r) for r in row["lift_reasons"][:8]],
        }
        for row in rows
        if row["run_id"] == directory.name
    ]
    if config.get("evaluated_source", {}).get("commit") != sha:
        return None, [], "Native source revision is missing or disagrees with the selected commit."
    return directory, summary, None


def main():
    resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    volume, project = sys.argv[1:]
    dirs, history, reasons = [], [], []
    for label, run in zip(("Prior", "Current"), json.load(sys.stdin), strict=True):
        directory, rows, reason = None, [], None
        if run:
            try:
                directory, rows, reason = inspect(Path(volume) / "artifacts" / project / run[0] / "tier3", run[1])
            except (OSError, ValueError, KeyError, AttributeError, TypeError, RuntimeError, OverflowError):
                reason = "Native evidence is missing, malformed, linked or exceeds inspection limits."
        else:
            reason = "No terminal live evaluation report selected."
        if reason:
            reasons.append(f"{label}: {reason}")
        dirs.append(directory)
        history.append(rows)
    comparison = {"status": "unavailable", "reasons": reasons}
    if all(dirs):
        native = compare_versions(dirs[1], dirs[0])
        comparison = {
            "status": native["status"],
            "reasons": [safe_reason(r) for r in native["reasons"][:12]],
            "agents": {
                name: {k: values[k] for k in ("prior_overall", "current_overall", "delta")}
                for name, values in native["agents"].items()
            },
        }
    json.dump({"comparison": comparison, "history": history}, sys.stdout, allow_nan=False)


if __name__ == "__main__":
    main()
