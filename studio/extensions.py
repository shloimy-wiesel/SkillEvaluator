"""Install production feature routers and their named project entry routes here."""

from .assets import router as assets_router
from .ci_advanced import router as advanced_ci_router
from .ci_routes import router as ci_router
from .dataset_routes import router as dataset_router
from .editor_routes import router as editor_router
from .expert import EXPERT
from .expert import router as expert_router
from .grader_job import GRADER
from .live_job import LIVE
from .live_routes import router as live_router
from .overlap import OVERLAP
from .overlap import router as overlap_router
from .providers import router as provider_router
from .review import router as review_router
from .runs import router as runs_router
from .static_job import STATIC

ROUTERS = (
    editor_router,
    provider_router,
    runs_router,
    ci_router,
    assets_router,
    dataset_router,
    live_router,
    review_router,
    overlap_router,
    expert_router,
    advanced_ci_router,
)
PROJECT_LINKS = (
    ("Edit skill", "skill_editor"),
    ("Datasets", "datasets"),
    ("Provider settings", "provider_settings"),
    ("Evaluation runs", "runs_index"),
    ("Evaluate overlap", "overlap_form"),
    ("Live Tier 3", "live_index"),
    ("Evaluation assets", "assets"),
    ("Repository CI", "repository_ci"),
    ("Results dashboard", "results_dashboard"),
)
JOB_DEFINITIONS = (STATIC, GRADER, LIVE, OVERLAP, EXPERT)
