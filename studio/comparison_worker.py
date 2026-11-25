"""Private native reader. Only completed, immutable Studio artifact trees enter here."""

import json
import os
import re
import resource
import sys
from pathlib import Path

from skillevaluator.tier3.history import history_directories, history_from_directories, history_sort_key
from skillevaluator.tier3.results_location import run_directory_sort_key
from skillevaluator.tier3.version_comparison import compare_versions, select_prior_candidates

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


def validate_agents(result, config):
    identity = result.get("comparison_identity", {})
    for source in (config, result, result.get("run_config", {}), identity.get("config", {})):
        agents = source.get("agents", {})
        if (
            not isinstance(agents, dict)
            or len(agents) > 32
            or any(not re.fullmatch(r"[\w-][\w.-]{0,127}", name) for name in agents)
        ):
            raise ValueError("Invalid retained agent names")


def scoped_directory(root, sha, skill):
    directory = bounded_directory(root)
    if directory.parent != root and directory.parent.name != skill:
        raise ValueError("Different skill in results directory")
    if directory not in history_directories(directory.parent):
        raise ValueError("Unrecognized native directory")
    config = json.loads((directory / "run_config.json").read_bytes())
    validate_agents(json.loads((directory / "result.json").read_bytes()), config)
    if config.get("evaluated_source", {}).get("commit") != sha:
        raise ValueError("Different source revision")
    return directory


def inspect(root, sha, skill):
    directory = scoped_directory(root, sha, skill)
    rows = history_from_directories([directory], skill)["rows"]
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
    if not run_directory_sort_key(directory, require_completed_result=True):
        return None, summary, "No completed native comparison evidence."
    return directory, summary, None


def catalog(volume, project, query):
    directories = {}
    for run, sha in query["runs"]:
        root = Path(volume) / "artifacts" / project / run / "tier3"
        try:
            directories[run] = scoped_directory(root, sha, query["skill"])
        except (OSError, ValueError, AttributeError, TypeError, RuntimeError):
            continue
    if query["action"] == "compare":
        completed = {
            path: key
            for path in directories.values()
            if (key := run_directory_sort_key(path, require_completed_result=True))
        }
        ordered = sorted(completed, key=completed.get, reverse=True)
        current = next(iter(ordered), None) if query["current"] == "latest" else directories.get(query["current"])
        if current not in completed:
            return {"status": "unavailable", "reasons": ["No completed current run in this results scope."]}
        if query["prior"] == "latest":
            identity = json.loads((current / "result.json").read_bytes()).get("comparison_identity", {})
            selected = select_prior_candidates(ordered, "latest", identity, current_run_dir=current)
            if selected["status"] != "available":
                for rejected in selected.get("rejected_candidates", []):
                    rejected["reasons"] = [safe_reason(r) for r in rejected["reasons"]]
                return selected
            prior = Path(selected["source_run_dir"])
        else:
            prior = directories.get(query["prior"])
        if prior not in completed:
            return {"status": "unavailable", "reasons": ["No completed prior run in this results scope."]}
        report = compare_versions(current, prior)
        report["source_studio_run"] = next(run for run, path in directories.items() if path == prior)
        report.pop("source_run_dir", None)
        report["reasons"] = [safe_reason(r) for r in report["reasons"]]
        return report
    trend = history_from_directories(sorted(directories.values(), key=history_sort_key), project, query.get("agent"))
    for row in trend["rows"]:
        row["lift_reasons"] = [safe_reason(r) for r in row["lift_reasons"]]
    return trend


def main():
    resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    volume, project = sys.argv[1:]
    query = json.load(sys.stdin)
    if query["action"] != "pair":
        json.dump(catalog(volume, project, query), sys.stdout, allow_nan=False)
        return
    dirs, history, reasons = [], [], []
    for label, run in zip(("Prior", "Current"), query["runs"], strict=True):
        directory, rows, reason = None, [], None
        if run:
            try:
                directory, rows, reason = inspect(
                    Path(volume) / "artifacts" / project / run[0] / "tier3", run[1], query["skill"]
                )
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
