"""Isolated engine adapter. Credentials arrive through stdin only."""

import json
import resource
import ssl
import sys
from dataclasses import fields, is_dataclass
from pathlib import Path

import click
import httpx

from skillevaluator.constants import CONTENT_DEDUP_LLM_REASONING_EFFORT
from skillevaluator.embedding.client import EmbeddingClient
from skillevaluator.inference import LLMClient
from skillevaluator.provider_config import ProviderConfig
from skillevaluator.reporting.github_reporter import GitHubReporter
from skillevaluator.reporting.json_reporter import JSONReporter
from skillevaluator.reporting.markdown import MarkdownReporter
from skillevaluator.reporting.run_status import resolve_run_status
from skillevaluator.tier1.commands import emit_reports
from skillevaluator.tier2.commands import run_context_optimization_check, run_similarity_check
from skillevaluator.tier_workflows import run_tier2_workflow
from skillevaluator.utils.tier2_paths import sanitize_tier2_results


def redact(value, secrets):
    """Remove echoed credentials before rendering (including HTML/XML escaping)."""
    if type(value) is str:
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
    elif isinstance(value, list):
        return [redact(item, secrets) for item in value]
    elif isinstance(value, dict):
        return {redact(k, secrets): redact(v, secrets) for k, v in value.items()}
    elif is_dataclass(value):
        for field in fields(value):
            setattr(value, field.name, redact(getattr(value, field.name), secrets))
    return value


def main():
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    data = json.load(sys.stdin)
    opts = data["options"]
    skill = Path(data["skill"])
    catalog = Path(data["catalog"]) if data["catalog"] else None
    artifacts = Path(data["artifacts"])
    save = artifacts / "catalog.json" if opts["save_catalog"] else None
    root = Path(data["root"])
    profiles = data["profiles"]
    secure = {"verify": ssl.create_default_context(), "follow_redirects": False, "trust_env": False}
    with httpx.Client(**secure) as emb_http, httpx.Client(**secure) as chat_http:
        embedding = EmbeddingClient(provider_config=ProviderConfig(**profiles["embeddings"]), http_client=emb_http)
        chat = (
            LLMClient(
                provider_config=ProviderConfig(**profiles["chat"]),
                http_client=chat_http,
                reasoning_effort=CONTENT_DEDUP_LLM_REASONING_EFFORT,
            )
            if "chat" in profiles
            else None
        )
        common = {"embedding_client": embedding, "chat_client": chat, "threshold": opts["threshold"]}
        if opts["action"] == "direct":
            try:
                results = run_tier2_workflow(
                    skill,
                    **common,
                    catalog=catalog,
                    full_body=opts["full_body"],
                    similarity_threshold=opts["similarity_threshold"],
                    repository_root=root,
                )
            except click.ClickException:
                if catalog:
                    json.dump({"error": "catalog_preflight"}, sys.stdout)
                    return
                raise
        elif opts["action"] == "similarity":
            results = run_similarity_check(
                skill,
                embedding_client=embedding,
                catalog=catalog,
                threshold=opts["similarity_threshold"],
                full_body=opts["full_body"],
                save_catalog=save,
                repository_root=root,
                content_type=opts["content_type"],
                max_entries=opts["max_entries"],
                max_scalar_comparisons=opts["max_scalar_comparisons"],
            )
        else:
            results = run_context_optimization_check(skill, **common)
    sanitize_tier2_results(results, skill, catalog, save)
    secrets = [c["api_key"] for c in profiles.values() if c["api_key"]]
    redact(results, secrets)
    if save and save.is_file():
        original = json.loads(save.read_text())
        if redact(original, secrets) != original:
            save.unlink()
            raise ValueError("Catalog contains credential material.")
    formats = opts["formats"] or (["cli", "html", "json"] if opts["action"] == "direct" else ["cli"])
    file_formats = tuple(f for f in formats if f not in ("cli", "github"))
    name = None if opts["action"] == "similarity" and not catalog else skill.name
    emit_reports(
        results,
        report_formats=file_formats,
        output_dir=artifacts,
        basename="overlap",
        repository_root=root,
        scan_root=skill,
        explicit_skill_name=name,
        announce_paths=False,
    )
    if "github" in formats:
        reporter = GitHubReporter(workspace_root=root, scan_root=skill, report_formats=tuple(formats))
        (artifacts / "github.txt").write_text(reporter.render_all(results))
    report = json.loads(JSONReporter(explicit_skill_name=name).render_all(results))
    report["studio_artifacts"] = sorted(p.name for p in artifacts.iterdir() if p.is_file())
    json.dump(
        {
            "status": resolve_run_status(results).tiers[2].status.value,
            "exit_code": int(not all(r.passed for r in results)),
            "report": json.dumps(report),
            "markdown": MarkdownReporter().render_all(results),
        },
        sys.stdout,
    )


if __name__ == "__main__":
    main()
