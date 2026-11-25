"""Revision-bound operations on a project's author checkout."""

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock, RLock

from .workspace import WorkspaceError


class Conflict(WorkspaceError):
    """The submitted editor snapshot is no longer current."""


_locks = {}
_guard = Lock()


def project_lock(ws, project_id):
    with _guard:
        return _locks.setdefault((ws.data_dir, project_id), RLock())


def require_base(project, branch, revision):
    """Bind submitted form fields to a trusted Workspace.get() snapshot."""
    if (branch, revision) != (project.branch, project.revision):
        raise Conflict("The checkout changed. Reopen the editor and review your draft.")
    return project


def _check(ws, p):
    current = ws.get(p.id)
    root = ws.checkout(p)
    if (
        current != p
        or root.resolve() != root
        or (root / ".git").is_symlink()
        or not (root / ".git").is_dir()
        or ws.git(p, ["symbolic-ref", "HEAD"]) != f"refs/heads/{p.branch}"
        or ws.git(p, ["rev-parse", "HEAD"]) != p.revision
        or ws.git(p, ["status", "--porcelain", "--untracked-files=all"])
    ):
        raise Conflict("The checkout changed. Reopen the branch before saving.")


def branches(ws, p):
    lines = ws.git(p, ["ls-remote", "--heads", "--", p.remote], authenticated=True)
    return {ref.removeprefix("refs/heads/"): sha for sha, ref in (line.split("\t") for line in lines.splitlines())}


def _branch(ws, p, name):
    if not name or name.startswith("-") or name == "HEAD" or any(ord(c) < 32 for c in name):
        raise WorkspaceError("Choose a valid Git branch name.")
    try:
        ws.git(p, ["check-ref-format", f"refs/heads/{name}"])
    except WorkspaceError as exc:
        raise WorkspaceError("Choose a valid Git branch name.") from exc


def _record(ws, p, branch, sha):
    with closing(sqlite3.connect(ws.db_path)) as db, db:
        db.execute("UPDATE projects SET branch=?,revision=? WHERE id=?", (branch, sha, p.id))


def _push(ws, p, sha, branch, expected):
    # A normal fast-forward push alone can recreate a just-deleted branch.
    # Only this trusted, application-owned hook sees the advertisement for the actual push.
    hooks = Path(__file__).resolve().with_name("git-hooks")
    if not os.access(hooks / "pre-push", os.X_OK):
        raise WorkspaceError("The Studio push guard is missing. Check the installation.")
    try:
        ws.git(
            p,
            [
                "-c",
                f"core.hooksPath={hooks}",
                "-c",
                f"studio.expectedRemoteTip={expected}",
                "push",
                "--",
                p.remote,
                f"{sha}:refs/heads/{branch}",
            ],
            authenticated=True,
        )
    except WorkspaceError as exc:
        raise Conflict("Push was not confirmed. Check remote access and reopen the branch.") from exc


def _file(ws, p, name, repo_root=False):
    if (
        any(part.lower() in ("", ".", "..", ".git") for part in name.split("/"))
        or "\\" in name
        or any(ord(c) < 32 for c in name)
    ):
        raise WorkspaceError("Choose a file inside the skill folder.")
    root = ws.checkout(p)
    path = (root if repo_root else root / p.folder) / name
    if not path.is_relative_to(root) or any(
        parent.is_symlink() for parent in (path, *path.parents) if parent.is_relative_to(root)
    ):
        raise WorkspaceError("Symbolic links are not editable.")
    return path


