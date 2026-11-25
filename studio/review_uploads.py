"""Bounded standalone dashboard sources; never resolve references in uploaded reports."""

import hashlib
import json
import math
import sqlite3
from contextlib import closing

from fastapi import HTTPException

from skillevaluator.reporting.dashboard_data import comparison_rows, parse_dashboard_report

LIMIT = 1024**2


def database(workspace):
    db = sqlite3.connect(workspace.db_path)
    db.execute(
        "CREATE TABLE IF NOT EXISTS dashboard_uploads(project TEXT, id TEXT, payload BLOB, PRIMARY KEY(project,id))"
    )
    return db


def unique(pairs):
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise ValueError("Duplicate key")
    return obj


def validate_tree(value, depth=0):
    if depth > 40 or (isinstance(value, float) and not math.isfinite(value)):
        raise ValueError("Invalid JSON value")
    if isinstance(value, str):
        value.encode("utf-8")
    if isinstance(value, dict):
        for k, v in value.items():
            validate_tree(k, depth + 1)
            validate_tree(v, depth + 1)
    if isinstance(value, list):
        for v in value:
            validate_tree(v, depth + 1)


async def import_report(request, workspace, project):
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise HTTPException(415, "Choose a JSON report.")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > LIMIT:
            raise HTTPException(413, "Report exceeds 1 MiB.")
        body.extend(chunk)
    source = "upload-" + hashlib.sha256(body).hexdigest()[:24]
    try:
        doc = json.loads(body.decode("utf-8"), object_pairs_hook=unique)
        validate_tree(doc)
        data = parse_dashboard_report(doc, source, max_row_bytes=2 * LIMIT)
        if not 0 < len(data.rows) <= 1000:
            raise ValueError("No supported measurements or too many rows")
        comparison_rows(data.rows)
    except (ValueError, RecursionError, TypeError, AttributeError, OverflowError, KeyError) as exc:
        raise HTTPException(422, "Choose valid canonical report JSON with 1 to 1000 measurement rows.") from exc
    with closing(database(workspace)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if (
            db.execute(
                "SELECT count(*) FROM dashboard_uploads WHERE project=? AND id!=?", (project, source)
            ).fetchone()[0]
            >= 16
        ):
            raise HTTPException(409, "Remove an imported report first (16 per project).")
        db.execute(
            "INSERT OR IGNORE INTO dashboard_uploads VALUES(?,?,?)",
            (project, source, workspace.cipher.encrypt(bytes(body))),
        )
    return source


def uploads(workspace, project):
    with closing(database(workspace)) as db:
        return dict(
            db.execute("SELECT id,payload FROM dashboard_uploads WHERE project=? ORDER BY rowid DESC", (project,))
        )


def remove(workspace, project, source):
    with closing(database(workspace)) as db, db:
        if not db.execute("DELETE FROM dashboard_uploads WHERE project=? AND id=?", (project, source)).rowcount:
            raise HTTPException(404, "Unknown imported report")
