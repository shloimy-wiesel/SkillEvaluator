"""Install production feature routers and their named project entry routes here."""

from .providers import router as provider_router
from .runs import router as runs_router
from .static_job import STATIC

ROUTERS = (provider_router, runs_router)
PROJECT_LINKS = (("Provider settings", "provider_settings"), ("Evaluation runs", "runs_index"))
JOB_DEFINITIONS = (STATIC,)
