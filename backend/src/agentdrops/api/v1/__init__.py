"""v1 HTTP surface: chat + research routers, mounted under `/v1`."""

from fastapi import APIRouter

from agentdrops.api.v1.chat import router as chat_router
from agentdrops.api.v1.research import router as research_router

router = APIRouter(prefix="/v1")
router.include_router(chat_router)
router.include_router(research_router)

__all__ = ["router"]
