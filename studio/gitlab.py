"""A GitLab project's origin, trust and API access are bound to its clone URL."""

import http.client
import json
import os
import re
import sqlite3
import ssl
from contextlib import closing
from dataclasses import dataclass
from urllib.parse import quote, urlencode, urlsplit

from .workspace import WorkspaceError


def location(remote, root):
    origin = urlsplit(remote)
    root = root.strip().rstrip("/")
    if not root:
        if origin.netloc.lower() != "gitlab.com":
            return None
        root = "https://gitlab.com"
    try:
        base = urlsplit(root)
    except ValueError:
        raise WorkspaceError("Enter the GitLab installation URL on the repository host.") from None
    if (
        base.scheme != "https"
        or origin.netloc.lower() != base.netloc.lower()
        or base.query
        or base.fragment
        or not origin.path.startswith(base.path + "/")
        or not re.fullmatch(r"https://[^\s?#\\]+", root)
        or any(p in ("", ".", "..") for p in origin.path.rstrip("/").split("/")[1:])
    ):
        raise WorkspaceError("GitLab installation URL must match the repository HTTPS host, port and path prefix.")
    namespace = origin.path[len(base.path) + 1 :].rstrip("/").removesuffix(".git")
    if "/" not in namespace or not namespace.rsplit("/", 1)[-1]:
        raise WorkspaceError("Include the GitLab namespace and project after the installation URL.")
    return root, namespace


def ca_file(ws, project_id):
    return ws.data_dir / f"{project_id}.ca.pem"


def save_ca(ws, project_id, pem):
    try:
        if len(pem) > 262144 or not re.fullmatch(
            r"(?:\s*-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\s]+-----END CERTIFICATE-----\s*)+", pem
        ):
            raise ValueError
        ssl.create_default_context(cadata=pem)
    except (ValueError, ssl.SSLError):
        raise WorkspaceError("Paste a PEM CA certificate bundle.") from None
    ca_file(ws, project_id).write_text(pem, encoding="ascii")


@dataclass(frozen=True)
class GitLab:
    workspace: object
    project_id: str
    root: str
    namespace: str

    @property
    def web_url(self):
        return f"{self.root}/{self.namespace}"

    def set_token(self, token):
        if token and not re.fullmatch(r"[!-~]{1,4096}", token):
            raise WorkspaceError("Enter a valid GitLab API token.")
        encrypted = self.workspace.cipher.encrypt(token.encode()) if token else None
        with closing(sqlite3.connect(self.workspace.db_path)) as db, db:
            db.execute(
                "INSERT INTO gitlab VALUES (?,?,?) ON CONFLICT(project_id) DO UPDATE SET token=excluded.token",
                (self.project_id, self.root, encrypted),
            )

    def request(self, method, suffix="", *, query=None, payload=None):
        if method not in ("GET", "POST") or not re.fullmatch(r"(?:/[A-Za-z0-9_-]+)*", suffix):
            raise WorkspaceError("Unsupported GitLab API operation.")
        with closing(sqlite3.connect(self.workspace.db_path)) as db:
            row = db.execute("SELECT token FROM gitlab WHERE project_id=?", (self.project_id,)).fetchone()
        if not row or not row[0]:
            raise WorkspaceError("Save a separate GitLab API token for this action.")
        parts = urlsplit(self.root)
        path = parts.path + "/api/v4/projects/" + quote(self.namespace, safe="") + suffix
        if query:
            path += "?" + urlencode(query, doseq=True)
        ca = ca_file(self.workspace, self.project_id)
        headers = {"PRIVATE-TOKEN": self.workspace.cipher.decrypt(row[0]).decode(), "Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        try:
            context = ssl.create_default_context(cafile=ca if ca.is_file() else os.getenv("GIT_SSL_CAINFO"))
            with closing(http.client.HTTPSConnection(parts.hostname, parts.port, timeout=10, context=context)) as conn:
                conn.request(method, path, json.dumps(payload).encode() if payload is not None else None, headers)
                response = conn.getresponse()
                if 300 <= response.status < 400:
                    raise WorkspaceError("GitLab redirected the request. Verify the installation URL.")
                if response.status in (401, 403, 404):
                    raise WorkspaceError(
                        "GitLab denied project API access or the project was not found. Check token scope and membership."
                    )
                if not 200 <= response.status < 300:
                    raise WorkspaceError(f"GitLab API returned HTTP {response.status}.")
                body = response.read(2**20 + 1)
                if len(body) > 2**20:
                    raise WorkspaceError("GitLab API response exceeded the size limit.")
                return json.loads(body) if body else None
        except (OSError, http.client.HTTPException, json.JSONDecodeError, UnicodeError) as exc:
            raise WorkspaceError(
                "Could not read the GitLab API. Check the installation URL, network and trusted CA."
            ) from exc


def instance(workspace, project):
    with closing(sqlite3.connect(workspace.db_path)) as db:
        row = db.execute("SELECT root FROM gitlab WHERE project_id=?", (project.id,)).fetchone()
    loc = location(project.remote, row[0] if row else "")
    return GitLab(workspace, project.id, *loc) if loc else None
