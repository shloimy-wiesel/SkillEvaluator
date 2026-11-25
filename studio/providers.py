"""Project-scoped provider profiles and Studio settings routes."""

import http.client
import json
import re
import sqlite3
from contextlib import closing
from urllib.parse import urlsplit

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .readiness import AGENTS, RECOGNIZED_CHECKS, Probe, all_env_modes, inspect

router = APIRouter(prefix="/projects/{project_id}/providers")
CHOICES = {
    "chat": ("openai-compatible", "openai", "anthropic", "nv_build", "bedrock"),
    "embeddings": ("openai-compatible", "openai", "nv_build"),
}
DEFAULT_URL = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "nv_build": "https://integrate.api.nvidia.com/v1",
}
MODEL = re.compile(r"[\w./:@+-]{1,256}", re.ASCII)


def database(workspace):
    db = sqlite3.connect(workspace.db_path)
    db.execute("""CREATE TABLE IF NOT EXISTS provider_profiles (
        project TEXT, role TEXT, profile BLOB NOT NULL, PRIMARY KEY(project, role))""")
    return db


def load(db, workspace, project, role):
    row = db.execute("SELECT profile FROM provider_profiles WHERE project=? AND role=?", (project, role)).fetchone()
    return json.loads(workspace.cipher.decrypt(row[0])) if row else {}


def worker_environment(workspace, project_id: str, role: str) -> dict[str, str]:
    """Return a fresh, secret-bearing evaluator environment for exactly one role."""
    if role not in CHOICES:
        raise ValueError("Unknown provider role.")
    with closing(database(workspace)) as db:
        profile = load(db, workspace, project_id, role)
    if not profile or (not profile["key"] and profile["provider"] != "bedrock"):
        raise ValueError("Provider settings are incomplete.")
    prefix = "SKILL_EVAL_LLM_" if role == "chat" else "SKILL_EVAL_EMBEDDING_"
    provider = profile["provider"]
    env = {prefix + "PROVIDER": provider}
    if profile["model"]:
        env[prefix + "MODEL"] = profile["model"]
    if profile["base_url"]:
        env[prefix + "BASE_URL"] = profile["base_url"]
        if provider in {"openai", "anthropic"}:
            env[provider.upper() + "_BASE_URL"] = profile["base_url"]
    if profile["key"]:
        key_name = {"openai": "OPENAI_API_KEY", "nv_build": "NVIDIA_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
        env[key_name.get(provider, prefix + "API_KEY")] = profile["key"]
    return env


def project_for(request, project_id):
    project = request.app.state.workspace.get(project_id)
    if not project:
        raise HTTPException(404, "Unknown project")
    return project


def render(request, project, **messages):
    workspace = request.app.state.workspace
    with closing(database(workspace)) as db:
        profiles = {}
        for role in CHOICES:
            profile = load(db, workspace, project.id, role)
            profile["has_key"] = bool(profile.pop("key", ""))
            profiles[role] = profile
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="providers/index.html",
        context=dict(
            project=project,
            choices=CHOICES,
            profiles=profiles,
            scanners=sorted(RECOGNIZED_CHECKS),
            runtime_agents=AGENTS,
            modes=all_env_modes(),
            **messages,
        ),
        status_code=422 if "error" in messages else 200,
        headers={"Cache-Control": "no-store"},
    )


@router.get("", name="provider_settings")
def settings(request: Request, project_id: str):
    return render(request, project_for(request, project_id))


@router.post("/readiness/run", name="native_readiness")
async def readiness(request: Request, project_id: str):
    project = project_for(request, project_id)
    async with request.form() as form:
        values = dict(form)
        for name in ("agents", "checks"):
            values[name] = form.getlist(name)
    try:
        probe = Probe.model_validate(values)
    except ValidationError as exc:
        fields = {
            str(error["loc"][0]) for error in exc.errors() if error["loc"] and error["loc"][0] in Probe.model_fields
        }
        return render(
            request, project, error="Invalid readiness settings. Check: " + ", ".join(sorted(fields) or ["form fields"])
        )
    return await run_in_threadpool(run_readiness, request, project, probe)


def run_readiness(request, project, probe):
    try:
        workspace = request.app.state.workspace
        profiles = {}
        for role in CHOICES:
            try:
                profiles[role] = worker_environment(workspace, project.id, role)
            except ValueError:
                profiles[role] = {}
        result, code = inspect(probe, profiles["chat"], profiles["embeddings"])
    except ValueError as exc:
        return render(request, project, error=str(exc))
    return render(request, project, result=result, exit_code=code, show_json=probe.as_json)


