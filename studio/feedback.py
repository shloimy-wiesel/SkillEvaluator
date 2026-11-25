"""Persistent run-scoped feedback with a private provider process per question."""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path

from fastapi import HTTPException

from skillevaluator.evaluation.tier3_feedback_chat import compact_run_context, load_agent_eval_payload

from .providers import worker_environment
from .retained import input_projection, mask_strings, scrubber


def database(workspace):
    db = sqlite3.connect(workspace.db_path)
    db.execute("""CREATE TABLE IF NOT EXISTS feedback_turns(
        project TEXT, run TEXT, turn INTEGER, question TEXT, answer TEXT,
        PRIMARY KEY(project, run, turn))""")
    return db


def conversation(workspace, run):
    with closing(database(workspace)) as db:
        return db.execute(
            "SELECT question,answer FROM feedback_turns WHERE project=? AND run=? ORDER BY turn",
            (run["project_id"], run["id"]),
        ).fetchall()


def ask(workspace, run, question):
    payload = json.loads(run["report"] or "{}").get("tier3")
    if not payload or not question.strip():
        raise HTTPException(422, "A question and a canonical evaluation report are required.")
    project = run["project_id"]
    try:
        env = worker_environment(workspace, project, "chat")
    except ValueError as exc:
        raise HTTPException(422, "Configure a chat provider in project settings.") from exc
    if env.get("SKILL_EVAL_LLM_PROVIDER") == "bedrock":
        authorized = {p.strip() for p in os.getenv("STUDIO_FEEDBACK_BEDROCK_PROJECTS", "").split(",")}
        if project not in authorized:
            raise HTTPException(403, "This project is not authorized for runtime Bedrock feedback.")
        for key in (
            "AWS_REGION",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "AWS_ROLE_ARN",
            "AWS_WEB_IDENTITY_TOKEN_FILE",
        ):
            if key in os.environ:
                env[key] = os.environ[key]
    if "SSL_CERT_FILE" in os.environ:
        env["SSL_CERT_FILE"] = os.environ["SSL_CERT_FILE"]
    scrub = scrubber(
        workspace,
        project,
        extra_secrets=[env.get(k) for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")],
    )
    history = conversation(workspace, run)
    question = scrub(question.strip())
    root = workspace.data_dir / "artifacts" / project / run["id"] / "tier3"
    try:
        with input_projection(root, run) as (native, skill):
            context = compact_run_context(load_agent_eval_payload(skill, native), run_dir=native, skill_dir=skill)
    except (ValueError, OSError, TypeError, AttributeError, RecursionError) as exc:
        raise HTTPException(422, "Cannot prepare feedback from this run's retained evidence.") from exc
    messages = [
        {"role": role, "content": scrub(text)}
        for pair in history
        for role, text in zip(("user", "assistant"), pair, strict=True)
    ]
    messages.append({"role": "user", "content": question})
    with tempfile.TemporaryDirectory() as home:
        try:
            result = subprocess.run(
                [sys.executable, "-I", str(Path(__file__).with_name("feedback_worker.py"))],
                cwd=home,
                env={**env, "HOME": home, "PYTHON_DOTENV_DISABLED": "1"},
                input=json.dumps([mask_strings(context, scrub), messages]),
                text=True,
                capture_output=True,
                timeout=90,
                check=True,
            )
            answer = scrub(json.loads(result.stdout))
        except (ValueError, subprocess.SubprocessError, OSError) as exc:
            raise HTTPException(502, "Feedback unavailable. Check the project chat provider and retry.") from exc
    with closing(database(workspace)) as db, db:
        try:
            db.execute(
                "INSERT INTO feedback_turns VALUES(?,?,?,?,?)", (project, run["id"], len(history), question, answer)
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "Another answer was saved. Reopen this conversation.") from exc
