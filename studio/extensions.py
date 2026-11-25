"""Install production feature routers and their named project entry routes here."""

from .dataset_routes import router as dataset_router
from .editor_routes import router as editor_router
from .providers import router as provider_router

ROUTERS = (editor_router, provider_router, dataset_router)
PROJECT_LINKS = (("Edit skill", "skill_editor"), ("Provider settings", "provider_settings"), ("Datasets", "datasets"))