def valid_url(url):
    try:
        parts = urlsplit(url)
        return (
            parts.scheme == "https"
            and parts.hostname
            and re.fullmatch(r"(?:[a-zA-Z0-9._-]+|\[[0-9a-fA-F:]+\])(?::[0-9]+)?", parts.netloc)
            and parts.port != 0
            and not re.search(r"[\s\\?#\x00-\x1f\x7f]", url)
            and url.isascii()
            and len(url) <= 2048
        )
    except ValueError:
        return False


@router.post("/{role}", name="provider_save")
def save(
    request: Request,
    project_id: str,
    role: str,
    *,
    provider: str = Form(""),
    base_url: str = Form(""),
    model: str = Form(""),
    key: str = Form(""),
    clear: bool = Form(False),
):
    project = project_for(request, project_id)
    if role not in CHOICES:
        raise HTTPException(404, "Unknown profile")
    base_url = base_url.strip().rstrip("/") or DEFAULT_URL.get(provider, "")
    model = model.strip()
    if (
        provider not in CHOICES[role]
        or (model and not MODEL.fullmatch(model))
        or (provider != "bedrock" and not valid_url(base_url))
        or (provider == "nv_build" and base_url != DEFAULT_URL["nv_build"])
        or (provider == "bedrock" and (base_url or key))
        or (key and not re.fullmatch(r"[!-~]{1,8192}", key))
    ):
        return render(request, project, error="Check the provider, HTTPS base URL, model and credential fields.")
    workspace = request.app.state.workspace
    with closing(database(workspace)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        old = load(db, workspace, project_id, role)
        if not key and not clear and (provider, base_url) == (old.get("provider"), old.get("base_url")):
            key = old["key"]
        if any(secret in model or secret in base_url for secret in (key, old.get("key")) if secret):
            return render(request, project, error="Keep credentials out of the URL and model fields.")
        profile = {"provider": provider, "base_url": base_url, "model": model, "key": key}
        db.execute(
            "INSERT OR REPLACE INTO provider_profiles VALUES(?,?,?)",
            (project_id, role, workspace.cipher.encrypt(json.dumps(profile).encode())),
        )
    return RedirectResponse(request.url_for("provider_settings", project_id=project_id), 303)


def discover(profile):
    """Read a bounded catalog from exactly one TLS connection; never follow redirects."""
    parts = urlsplit(profile["base_url"])
    path = parts.path.rstrip("/")
    headers = {"Accept": "application/json"}
    if profile["provider"] == "anthropic":
        headers.update({"x-api-key": profile["key"], "anthropic-version": "2023-06-01"})
        path = path.removesuffix("/v1") + "/v1"
    else:
        headers["Authorization"] = "Bearer " + profile["key"]
    with closing(http.client.HTTPSConnection(parts.hostname, parts.port, timeout=5)) as client:
        client.request("GET", path + "/models", headers=headers)
        response = client.getresponse()
        if response.status != 200:
            raise ValueError
        data = response.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError
    catalog = json.loads(data)
    if not isinstance(catalog, dict) or not isinstance(catalog.get("data"), list):
        raise ValueError
    return sorted(
        {
            item["id"]
            for item in catalog["data"]
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and MODEL.fullmatch(item["id"])
            and profile["key"] not in item["id"]
        }
    )


@router.post("/{role}/check", name="provider_check")
def check(request: Request, project_id: str, role: str):
    project = project_for(request, project_id)
    if role not in CHOICES:
        raise HTTPException(404, "Unknown profile")
    workspace = request.app.state.workspace
    with closing(database(workspace)) as db:
        profile = load(db, workspace, project_id, role)
    if profile.get("provider") == "bedrock":
        return render(
            request, project, checked=role, notice="Bedrock uses AWS runtime credentials; discovery unavailable."
        )
    if not profile.get("key"):
        return render(request, project, error="Save an API key for this profile before checking readiness.")
    try:
        models = discover(profile)
    except (OSError, http.client.HTTPException, ValueError, RecursionError):
        return render(request, project, error="Model discovery failed. Check endpoint access, TLS and API key.")
    notice = "Catalog reachable."
    if profile["model"]:
        notice += " Selected model is listed." if profile["model"] in models else " Selected model was not listed."
    return render(request, project, checked=role, notice=notice, models=models)
