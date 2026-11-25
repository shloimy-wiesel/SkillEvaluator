"""Install production feature routers and their named project entry routes here."""

from .assets import router as assets_router
from .ci_routes import router as ci_router
from .editor_routes import router as editor_router
from .grader_job import GRADER
from .live_job import LIVE
from .live_routes import router as live_router
from .providers import router as provider_router
from .runs import router as runs_router
from .static_job import STATIC

ROUTERS = (editor_router, provider_router, runs_router, ci_router, assets_router, live_router)
PROJECT_LINKS = (
    ("Edit skill", "skill_editor"),
    ("Provider settings", "provider_settings"),
    ("Evaluation runs", "runs_index"),
    ("Live Tier 3", "live_index"),
    ("Evaluation assets", "assets"),
    ("Repository CI", "repository_ci"),
)
JOB_DEFINITIONS = (STATIC, GRADER, LIVE)
