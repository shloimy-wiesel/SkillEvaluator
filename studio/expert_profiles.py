"""Snapshot only the provider roles needed by a selected check."""

import json
from contextlib import closing
from importlib.util import find_spec
from uuid import uuid4

from skillevaluator.provider_config import resolve_embedding_provider, resolve_llm_provider

from .providers import database, load, worker_environment
from .workspace import WorkspaceError


def snapshot(workspace, project_id, options):
    if options.live:
        options = options.model_copy(update={"snapshot_id": uuid4().hex})
    tier2 = options.action == "validate" and options.dedup is not False and (not options.tiers or "2" in options.tiers)
    with closing(database(workspace)) as db:
        if tier2 and load(db, workspace, project_id, "embeddings"):
            options = freeze_role(workspace, project_id, options, "embeddings")
        required = options.action in ("rubric-eval", "tier1-rubric-eval") or options.llm or options.llm_verify
        automatic = tier2 or options.live or (options.action in {"tier1", "tier1-validate"} and options.llm is None)
        if required or (automatic and load(db, workspace, project_id, "chat")):
            options = freeze_role(workspace, project_id, options, "chat")
    return options


def freeze_role(workspace, project_id, options, role):
    try:
        env = worker_environment(workspace, project_id, role)
        config = (resolve_llm_provider if role == "chat" else resolve_embedding_provider)(env)
    except ValueError as exc:
        raise WorkspaceError(f"Complete the saved {role} provider settings first.") from exc
    if config.provider == "bedrock":
        raise WorkspaceError("Choose a key-backed chat provider; the expert worker has no AWS identity.")
    if find_spec("openai") is None or (config.provider == "anthropic" and find_spec("anthropic") is None):
        raise WorkspaceError("Install the evaluator chat SDK in the Studio worker first.")
    from .expert_options import FrozenProfile

    profile = FrozenProfile(id=uuid4().hex, provider=config.provider, model=config.model, endpoint=config.base_url)
    frozen = options.model_copy(update={role: profile})
    if config.api_key and config.api_key in frozen.model_dump_json():
        raise WorkspaceError("Keep credentials out of public check settings.")
    if options.live:
        env["SKILL_EVAL_LLM_MODEL" if role == "chat" else "SKILL_EVAL_EMBEDDING_MODEL"] = config.model
    # Preserve the engine's distinction between a model override and its defaults.
    with closing(database(workspace)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS expert_profiles
                   (project TEXT, id TEXT, profile BLOB NOT NULL, PRIMARY KEY(project,id))""")
        db.execute(
            "INSERT INTO expert_profiles VALUES(?,?,?)",
            (project_id, profile.id, workspace.cipher.encrypt(json.dumps(env).encode())),
        )
    return frozen


def environment(ctx, profile):
    if not profile:
        return {}
    with closing(database(ctx.workspace)) as db:
        row = db.execute(
            "SELECT profile FROM expert_profiles WHERE project=? AND id=?", (ctx.project_id, profile.id)
        ).fetchone()
    if not row:
        raise WorkspaceError("The frozen provider profile is unavailable.")
    return json.loads(ctx.workspace.cipher.decrypt(row[0]))
