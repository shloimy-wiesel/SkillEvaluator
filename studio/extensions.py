"""Install production feature routers and their named project entry routes here."""

from .editor_routes import router as editor_router
from .overlap import OVERLAP
from .overlap import router as overlap_router
from .providers import router as provider_router
from .runs import router as runs_router
from .static_job import STATIC

ROUTERS = (editor_router, provider_router, runs_router, overlap_router)
PROJECT_LINKS = (
    ("Edit skill", "skill_editor"),
    ("Provider settings", "provider_settings"),
    ("Evaluation runs", "runs_index"),
    ("Evaluate overlap", "overlap_form"),
)
JOB_DEFINITIONS = (STATIC, OVERLAP)
