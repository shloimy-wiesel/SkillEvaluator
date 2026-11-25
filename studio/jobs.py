"""Single-volume queue for trusted, typed evaluator adapters."""

import json
import re
import shutil
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from .workspace import Project, Workspace, WorkspaceError


@dataclass(frozen=True)
class JobContext:
    root: Path
    skill: Path
    revision: str
    progress: Callable[[str], None]
    workspace: Workspace
    project_id: str
    run_id: str
    artifacts: Path

    def input_file(self, relative: str) -> Path:
        """Resolve a repository-relative input (e.g. dataset) at this job's SHA."""
        parts = relative.split("/")
        if any(p.lower() in ("", ".", "..", ".git") for p in parts) or "\\" in relative:
            raise WorkspaceError("Choose a regular file inside the pinned repository.")
        path = self.root.joinpath(*parts)
        if path.resolve() != path or not path.is_file():
            raise WorkspaceError("Selected file is absent or linked at this commit.")
        return path


@dataclass(frozen=True)
class Outcome:
    status: Literal["passed", "failed", "incomplete", "skipped", "neutral", "not_run"]
    exit_code: int
    report: str  # Engine JSON report
    markdown: str


@dataclass(frozen=True)
class JobDefinition[Options: BaseModel]:
    kind: str
    options: type[Options]
    evaluate: Callable[[JobContext, Options], Outcome]


