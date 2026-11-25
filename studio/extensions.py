"""Install production feature routers and their named project entry routes here."""

from .editor_routes import router as editor_router

ROUTERS = (editor_router,)
PROJECT_LINKS = (("Edit skill", "skill_editor"),)
