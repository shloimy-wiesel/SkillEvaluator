"""Project-scoped native CLI probes; no repository code or host credentials."""

import json
import os
import signal
import subprocess
import sys
import tempfile
from ipaddress import IPv4Address, IPv6Address
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from skillevaluator.tier1.commands import RECOGNIZED_CHECKS
from skillevaluator.tier3_environments import all_env_modes

AGENTS = ("claude-code", "claude", "codex", "opencode", "hermes")
ModelName = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_./:@+-]{1,256}$")]


class Probe(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    action: Literal["doctor", "health-check", "tier3 doctor", "models"]
    tier: Literal["1", "2", "3", "all"] | None = None
    checks: list[str] = []
    timeout: Annotated[float, Field(gt=0, le=60)] | None = None
    as_json: bool = False
    verify_models: bool = False
    limit: Annotated[int, Field(ge=1, le=100)] | None = None
    agents: list[str] = []
    env_mode: str | None = None
    backend: Literal["harbor", "nemo-gym"] | None = None
    kata_runtime: Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")] | None = None
    kata_dns: IPv4Address | IPv6Address | None = None
    claude_code_model: ModelName | None = None
    codex_model: ModelName | None = None
    opencode_model: ModelName | None = None
    hermes_model: ModelName | None = None

    @model_validator(mode="before")
    @classmethod
    def omit_blank_fields(cls, values):
        return {key: value for key, value in values.items() if value != ""}

    def arguments(self):
        args = [*self.action.split(), "--json"]
        models = {agent: getattr(self, agent.replace("-", "_") + "_model") for agent in AGENTS if agent != "claude"}
        runtime = (
            self.agents or self.env_mode or self.backend or self.kata_runtime or self.kata_dns or any(models.values())
        )
        if self.action == "models":
            if self.tier or self.checks or self.timeout is not None or self.verify_models or runtime:
                raise ValueError("Catalog discovery does not take tier options.")
            return args + (["--limit", str(self.limit)] if self.limit is not None else [])
        if self.limit is not None:
            raise ValueError("Catalog limit applies only to model discovery.")
        tier = self.tier or "3"
        if (self.action == "tier3 doctor" and self.tier) or (runtime and tier not in {"3", "all"}):
            raise ValueError("Runtime options require a Tier 3 scope; tier3 doctor already selects Tier 3.")
        if self.checks and tier not in {"1", "all"}:
            raise ValueError("Scanner checks require a Tier 1 scope.")
        if self.timeout is not None and (tier == "3" or (tier == "2" and not self.verify_models)):
            raise ValueError("Probe timeout applies to scanners or Tier 2 inference.")
        if self.agents:
            if not set(self.agents) <= set(AGENTS):
                raise ValueError("Select supported runtime agents.")
            args.extend(["-a", ",".join(self.agents)])
        if self.env_mode:
            if self.env_mode not in all_env_modes():
                raise ValueError("Select an installed runtime environment.")
            args.extend(["--env-mode", self.env_mode])
        if self.kata_runtime or self.kata_dns:
            if self.env_mode != "kata":
                raise ValueError("Kata settings require the Kata environment.")
            if self.kata_runtime:
                args.extend(["--environment-kwarg", "kata_runtime=" + self.kata_runtime])
            if self.kata_dns:
                args.extend(["--ek", "kata_dns=" + json.dumps([str(self.kata_dns)])])
        if self.backend:
            if self.action == "health-check":
                raise ValueError("Backend selection applies only to doctor.")
            args.extend(["--backend", self.backend])
        for agent, model in models.items():
            if model:
                if self.action == "health-check":
                    raise ValueError("Agent model overrides apply only to doctor.")
                args.extend(["--agent-model", f"{agent}={model}"])
        if self.verify_models:
            if self.action == "health-check" or self.tier == "1":
                raise ValueError("Provider probes apply only to doctor for tiers 2 and 3.")
            args.append("--verify-models")
        if self.tier:
            args.extend(["--tier", self.tier])
        if self.checks:
            if not set(self.checks) <= RECOGNIZED_CHECKS:
                raise ValueError("Select known scanner checks.")
            args.extend(["--checks", ",".join(self.checks)])
        if self.timeout is not None:
            args.extend(["--timeout", str(self.timeout)])
        return args


def inspect(probe, chat, embeddings):
    args = probe.arguments()
    secrets = {
        value for role in (chat, embeddings) for name, value in role.items() if name.endswith("API_KEY") and value
    }
    if any(secret in arg for secret in secrets for arg in args):
        raise ValueError("Keep provider credentials out of readiness controls.")
    with tempfile.TemporaryDirectory(prefix="studio-readiness-") as home:
        env = {k: os.environ[k] for k in ("PATH", "SSL_CERT_FILE", "DOCKER_HOST") if k in os.environ}
        process = subprocess.Popen(
            [sys.executable, "-I", str(Path(__file__).with_name("readiness_worker.py")), *args],
            cwd=home,
            env={**env, "HOME": home, **(chat if probe.tier != "1" else {})},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, _ = process.communicate(
                json.dumps(embeddings if probe.tier in {"2", "all"} else {}).encode(), timeout=90
            )
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise ValueError("Readiness check exceeded the 90-second deadline.") from None
    try:
        result = json.loads(stdout)
    except ValueError:
        if probe.action == "models":
            raise ValueError(
                "Catalog discovery failed. Check the saved chat credential, endpoint and TLS trust."
            ) from None
        raise ValueError("Readiness check failed. Check the scope and installed evaluator.") from None

    def scrub(value):
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if isinstance(value, str):
            for secret in sorted(secrets, key=len, reverse=True):
                value = value.replace(secret, "[redacted]")
        return value

    return scrub(result), process.returncode