class Jobs:
    def __init__(self, workspace: Workspace, definitions):
        self.workspace = workspace
        self.definitions = {d.kind: d for d in definitions}
        if len(self.definitions) != len(definitions):
            raise ValueError("Job kinds must be unique")
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="studio-job")
        with self.connection() as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, sha TEXT NOT NULL, folder TEXT NOT NULL,
                kind TEXT NOT NULL, options TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
                progress TEXT NOT NULL DEFAULT 'Waiting for worker', exit_code INTEGER,
                report TEXT, markdown TEXT, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
            db.execute("""UPDATE runs SET status='interrupted',progress='Worker stopped before saving a result.'
                WHERE status IN ('queued','running')""")
        # A killed worker may have left a private checkout, even if it had
        # just finished committing its reports. Never resume its evaluation.
        for area in (workspace.data_dir / "jobs").glob("*"):
            with self.connection() as db:
                row = db.execute("SELECT project_id FROM runs WHERE id=?", (area.name,)).fetchone()
            if row and (project := workspace.get(row["project_id"])):
                self._cleanup(project, area)

    def connection(self):
        db = sqlite3.connect(self.workspace.db_path)
        db.row_factory = sqlite3.Row
        return closing(db)

    def history(self, project_id: str):
        with self.connection() as db:
            return db.execute(
                "SELECT id,sha,folder,kind,status,created FROM runs WHERE project_id=? ORDER BY rowid DESC",
                (project_id,),
            ).fetchall()

    def get(self, project_id: str, run_id: str):
        with self.connection() as db:
            return db.execute("SELECT * FROM runs WHERE project_id=? AND id=?", (project_id, run_id)).fetchone()

    def enqueue[Options: BaseModel](
        self, project: Project, sha: str, definition: JobDefinition[Options], options: Options
    ) -> str:
        if self.definitions.get(definition.kind) is not definition or not isinstance(options, definition.options):
            raise ValueError("Unregistered job type or invalid options")
        if not re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", sha):
            raise WorkspaceError("Choose a full commit SHA in this project.")
        git = self.workspace.git
        if git(project, ["cat-file", "-t", sha]) != "commit":
            raise WorkspaceError("Choose a commit in this project.")
        run_id = uuid4().hex
        git(project, ["update-ref", f"refs/studio/runs/{run_id}", sha])
        with self.connection() as db, db:
            db.execute(
                "INSERT INTO runs(id,project_id,sha,folder,kind,options) VALUES(?,?,?,?,?,?)",
                (run_id, project.id, sha, project.folder, definition.kind, options.model_dump_json()),
            )
        self.pool.submit(self._run, project, run_id)
        return run_id

    def rerun(self, project: Project, run_id: str) -> str:
        row = self.get(project.id, run_id)
        if row is None or row["kind"] not in self.definitions:
            raise WorkspaceError("This job type is unavailable.")
        if row["status"] in {"queued", "running"}:
            raise WorkspaceError("This run is still active.")
        definition = self.definitions[row["kind"]]
        try:
            options = definition.options.model_validate_json(row["options"])
        except ValidationError as exc:
            raise WorkspaceError("This saved configuration is no longer supported.") from exc
        return self.enqueue(replace(project, folder=row["folder"]), row["sha"], definition, options)

    @staticmethod
    def _root(project, area):
        return area / (project.name if project.name.lower() not in (".", "..", ".git") else "repository")

    def _cleanup(self, project, area):
        root = self._root(project, area)
        try:
            if root.exists():
                self.workspace.git(project, ["worktree", "remove", "--force", str(root)])
        except WorkspaceError:
            # Interrupted checkout may not have finished registering itself.
            shutil.rmtree(root)
            self.workspace.git(project, ["worktree", "prune"])
        if area.exists():
            # A killed adapter may also leave private scratch directories beside its checkout.
            shutil.rmtree(area)

    def _run(self, project: Project, run_id: str):
        record = self.get(project.id, run_id)
        area = self.workspace.data_dir / "jobs" / run_id
        root = self._root(project, area)
        git = self.workspace.git

        def progress(message: str):
            with self.connection() as db, db:
                db.execute("UPDATE runs SET status='running', progress=? WHERE id=?", (message, run_id))

        try:
            progress("Preparing detached commit")
            tree = git(project, ["ls-tree", "-rlz", record["sha"]])
            total = 0
            entries = tree.rstrip("\0").split("\0") if tree else []
            if len(entries) > 100_000:
                raise WorkspaceError("Repository exceeds the Studio run entry limit.")
            for entry in entries:
                header, _, name = entry.partition("\t")
                mode, _, _, size = header.split()
                if mode == "160000":
                    if Path(name).is_relative_to(record["folder"]):
                        raise WorkspaceError("The selected skill contains an unavailable submodule.")
                    continue
                total += int(size)
                if total > 512 * 1024**2 or int(size) > 64 * 1024**2:
                    raise WorkspaceError("Repository exceeds the Studio run size limit.")
            area.mkdir(parents=True)
            git(project, ["worktree", "add", "--detach", str(root), record["sha"]])
            skill = root / record["folder"]
            if skill.resolve() != skill or not skill.is_relative_to(root) or not (skill / "SKILL.md").is_file():
                raise WorkspaceError("Selected skill is absent or linked at this commit.")
            for path in root.rglob("*"):
                if path.is_symlink():
                    target = path.resolve()
                    if path.is_relative_to(skill) or not target.is_relative_to(root) or ".git" in target.parts:
                        raise WorkspaceError("Run input contains an unsupported symbolic link.")
            definition = self.definitions[record["kind"]]
            artifacts = self.workspace.data_dir / "artifacts" / project.id / run_id
            artifacts.mkdir(mode=0o700, parents=True)
            outcome = definition.evaluate(
                JobContext(root, skill, record["sha"], progress, self.workspace, project.id, run_id, artifacts),
                definition.options.model_validate_json(record["options"]),
            )
            json.loads(outcome.report)
            with self.connection() as db, db:
                db.execute(
                    "UPDATE runs SET status=?,exit_code=?,progress='Results saved',report=?,markdown=? WHERE id=?",
                    (outcome.status, outcome.exit_code, outcome.report, outcome.markdown, run_id),
                )
        except Exception as exc:
            with self.connection() as db, db:
                db.execute(
                    "UPDATE runs SET status='error', progress=? WHERE id=?",
                    (str(exc) if isinstance(exc, WorkspaceError) else "Evaluator could not finish.", run_id),
                )
        finally:
            self._cleanup(project, area)
