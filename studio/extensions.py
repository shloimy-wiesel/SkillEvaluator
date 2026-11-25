"""Install production feature routers and their named project entry routes here."""

from .providers import router as provider_router

ROUTERS = (provider_router,)
PROJECT_LINKS = (("Provider settings", "provider_settings"),)
