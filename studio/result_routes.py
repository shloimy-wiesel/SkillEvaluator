"""Route pairs for the exported evidence screens and their scoped JSON views."""

from fastapi import APIRouter, HTTPException
from fastapi.routing import APIRoute


class EvidenceAPI(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def scoped(request):
            try:
                response = await handler(request)
                response.headers["Cache-Control"] = "no-store"
                return response
            except HTTPException as exc:
                if isinstance(exc.detail, str):
                    raise HTTPException(exc.status_code, {"code": "evidence_error", "message": exc.detail}) from exc
                raise

        return scoped


def route_pair(prefix):
    return APIRouter(prefix=prefix), APIRouter(prefix="/api/v1" + prefix, route_class=EvidenceAPI)
