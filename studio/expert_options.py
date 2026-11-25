"""Command-scoped form contract. Blank controls leave CLI options unset."""

from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from skillevaluator.harness.overlay import PROFILES_DIR, profile_names
from skillevaluator.tier1.commands import DEFAULT_CHECKS, OPTIONAL_CHECKS

from .live_job import Agent, Budget, Model, Positive

AGENT_MODELS = {"codex_model": "codex", "opencode_model": "opencode", "claude_code_model": "claude-code"}

ACTIONS = {
    "quality-check": "Quality check",
    "rubric-eval": "Rubric evaluation",
    "security-scan": "Security scan",
    "pii-scan": "PII scan",
    "lint-scripts": "Script lint",
    "harness-check": "Harness compatibility",
    "validate": "Validation pipeline",
    "tier1": "Tier 1 workflow",
    "tier1-validate": "Tier 1 validate",
}
WORKFLOWS = ("validate", "tier1", "tier1-validate")
ALIASES = {f"tier1-{a}": a for a in ("quality-check", "rubric-eval", "security-scan", "pii-scan", "lint-scripts")}
ACTIONS.update({alias: f"Tier 1: {ACTIONS[a]}" for alias, a in ALIASES.items()})
REPORTS = ("cli", "json", "html", "markdown", "sarif", "junit", "github")
CHECKS = (*DEFAULT_CHECKS, *OPTIONAL_CHECKS)
HARNESSES = tuple(profile_names(None))
AGENT_HARNESSES = ("claude-code", "codex", "opencode")
FILES = {
    "quality_config": "Quality configuration",
    "pii_waivers": "PII waivers",
    "skillspector_baseline": "SkillSpector baseline",
    "hook_waivers": "Hook waivers",
    "policy": "Validation policy overlay",
}
COMMON = {"checks", "skip", "profile", "min_score", "previous_version", "llm", *FILES}
FILES["price_file"] = "Model price file"
ROOT_LIVE = {
    *AGENT_MODELS,
    "price_file",
    "n_attempts",
    "n_concurrent",
    "grading_mode",
    "max_agents",
    "max_agent_tokens",
    "max_judge_calls",
    "max_cost_usd",
    "pass_threshold",
    "stop_on_pass",
    "timeout_multiplier",
    "tolerate_baseline_timeouts",
    "block_on_agent_eval",
    "env_mode",
    "autopilot",
    "agents",
    "max_cases",
    "max_attempts_total",
    "agent_runtime_preflight",
    "skip_baseline",
    "model",
}
FIELDS = {
    "quality-check": {"reports", "min_score", "quality_config"},
    "validate": COMMON
    | {
        "reports",
        "tiers",
        "block_on_dedup",
        *ROOT_LIVE,
        "fail_fast",
        "continue_on_failure",
        "verbose",
        "llm_verify",
        "harness",
        "include_revision",
    },
    "rubric-eval": {"reports", "min_score"},
    "security-scan": {"reports", "llm", "llm_verify", "skillspector_baseline", "hook_waivers"},
    "pii-scan": {"reports", "llm_verify", "pii_waivers"},
    "lint-scripts": {"reports"},
    "harness-check": {
        "harness",
        "harness_versions",
        "context_tokens",
        "verbose",
        "write_json",
        "custom_provider",
        "explicit_invocation",
        "headless",
    },
    **{a: COMMON | {"reports"} for a in WORKFLOWS[1:]},
}
MULTI = {"reports", "checks", "skip", "harness", "agents"}
FIELDS.update({alias: FIELDS[a] for alias, a in ALIASES.items()})
for action in FIELDS:
    if action != "harness-check":
        FIELDS[action].add("target")
FIELDS["validate"].update({"workers", "content_type", "catalog_root", "full", "dedup", "agent_eval", "external"})
for action in ("validate", "harness-check"):
    FIELDS[action].add("harness_profiles")


class FrozenProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    provider: str
    model: str
    endpoint: str | None


class ExpertOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    action: str
    full: bool = False
    dedup: bool | None = None
    agent_eval: bool | None = None
    external: bool = False
    harness_profiles: Literal["agent-clis"] | None = None
    target: str | None = None
    catalog_root: str | None = None
    workers: int | None = Field(None, ge=1, le=4)
    content_type: Literal["auto", "skill", "rules", "workflows", "plugin"] | None = None
    snapshot_id: str | None = Field(None, pattern=r"^[0-9a-f]{32}$")
    chat: FrozenProfile | None = None
    embeddings: FrozenProfile | None = None
    min_score: int | None = Field(None, ge=0, le=100)
    reports: tuple[Literal["cli", "json", "html", "markdown", "sarif", "junit", "github"], ...] = ()
    checks: tuple[str, ...] = ()
    skip: tuple[str, ...] = ()
    tiers: Literal["1", "1,2", "1,3", "1,2,3"] | None = None
    block_on_dedup: bool | None = None
    env_mode: Literal["docker", "kata"] | None = None
    agents: tuple[Agent, ...] = ()
    block_on_agent_eval: bool | None = None
    autopilot: bool | None = None
    agent_runtime_preflight: bool | None = None
    skip_baseline: bool = False
    max_cases: int | None = Field(None, gt=0)
    max_attempts_total: int | None = Field(None, ge=0)
    model: Model | None = None
    codex_model: Model | None = None
    opencode_model: Model | None = None
    claude_code_model: Model | None = None
    n_attempts: Positive | None = None
    n_concurrent: Positive | None = None
    max_agents: Positive | None = None
    max_agent_tokens: Budget | None = None
    max_judge_calls: Budget | None = None
    pass_threshold: float | None = Field(None, ge=0, le=1)
    max_cost_usd: float | None = Field(None, ge=0)
    price_file: str | None = None
    timeout_multiplier: float | None = Field(None, gt=0)
    stop_on_pass: bool | None = None
    tolerate_baseline_timeouts: bool | None = None
    grading_mode: Literal["default", "default_plus_custom", "custom_only"] | None = None
    include_revision: bool = False
    llm: bool | None = None
    llm_verify: bool = False
    fail_fast: bool = False
    continue_on_failure: bool = False
    verbose: bool = False
    previous_version: str | None = Field(None, max_length=128, pattern=r"^[0-9A-Za-z][0-9A-Za-z.+-]*$")
    profile: Literal["default", "external", "registry"] | None = None
    quality_config: str | None = None
    policy: str | None = None
    pii_waivers: str | None = None
    skillspector_baseline: str | None = None
    hook_waivers: str | None = None
    harness: tuple[str, ...] = ()
    harness_versions: tuple[str, ...] = ()
    context_tokens: int | None = Field(None, ge=0)
    write_json: bool = False
    custom_provider: bool = False
    explicit_invocation: bool = False
    headless: bool = False

    @property
    def live(self):
        return self.action == "validate" and ("3" in self.tiers if self.tiers else self.agent_eval is not False)

    @model_validator(mode="after")
    def scope(self):
        if self.action not in FIELDS:
            raise ValueError("Unknown action")
        if (
            self.model_dump(exclude_defaults=True).keys()
            - FIELDS[self.action]
            - {"action", "chat", "embeddings", "snapshot_id"}
        ):
            raise ValueError("Setting outside this action")
        if set(self.checks) - set(CHECKS) or set(self.skip) - {*CHECKS, "secrets"}:
            raise ValueError("Unknown check")
        import re

        if set(self.harness) - set(HARNESSES) or any(
            v.partition("=")[0] not in HARNESSES or not re.fullmatch(r"[\w.+-]{1,64}", v.partition("=")[2])
            for v in self.harness_versions
        ):
            raise ValueError("Invalid harness selection")
        if self.harness_profiles and set(self.harness) - set(AGENT_HARNESSES):
            raise ValueError("Select harnesses from the managed agent CLI set")
        if not self.live and self.model_dump(exclude_defaults=True).keys() & ROOT_LIVE:
            raise ValueError("Select Tier 3 to set live controls")
        if self.live and (self.target or self.catalog_root or self.workers):
            raise ValueError("Alternate targets and catalog evaluation require static tiers")
        for directory in (self.target, self.catalog_root):
            if directory is not None and directory != "." and (
                any(p.lower() in {"", ".", "..", ".git"} for p in directory.split("/")) or "\\" in directory
            ):
                raise ValueError("Invalid directory selection")
        if self.block_on_dedup is not None and self.tiers and "2" not in self.tiers:
            raise ValueError("Select Tier 2 to set its gate")
        if self.external and self.profile == "registry":
            raise ValueError("External conflicts with registry policy")
        if any(getattr(self, key) and agent not in self.agents for key, agent in AGENT_MODELS.items()):
            raise ValueError("Select each agent with a model override")
        if self.max_cost_usd is not None and not self.price_file:
            raise ValueError("Select a price file with a cost limit")
        for key in FILES:
            path = getattr(self, key)
            if path and (
                PurePosixPath(path).is_absolute()
                or any(p.lower() in {"", ".", "..", ".git"} for p in path.split("/"))
                or "\\" in path
                or not path.lower().endswith((".yaml", ".yml", ".json"))
            ):
                raise ValueError("Invalid configuration selection")
        return self

    def arguments(self, ctx):
        cmd = self.action.split("-", 1) if self.action.startswith("tier1-") else [self.action]
        target = ctx.root / self.target if self.target else ctx.skill
        cmd.append(str(target))
        if self.action != "harness-check":
            cmd.extend(["--output-dir", str(ctx.artifacts)])
        for key, value in self.model_dump(exclude_defaults=True).items():
            flag = "--" + key.replace("_", "-")
            if key in {"action", "chat", "embeddings", "snapshot_id", "target"}:
                continue
            if key == "catalog_root":
                root = ctx.root / value
                if not target.is_relative_to(root):
                    raise ValueError("Catalog root must contain the target")
                cmd.extend([flag, str(root)])
            elif key == "content_type":
                cmd.extend(["--type", value])
            elif key == "harness_profiles":
                cmd.extend([flag, str(PROFILES_DIR)])
                if not self.harness:
                    cmd.extend(["--harness", ",".join(AGENT_HARNESSES)])
            elif key == "reports":
                for fmt in value:
                    cmd.extend(["--report", fmt])
            elif key in AGENT_MODELS:
                cmd.extend(["--agent-model", f"{AGENT_MODELS[key]}={value}"])
            elif key == "write_json":
                cmd.extend(["--json", str(ctx.artifacts / "harness.json")])
            elif key == "include_revision":
                cmd.extend(["--evaluated-source-revision", ctx.revision])
            elif key == "harness_versions":
                for item in value:
                    cmd.extend(["--harness-version", item])
            elif key in {
                "llm",
                "dedup",
                "agent_eval",
                "block_on_dedup",
                "block_on_agent_eval",
                "autopilot",
                "agent_runtime_preflight",
                "stop_on_pass",
                "tolerate_baseline_timeouts",
            }:
                cmd.append(flag if value else "--no-" + flag[2:])
            elif isinstance(value, bool):
                cmd.append(flag)
            elif key in FILES:
                cmd.extend([flag, str(ctx.input_file(value))])
            else:
                cmd.extend([flag, ",".join(value) if isinstance(value, tuple) else str(value)])
        return cmd
