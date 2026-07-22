"""FastAPI app exposing the market-research agent over the versioned `/v1` API."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from agentdrops.agents.graph import build_market_researcher
from agentdrops.api.v1 import router as v1_router
from agentdrops.config import get_settings
from agentdrops.db.engine import create_engine, create_session_factory
from agentdrops.observability.setup import configure_observability, instrument_fastapi
from agentdrops.repository.audit import AuditLog
from agentdrops.repository.sessions import SessionStore
from agentdrops.service.chat_service import ChatService
from agentdrops.service.research_service import ResearchService
from agentdrops.service.sessions_service import SessionsService
from agentdrops.types.error_codes import Error, ValidationError
from agentdrops.types.response import ErrorResponse, Response, SuccessResponse

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the shared httpx client, DB engine, compiled graph, and session registry, once per
    process.

    Telemetry is configured *before* the httpx client and the graph are built: both the httpx
    and LangChain instrumentors patch at import/class level, so anything constructed ahead of
    them would never be traced.
    """
    settings = get_settings()
    providers = configure_observability(settings)
    try:
        engine = create_engine(settings)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                session_factory = create_session_factory(engine)
                graph = build_market_researcher(settings, client)
                sessions = SessionStore(session_factory)
                audit = AuditLog(session_factory)
                app.state.engine = engine
                app.state.chat_service = ChatService(graph, sessions, audit)
                app.state.research_service = ResearchService(graph, sessions)
                app.state.sessions_service = SessionsService(sessions)
                yield
        finally:
            await engine.dispose()
    finally:
        providers.shutdown()


app = FastAPI(title="Agentdrops Market Research Agent", lifespan=lifespan)
instrument_fastapi(app)

# Dev-only: the Next.js frontend runs on a different origin (localhost:3000) and streams
# /v1/chat/stream via fetch, which requires CORS headers even for same-machine requests.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router)


def _error_content(error: Error) -> dict[str, Any]:
    return Response[Error](success=False, data=error).model_dump()


@app.exception_handler(ErrorResponse)
async def handle_error_response(_request: Request, exc: ErrorResponse) -> JSONResponse:
    """The one place a route's `raise ErrorResponse(...)` becomes a JSON body."""
    return JSONResponse(status_code=exc.error.code, content=_error_content(exc.error))


@app.exception_handler(HTTPException)
async def handle_http_exception(_request: Request, exc: HTTPException) -> JSONResponse:
    """Normalizes FastAPI/Starlette-raised HTTPExceptions (unmatched routes, method not
    allowed) into the same envelope as routes that raise `ErrorResponse` directly."""
    error = Error(code=exc.status_code, description=str(exc.detail))
    return JSONResponse(status_code=exc.status_code, content=_error_content(error))


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    error = ValidationError(message=str(exc.errors()))
    return JSONResponse(status_code=error.code, content=_error_content(error))


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler: never leak internal exception details to the client."""
    logger.exception("unhandled error while processing %s %s", request.method, request.url.path)
    error = Error(code=500, description="Internal Server Error")
    return JSONResponse(status_code=error.code, content=_error_content(error))


@app.get("/health", response_model=SuccessResponse[dict[str, str]])
async def health() -> SuccessResponse[dict[str, str]]:
    """Liveness probe."""
    return SuccessResponse(data={"status": "ok"})
