"""Inert previews of a completed run's retained text artifacts."""

import hashlib
import json
import os
import stat
from contextlib import closing, contextmanager
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import HTTPException

from skillevaluator.utils.redaction import redact_sensitive_data, redact_sensitive_text

from .native_location import native_directory, validate_agent_names
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
    "dataset_snapshot.json",
    "what_to_fix.json",
    "pass_at_k_lift.json",
    "custom_lift.json",
    "security_attribution.json",
}


def scrubber(workspace, project, *, extra_secrets=()):
    with closing(database(workspace)) as db:
        secrets = [load(db, workspace, project, role).get("key") for role in ("chat", "embeddings")]
        gitlab = db.execute("SELECT token FROM gitlab WHERE project_id=?", (project,)).fetchone()
        if gitlab and gitlab[0]:
            secrets.append(workspace.cipher.decrypt(gitlab[0]).decode())
    secrets.extend(extra_secrets)
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
        allowed = NAMES
        if "_harbor-jobs" in parent.relative_to(root).parts:
            allowed = allowed | {"config.json", "trial.log", "job.log", "exception.txt"}
            if parent.name == "verifier":
                allowed |= {"test-stdout.txt", "test-stderr.txt", "reward.txt"}
        for name in sorted(allowed.intersection(names)):
            path = parent / name
            try:
                meta = path.lstat()
                relative = path.relative_to(root).as_posix().encode("utf-8")
            except (OSError, UnicodeError):
                continue
            if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1:
                continue
            files[hashlib.sha256(relative).hexdigest()] = path
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
        self.sections = [("Report", [])]
        self.heading = None

    def handle_starttag(self, tag, _attrs):
        if tag in {"script", "style"}:
            self.hidden = True
        elif tag in {"h1", "h2", "h3", "h4"} and not self.hidden:
            self.heading = []

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = False
        elif tag in {"h1", "h2", "h3", "h4"} and self.heading is not None:
            self.sections.append((" ".join(self.heading) or "Section", []))
            self.heading = None

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.lines.append(data.strip())
            (self.sections[-1][1] if self.heading is None else self.heading).append(data.strip())


def read_artifact(path, limit):
    """Open every component without following links, and bound the actual read."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:-1]:
            nxt = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = nxt
        with os.fdopen(os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=fd), "rb") as stream:
            meta = os.fstat(stream.fileno())
            if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1:
                raise HTTPException(404, "Unknown artifact")
            if meta.st_size > limit or len(data := stream.read(limit + 1)) > limit:
                raise HTTPException(413, "File exceeds the review limit")
            return data
    except OSError as exc:
        raise HTTPException(404, "Unknown artifact") from exc
    finally:
        os.close(fd)


def preview(path, scrub, *, sections=False):
    try:
        text = read_artifact(path, 8 * 1024**2).decode("utf-8")
        if path.suffix == ".html":
            parser = ReportText()
            parser.feed(text)
            if sections:
                return [
                    (scrub(title), scrub("\n".join(lines)))
                    for title, lines in parser.sections
                    if lines or title != "Report"
                ]
            text = "\n".join(parser.lines)
        elif path.suffix == ".json":
            return json.dumps(
                mask_strings(redact_sensitive_data(json.loads(text)), scrub), indent=2, ensure_ascii=False
            )
        return scrub(text)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise HTTPException(422, "Cannot display this artifact") from exc


def native_results(root, paths):
    try:
        result = native_directory(root) / "result.json"
    except (ValueError, OSError, RuntimeError):
        return []
    return [result] if result in paths else []


@contextmanager
def input_projection(root, run):
    """Give native readers a bounded, link-free copy; keep writes away from retained evidence."""
    files = inventory(root).values()
    results = native_results(root, files)
    if len(results) != 1:
        raise ValueError("No unambiguous native run.")
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
                raise ValueError("Native input exceeds the review limit.")
            target = selected / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(read_artifact(path, size))
        config = selected / "run_config.json"
        validate_agent_names(
            json.loads((selected / "result.json").read_bytes()),
            json.loads(config.read_bytes()) if config.exists() else {},
        )
        skill = Path(temp) / "inputs" / (Path(run["folder"]).name or "skill")
        yield selected, skill


def native_dashboard(root, run):
    from skillevaluator.reporting.dashboard_data import DashboardData, load_retained_dashboard

    try:
        with input_projection(root, run) as (selected, skill):
            data = load_retained_dashboard(selected, skill_path=skill)
        for row in data.rows:
            row["source"] = run["id"]
        data.warnings = [w.replace(str(selected), run["id"]) for w in data.warnings]
        return data
    except (ValueError, TypeError, AttributeError, OSError, RecursionError):
        return DashboardData(
            warnings=[f"{run['id']}: native evidence missing, unreadable or too large. Use saved report."]
        )


def report_preview(root, run, files, scrub):
    from skillevaluator.evaluation.tier3_feedback_chat import saved_feedback_for_run
    from skillevaluator.evaluation.tier3_report import render_agent_eval_html_report

    results = native_results(root, files)
    if len(results) == 1 and (report := results[0].with_name("report.html")) in files:
        return preview(report, scrub, sections=True)
    try:
        with input_projection(root, run) as (selected, skill):
            result = json.loads((selected / "result.json").read_text())
            report = render_agent_eval_html_report(
                skill,
                selected,
                engine_result=result,
                use_llm_judge=False,
                saved_feedback=saved_feedback_for_run(result, selected),
            )
            return preview(report, scrub, sections=True)
    except (ValueError, TypeError, AttributeError, OSError, RecursionError) as exc:
        raise HTTPException(422, "Cannot rebuild this run's report.") from exc


def compare(roots, skill, scrub):
    """The engine picks the first scoreable summary per agent, in Studio history order."""
    from rich.console import Console

    from skillevaluator.tier3.commands import render_agent_comparison

    with TemporaryDirectory() as temp:
        directories = []
        budget = 64 * 1024**2
        for index, root in enumerate(roots):
            files = inventory(root).values()
            results = native_results(root, files)
            if not results:
                continue
            native = results[0].parent
            selected = Path(temp) / str(index) / native.name
            selected.mkdir(parents=True)
            # A canonical result exists here: never interpret its summaries as pre-result legacy output.
            (selected / "result.json").touch()
            directories.append(selected)
            for path in files:
                if not path.is_relative_to(native) or path.name not in ("summary.json", "lift.json"):
                    continue
                relative = path.relative_to(native)
                if len(relative.parts) not in (2, 3) or relative.parts[0].startswith("_"):
                    continue
                data = read_artifact(path, min(8 * 1024**2, budget))
                budget -= len(data)
                target = selected / relative
                target.parent.mkdir(exist_ok=True, parents=True)
                target.write_bytes(data)
        buffer = StringIO()
        render_agent_comparison(skill, [directories], Console(file=buffer, width=140, color_system=None))
        return scrub(buffer.getvalue())
