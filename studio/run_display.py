"""Project immutable job inputs onto the author-facing configuration."""

from pydantic import BaseModel, JsonValue

from .changed_files import ChangedOptions
from .experiment_jobs import DecoyControls, InteractionControls, Observations
from .expert_options import FIELDS
from .grader_job import QualificationControls
from .live_job import Controls
from .static_job import StaticOptions
from .workspace import Project


class RunDisplay(BaseModel):
    id: str
    sha: str
    folder: str
    kind: str
    status: str
    progress: str
    created: str
    exit_code: int | None
    options: dict[str, JsonValue]
    markdown: str | None


class DisplayModels(BaseModel):
    judge: str
    agents: list[str]


class RunStatus(BaseModel):
    project: Project
    run: RunDisplay
    report: JsonValue = None
    models: DisplayModels | None


def configuration(kind, saved):
    from .overlap import Inputs

    controls = {
        "tier1-static": StaticOptions,
        "changed-files-v1": ChangedOptions,
        "tier3-live-v1": Controls,
        "tier2-overlap-v1": Inputs,
        "validate-grader": QualificationControls,
        "external-metrics-v1": Observations,
        "select-decoys-v1": DecoyControls,
        "skill-interaction-v1": InteractionControls,
    }
    if kind == "expert-check-v1":
        fields = FIELDS.get(saved.get("action"), set()) | {"action"}
    elif kind in controls:
        fields = set(controls[kind].model_fields)
    else:
        return {}
    if kind == "tier3-live-v1":
        fields.update(("provider", "judge_model", "source_repository", "evaluator_revision"))
    if kind in ("select-decoys-v1", "skill-interaction-v1"):
        fields.update(("provider", "profile_model"))
    result = {key: value for key, value in saved.items() if key in fields and value is not None}
    if kind in ("expert-check-v1", "tier2-overlap-v1"):
        for role in ("chat", "embeddings"):
            if profile := saved.get(role):
                result[role] = {key: profile[key] for key in ("provider", "model")}
    elif kind == "validate-grader" and (profile := saved.get("chat")):
        result["chat"] = {"provider": profile[0], "model": profile[1]}
    return result
