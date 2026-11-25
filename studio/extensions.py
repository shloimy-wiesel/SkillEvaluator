"""Install production feature routers and their named project entry routes here."""

from .runs import router as runs_router
from .static_job import STATIC

ROUTERS = (runs_router,)
PROJECT_LINKS = (("Evaluation runs", "runs_index"),)
JOB_DEFINITIONS = (STATIC,)
