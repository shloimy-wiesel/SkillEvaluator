"""Carry server-generated publication feedback across a POST/Redirect/GET."""

import sqlite3
from contextlib import closing
from uuid import uuid4

from pydantic import BaseModel


class Publication(BaseModel):
    location: str


def database(request):
    db = sqlite3.connect(request.app.state.workspace.db_path)
    db.execute("""CREATE TABLE IF NOT EXISTS ci_receipts (
        id TEXT PRIMARY KEY, project TEXT, route TEXT, notice TEXT, compare_url TEXT)""")
    return db


def published(request, project, route, notice, compare=None):
    receipt = uuid4().hex
    with closing(database(request)) as db, db:
        db.execute("INSERT INTO ci_receipts VALUES(?,?,?,?,?)", (receipt, project.id, route, notice, compare))
        db.execute(
            """DELETE FROM ci_receipts WHERE rowid IN (
                SELECT rowid FROM ci_receipts WHERE project=? AND route=? ORDER BY rowid DESC LIMIT -1 OFFSET 32)""",
            (project.id, route),
        )
    url = request.url_for(route, project_id=project.id).include_query_params(receipt=receipt)
    return Publication(location=url.path + "?" + url.query)


def feedback(request, project, route):
    receipt = request.query_params.get("receipt")
    if not receipt:
        return {}
    with closing(database(request)) as db:
        row = db.execute(
            "SELECT notice, compare_url FROM ci_receipts WHERE project=? AND route=? AND id=?",
            (project.id, route, receipt),
        ).fetchone()
    return {"notice": row[0], "compare": row[1]} if row else {}