def _entry(ws, p, name, repo_root):
    path = _file(ws, p, name, repo_root)
    root = ws.checkout(p)
    rel = path.relative_to(root).as_posix()
    for parent in path.parents:
        if parent == root:
            break
        if parent.exists() and (not parent.is_dir() or (parent / ".git").exists()):
            raise WorkspaceError("Choose a regular directory within this repository.")
    # Validate the tree too: an uninitialized submodule can have an empty directory.
    parts = rel.split("/")
    for i in range(1, len(parts) + 1):
        entry = ws.git(p, ["--literal-pathspecs", "ls-tree", p.revision, "--", "/".join(parts[:i])])
        if not entry:
            if path.exists():
                raise Conflict("An untracked file occupies this path.")
            return rel, None, None
        mode, _, oid = entry.split("\t", 1)[0].split()
        if i < len(parts) and mode != "040000":
            raise WorkspaceError("Choose a regular directory within this repository.")
    if mode not in ("100644", "100755"):
        raise WorkspaceError("Choose a regular file within this repository.")
    return rel, mode, oid


def read_file(ws, p, name, *, repo_root=False):
    with project_lock(ws, p.id):
        _check(ws, p)
        _, _, oid = _entry(ws, p, name, repo_root)
        return ws.git(p, ["cat-file", "blob", oid], raw=True) if oid else None


def commit_changes(ws, p, changes, message, *, repo_root=False):
    """Publish one direct child of the expected revision, leaving no dirty state on rejection."""
    with project_lock(ws, p.id), TemporaryDirectory(dir=ws.data_dir) as temp:
        _check(ws, p)
        if branches(ws, p).get(p.branch) != p.revision:
            raise Conflict("The remote branch changed. Switch to its latest revision and review your draft.")
        index = Path(temp) / "index"
        ws.git(p, ["read-tree", p.revision], index=index)
        for name, data in changes.items():
            rel, mode, _ = _entry(ws, p, name, repo_root)
            if data is None:
                ws.git(p, ["update-index", "--force-remove", "--", rel], index=index)
            else:
                blob = ws.git(p, ["hash-object", "-w", "--stdin"], stdin=data)
                ws.git(p, ["update-index", "--add", "--cacheinfo", mode or "100644", blob, rel], index=index)
        tree = ws.git(p, ["write-tree"], index=index)
        if tree == ws.git(p, ["rev-parse", "HEAD^{tree}"]):
            raise WorkspaceError("There are no changes to save.")
        sha = ws.git(
            p,
            [
                "-c",
                "user.name=Studio",
                "-c",
                "user.email=studio@localhost",
                "commit-tree",
                tree,
                "-p",
                p.revision,
                "-m",
                message,
            ],
        )
        _push(ws, p, sha, p.branch, p.revision)
        ws.git(p, ["checkout", "--no-overwrite-ignore", "-B", p.branch, sha, "--"])
        _record(ws, p, p.branch, sha)
        return sha


def open_branch(ws, p, source, expected_source, new=None):
    with project_lock(ws, p.id):
        _check(ws, p)
        _branch(ws, p, source)
        heads = branches(ws, p)
        if heads.get(source) != expected_source:
            raise Conflict("The source branch changed. Review the latest revision and try again.")
        if new is not None:
            _branch(ws, p, new)
            if new in heads:
                raise Conflict("That branch already exists.")
        ws.git(p, ["fetch", "--no-tags", "--", p.remote, f"refs/heads/{source}"], authenticated=True)
        sha = ws.git(p, ["rev-parse", "FETCH_HEAD"])
        if sha != heads[source]:
            raise Conflict("The source branch changed. Try again.")
        path = _file(ws, p, "SKILL.md").relative_to(ws.checkout(p)).as_posix()
        entry = ws.git(p, ["--literal-pathspecs", "ls-tree", sha, "--", path])
        if not entry.startswith(("100644 blob ", "100755 blob ")):
            raise WorkspaceError("That branch does not contain a regular SKILL.md in this folder.")
        target = source if new is None else new
        if new is not None:
            _push(ws, p, sha, target, "0" * len(sha))
        ws.git(p, ["checkout", "--no-overwrite-ignore", "-B", target, sha, "--"])
        _file(ws, p, "SKILL.md")
        _record(ws, p, target, sha)
