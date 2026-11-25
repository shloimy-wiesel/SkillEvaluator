"""Persistent project metadata and the controlled Git transport."""

import base64
import os
import re
import shutil
import sqlite3
import subprocess
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from cryptography.fernet import Fernet


class WorkspaceError(ValueError):
    """A safe, author-facing diagnostic."""


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    remote: str
    folder: str
    branch: str
    revision: str


class Workspace:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.repos = self.data_dir / "projects"
        self.repos.mkdir(mode=0o700, exist_ok=True)
        key = self.data_dir / "credential.key"
        if not key.exists():
            with os.fdopen(os.open(key, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as stream:
                stream.write(Fernet.generate_key())
        self.cipher = Fernet(key.read_bytes())
        self.db_path = self.data_dir / "studio.sqlite3"
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, remote TEXT NOT NULL,
                folder TEXT NOT NULL, branch TEXT NOT NULL, revision TEXT NOT NULL,
                credential BLOB)""")
            db.execute(
                "CREATE TABLE IF NOT EXISTS gitlab (project_id TEXT PRIMARY KEY, root TEXT NOT NULL, token BLOB)"
            )

    def projects(self):
        with closing(sqlite3.connect(self.db_path)) as db:
            return [
                Project(*r)
                for r in db.execute("SELECT id,name,remote,folder,branch,revision FROM projects ORDER BY rowid DESC")
            ]

    def get(self, project_id):
        with closing(sqlite3.connect(self.db_path)) as db:
            row = db.execute(
                "SELECT id,name,remote,folder,branch,revision FROM projects WHERE id=?", (project_id,)
            ).fetchone()
        return Project(*row) if row else None

    def checkout(self, project: Project):
        return self.repos / project.id

    def git(self, project: Project, args: list[str], *, authenticated=False, stdin=None, raw=False, index=None):
        """Run a server-constructed argv; credentials are scoped to the saved URL."""
        credential = None
        if authenticated:
            with closing(sqlite3.connect(self.db_path)) as db:
                (credential,) = db.execute("SELECT credential FROM projects WHERE id=?", (project.id,)).fetchone()
        from .gitlab import ca_file

        return self._git(
            self.checkout(project),
            args,
            credential,
            project.remote,
            stdin=stdin,
            raw=raw,
            index=index,
            ca=ca_file(self, project.id),
        )

    def connect(self, remote, folder, username="", token="", *, gitlab_root="", ca_pem=""):
        from .gitlab import ca_file, location, save_ca

        remote = remote.strip()
        try:
            parts = urlsplit(remote)
            _ = parts.port
        except ValueError as exc:
            raise WorkspaceError("Enter a valid HTTPS repository URL.") from exc
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.query
            or parts.fragment
            or "\\" in remote
            or not re.fullmatch(r"/[A-Za-z0-9_./~-]+", parts.path)
            or any(ord(c) <= 32 for c in remote)
        ):
            raise WorkspaceError("Enter an HTTPS repository URL without embedded credentials.")
        name = parts.path.rstrip("/").split("/")[-1].removesuffix(".git")
        if not name:
            raise WorkspaceError("Include the repository name in its URL.")
        folder = folder.strip() or "."
        if folder != "." and any(p.lower() in ("", ".", "..", ".git") for p in folder.split("/")):
            raise WorkspaceError("Choose a folder relative to the repository root.")
        if any(ord(c) < 32 or c == "\\" for c in folder):
            raise WorkspaceError("Choose a valid repository folder.")
        if bool(username) != bool(token) or ":" in username:
            raise WorkspaceError("For private access, provide both a Git username and an access token.")
        credential = self.cipher.encrypt(f"{username}:{token}".encode()) if token else None
        project_id = uuid4().hex
        repo = self.repos / project_id
        loc = location(remote, gitlab_root)
        ca = ca_file(self, project_id)
        try:
            if ca_pem:
                if not loc:
                    raise WorkspaceError("Provide the GitLab installation URL for this CA.")
                save_ca(self, project_id, ca_pem)
            self._git(self.repos, ["clone", "--", remote, project_id], credential, remote, ca=ca)
            skill = repo / folder / "SKILL.md"
            if any(path.is_symlink() for path in (skill, *skill.parents) if path.is_relative_to(repo)):
                raise WorkspaceError("Choose the actual skill folder, not a symbolic link.")
            if not skill.is_file():
                raise WorkspaceError("The selected folder must contain a SKILL.md file.")
            branch = self._git(repo, ["symbolic-ref", "--short", "HEAD"])
            revision = self._git(repo, ["rev-parse", "--verify", "HEAD"])
            with closing(sqlite3.connect(self.db_path)) as db, db:
                db.execute(
                    "INSERT INTO projects VALUES (?,?,?,?,?,?,?)",
                    (project_id, name, remote, folder, branch, revision, credential),
                )
                if loc:
                    db.execute("INSERT INTO gitlab(project_id,root) VALUES (?,?)", (project_id, loc[0]))
        except BaseException:
            ca.unlink(missing_ok=True)
            shutil.rmtree(repo, ignore_errors=True)
            raise
        return project_id

    def _git(self, cwd, args, credential=None, remote=None, *, stdin=None, raw=False, index=None, ca=None):
        env = {k: os.environ[k] for k in ("PATH", "GIT_SSL_CAINFO", "LANG") if k in os.environ}
        env.update(
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
            GIT_TERMINAL_PROMPT="0",
            GIT_ALLOW_PROTOCOL="https",
            GIT_ATTR_NOSYSTEM="1",
            HOME=str(self.data_dir),
        )
        if index is not None:
            env["GIT_INDEX_FILE"] = str(index)
        if ca and ca.is_file():
            env["GIT_SSL_CAINFO"] = str(ca)
        if credential:
            auth = base64.b64encode(self.cipher.decrypt(credential)).decode("ascii")
            env.update(
                GIT_CONFIG_COUNT="1",
                GIT_CONFIG_KEY_0=f"http.{remote}.extraHeader",
                GIT_CONFIG_VALUE_0=f"Authorization: Basic {auth}",
            )
        try:
            result = subprocess.run(
                [
                    "git",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "http.followRedirects=false",
                    "-c",
                    "credential.helper=",
                    "-c",
                    "submodule.recurse=false",
                    *args,
                ],
                cwd=cwd,
                env=env,
                capture_output=True,
                input=stdin,
                timeout=120,
                check=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise WorkspaceError(
                "Git could not open this repository. Check the URL, access and default branch."
            ) from exc
        return result.stdout if raw else result.stdout.decode("utf-8", errors="replace").strip()
