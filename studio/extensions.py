"""Install production feature routers and their named project entry routes here."""

from .ci_routes import router as ci_router
from .editor_routes import router as editor_router
from .providers import router as provider_router

ROUTERS = (ci_router, editor_router, provider_router)
PROJECT_LINKS = (
    ("Repository CI", "repository_ci"),
    ("Edit skill", "skill_editor"),
    ("Provider settings", "provider_settings"),
)
