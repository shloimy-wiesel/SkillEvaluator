"""Inert previews of a completed run's retained text artifacts."""

import hashlib
import json
import os
from contextlib import closing
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import HTTPException

from skillevaluator.utils.redaction import redact_sensitive_data, redact_sensitive_text

from .providers import database, load

NAMES = {
    "report.html",
    "tier3-benchmark.md",
    "result.json",
    "summary.json",
    "reward.json",
    "trajectory.json",
    "run_config.json",
    "comparison.json",
    "lift.json",
    "findings.json",
    "attempt_policy.json",
}


def scrubber(workspace, project):
    with closing(database(workspace)) as db:
        secrets = [load(db, workspace, project, role).get("key") for role in ("chat", "embeddings")]
        gitlab = db.execute("SELECT token FROM gitlab WHERE project_id=?", (project,)).fetchone()
        if gitlab and gitlab[0]:
            secrets.append(workspace.cipher.decrypt(gitlab[0]).decode())
    secrets.append(workspace.host_token(workspace.get(project)))
    secrets = sorted(filter(None, secrets), key=len, reverse=True)

    def scrub(text):
        for secret in secrets:
            text = text.replace(secret, "<redacted>")
        return redact_sensitive_text(text)

    return scrub


def inventory(root):
    files = {}
    if root.resolve() != root or not root.is_dir():
        return files
    visited = 0
    for directory, dirs, names in os.walk(root):
        visited += len(dirs) + len(names)
        if visited > 100_000:
            raise HTTPException(413, "Too many retained files to index")
        parent = Path(directory)
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (parent / d).is_symlink())
        for name in sorted(NAMES.intersection(names)):
            path = parent / name
            if path.resolve() != path or not path.is_file() or path.stat().st_nlink != 1:
                continue
            relative = path.relative_to(root).as_posix()
            files[hashlib.sha256(relative.encode()).hexdigest()] = path
    return files


def mask_strings(value, scrub):
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        return {scrub(k): mask_strings(v, scrub) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_strings(v, scrub) for v in value]
    return value


class ReportText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = False
        self.lines = []

    def handle_starttag(self, tag, _attrs):
        if tag in {"script", "style"}:
            self.hidden = True

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = False

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.lines.append(data.strip())


def preview(path, scrub):
    if path.stat().st_size > 8 * 1024**2:
        raise HTTPException(413, "File exceeds the 8 MiB preview limit")
    try:
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".html":
            parser = ReportText()
            parser.feed(text)
            text = "\n".join(parser.lines)
        elif path.suffix == ".json":
            return json.dumps(
                mask_strings(redact_sensitive_data(json.loads(text)), scrub), indent=2, ensure_ascii=False
            )
        return scrub(text)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise HTTPException(422, "Cannot display this artifact") from exc


def native_results(root, paths):
    return [
        p
        for p in paths
        if p.name == "result.json"
        and len(p.relative_to(root).parts) in (2, 3)
        and not any(part.startswith("_") for part in p.relative_to(root).parts)
    ]


def native_dashboard(root, run):
    from skillevaluator.reporting.dashboard_data import DashboardData, load_retained_dashboard

    files = inventory(root).values()
    results = native_results(root, files)
    if len(results) != 1 or results[0].with_name("run_config.json") not in files:
        return DashboardData(warnings=[f"{run['id']}: native run or configuration unavailable."])
    native = results[0].parent
    with TemporaryDirectory() as temp:
        selected = Path(temp) / "results" / native.name
        total = 0
        for path in files:
            if not path.is_relative_to(native) or path.suffix != ".json":
                continue
            relative = path.relative_to(native)
            if relative.parts[0].startswith("_"):
                continue
            size = path.stat().st_size
            total += size
            if size > 16 * 1024**2 or total > 64 * 1024**2:
                return DashboardData(
                    warnings=[f"{run['id']}: native input exceeds the dashboard limit. Use saved report."]
                )
            target = selected / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
        skill = Path(temp) / "inputs" / (Path(run["folder"]).name or "skill")
        try:
            data = load_retained_dashboard(selected, skill_path=skill)
        except (ValueError, TypeError, AttributeError, OSError, RecursionError):
            return DashboardData(warnings=[f"{run['id']}: unreadable native evidence."])
        for row in data.rows:
            row["source"] = run["id"]
        data.warnings = [w.replace(str(selected), run["id"]) for w in data.warnings]
        return data


def compare(root, skill, scrub):
    """Project only authorized native summaries into a read-only engine input set."""
    from rich.console import Console

    from skillevaluator.tier3.commands import render_agent_comparison

    files = inventory(root).values()
    native = [p.parent for p in native_results(root, files)]
    if len(native) != 1:
        return "No unambiguous retained result directory."
    with TemporaryDirectory() as temp:
        selected = Path(temp) / native[0].name
        selected.mkdir()
        for path in files:
            if not path.is_relative_to(native[0]) or path.name not in ("summary.json", "lift.json"):
                continue
            relative = path.relative_to(native[0])
            if len(relative.parts) not in (2, 3):
                continue
            target = selected / relative
            target.parent.mkdir(exist_ok=True, parents=True)
            target.write_text(preview(path, scrub))
        buffer = StringIO()
        render_agent_comparison(skill, [[selected]], Console(file=buffer, width=140, color_system=None))
        return scrub(buffer.getvalue())
