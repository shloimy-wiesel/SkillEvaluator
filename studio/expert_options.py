"""Command-scoped form contract. Blank controls leave CLI options unset."""

from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from skillevaluator.harness.overlay import profile_names
from skillevaluator.tier1.commands import DEFAULT_CHECKS, OPTIONAL_CHECKS

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
REPORTS = ("cli", "json", "html", "markdown", "sarif", "junit", "github")
CHECKS = (*DEFAULT_CHECKS, *OPTIONAL_CHECKS)
HARNESSES = tuple(profile_names(None))
FILES = {
    "quality_config": "Quality configuration",
    "pii_waivers": "PII waivers",
    "skillspector_baseline": "SkillSpector baseline",
    "hook_waivers": "Hook waivers",
    "policy": "Validation policy overlay",
}
COMMON = {"checks", "skip", "profile", "min_score", "previous_version", "llm", *FILES}
FIELDS = {
    "quality-check": {"reports", "min_score", "quality_config"},
    "validate": COMMON
    | {
        "reports",
        "tiers",
        "block_on_dedup",
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
MULTI = {"reports", "checks", "skip", "harness"}


class FrozenProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    provider: str
    model: str
    endpoint: str | None


class ExpertOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: str
    chat: FrozenProfile | None = None
    embeddings: FrozenProfile | None = None
    min_score: int | None = Field(None, ge=0, le=100)
    reports: tuple[Literal["cli", "json", "html", "markdown", "sarif", "junit", "github"], ...] = ()
    checks: tuple[str, ...] = ()
    skip: tuple[str, ...] = ()
    tiers: Literal["1", "1,2"] | None = None
    block_on_dedup: bool | None = None
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

    @model_validator(mode="after")
    def scope(self):
        if self.action not in FIELDS:
            raise ValueError("Unknown action")
        if self.model_dump(exclude_defaults=True).keys() - FIELDS[self.action] - {"action", "chat", "embeddings"}:
            raise ValueError("Setting outside this action")
        if set(self.checks) - set(CHECKS) or set(self.skip) - {*CHECKS, "secrets"}:
            raise ValueError("Unknown check")
        import re

        if set(self.harness) - set(HARNESSES) or any(
            v.partition("=")[0] not in HARNESSES or not re.fullmatch(r"[\w.+-]{1,64}", v.partition("=")[2])
            for v in self.harness_versions
        ):
            raise ValueError("Invalid harness selection")
        if self.action == "validate" and not self.tiers:
            raise ValueError("Select supported tiers")
        if self.block_on_dedup is not None and self.tiers != "1,2":
            raise ValueError("Select Tier 2 to set its gate")
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
        cmd = ["tier1", "validate"] if self.action == "tier1-validate" else [self.action]
        cmd.append(str(ctx.skill))
        if self.action != "harness-check":
            cmd.extend(["--output-dir", str(ctx.artifacts)])
        for key, value in self.model_dump(exclude_defaults=True).items():
            flag = "--" + key.replace("_", "-")
            if key in {"action", "chat", "embeddings"}:
                continue
            if key == "reports":
                for fmt in value:
                    cmd.extend(["--report", fmt])
            elif key == "write_json":
                cmd.extend(["--json", str(ctx.artifacts / "harness.json")])
            elif key == "include_revision":
                cmd.extend(["--evaluated-source-revision", ctx.revision])
            elif key == "harness_versions":
                for item in value:
                    cmd.extend(["--harness-version", item])
            elif key in {"llm", "block_on_dedup"}:
                cmd.append(flag if value else "--no-" + flag[2:])
            elif isinstance(value, bool):
                cmd.append(flag)
            elif key in FILES:
                cmd.extend([flag, str(ctx.input_file(value))])
            else:
                cmd.extend([flag, ",".join(value) if isinstance(value, tuple) else str(value)])
        return cmd
