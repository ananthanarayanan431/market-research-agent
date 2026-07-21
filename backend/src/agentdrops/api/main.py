"""FastAPI app exposing the market-research agent over /chat and /chat/stream."""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.messages import HumanMessage

from agentdrops.agents.graph import build_market_researcher
from agentdrops.api.schema import (
    ChatRequest,
    ChatResponse,
    ReportResponse,
    ResearchStatusResponse,
    SessionsResponse,
    SessionSummary,
)
from agentdrops.api.sessions import SessionStore
from agentdrops.config import get_settings
from agentdrops.observability.logging import bind_run_id
from agentdrops.observability.setup import configure_observability, instrument_fastapi
from agentdrops.observability.tracing import traced_span
from agentdrops.types.error_codes import (
    BadGatewayError,
    Error,
    NotFoundError,
    ValidationError,
    fastAPIErrorResponseModels,
)
from agentdrops.types.response import ErrorResponse, Response, SuccessResponse

logger = logging.getLogger(__name__)

# A session's title is the opening message, trimmed for the sidebar.
TITLE_MAX_LENGTH = 80

# Top-level graph nodes that should surface as a progress step in the SSE stream.
NODE_LABELS: dict[str, str] = {
    "clarify_with_user": "Reviewing your request",
    "write_research_brief": "Planning research approach",
    "supervisor": "Coordinating research",
    "final_report_generation": "Synthesizing findings",
}


def _sse(payload: dict[str, Any]) -> str:
    """Format one SSE event as a `data:` line, per the text/event-stream framing."""
    return f"data: {json.dumps(payload)}\n\n"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the shared httpx client, compiled graph, and session registry, once per process.

    Telemetry is configured *before* the httpx client and the graph are built: both the httpx
    and LangChain instrumentors patch at import/class level, so anything constructed ahead of
    them would never be traced.
    """
    settings = get_settings()
    providers = configure_observability(settings)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            app.state.graph = build_market_researcher(settings, client)
            app.state.sessions = SessionStore()
            yield
    finally:
        providers.shutdown()


app = FastAPI(title="Agentdrops Market Research Agent", lifespan=lifespan)
instrument_fastapi(app)

# Dev-only: the Next.js frontend runs on a different origin (localhost:3000) and streams
# /chat/stream via fetch, which requires CORS headers even for same-machine requests.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


async def _run_graph_turn(
    graph: Any,
    inputs: dict[str, Any],
    config: dict[str, Any],
    thread_id: str,
    sessions: SessionStore,
) -> AsyncIterator[dict[str, Any]]:
    """Drive one graph turn to completion, yielding every SSE-shaped event along the way.

    The single place that calls `graph.astream` — shared by `/chat` (which only keeps the
    terminal `clarify`/`done` event) and `/chat/stream` (which forwards every event to the
    client), so both get the same source-persistence and session-status side effects instead of
    `/chat` silently dropping the `source` events `/chat/stream` picks up.

    The whole turn runs inside one `research.turn` span, and inside `bind_run_id(thread_id)` so
    every log line emitted anywhere in the graph carries the thread it belongs to — that is what
    makes a single run filterable end-to-end in SigNoz.
    """
    with bind_run_id(thread_id), traced_span("research.turn", thread_id=thread_id) as span:
        outcome = "incomplete"
        try:
            async for stream_type, chunk in graph.astream(
                inputs, config=config, stream_mode=["updates", "custom"]
            ):
                if stream_type == "custom":
                    if chunk.get("type") == "source":
                        sessions.add_source(thread_id, chunk["topic"], chunk["summary"])
                        span.add_event("research.source", {"topic": chunk["topic"]})
                    yield chunk
                    continue
                for node_name, node_output in chunk.items():
                    if node_name == "clarify_with_user" and node_output.get("needs_clarification"):
                        question = str(node_output["messages"][-1].content)
                        sessions.set_status(thread_id, "clarifying")
                        outcome = "clarify"
                        yield {"type": "clarify", "thread_id": thread_id, "response": question}
                        return
                    if node_name == "final_report_generation":
                        report = node_output["final_report"]
                        sessions.set_status(thread_id, "done", report=report)
                        outcome = "done"
                        span.set_attribute("research.report_chars", len(report))
                        yield {"type": "done", "thread_id": thread_id, "report": report}
                        return
                    if node_name == "supervisor":
                        sessions.set_status(thread_id, "running")
                    label = NODE_LABELS.get(node_name)
                    if label:
                        span.add_event("research.stage", {"stage": label})
                        yield {"type": "progress", "step": label}
        finally:
            span.set_attribute("research.outcome", outcome)


_CHAT_ERROR_RESPONSES = {
    status.HTTP_502_BAD_GATEWAY: fastAPIErrorResponseModels[status.HTTP_502_BAD_GATEWAY]
}


@app.post("/chat", response_model=SuccessResponse[ChatResponse], responses=_CHAT_ERROR_RESPONSES)
async def chat(request: ChatRequest) -> SuccessResponse[ChatResponse]:
    """Advance one chat turn: clarify, research, and report, resuming state via `thread_id`."""
    thread_id = request.thread_id or str(uuid.uuid4())
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    sessions: SessionStore = app.state.sessions
    sessions.touch(thread_id, title=request.message[:TITLE_MAX_LENGTH])
    graph = app.state.graph
    inputs = {"messages": [HumanMessage(content=request.message)]}

    terminal: dict[str, Any] | None = None
    try:
        async for event in _run_graph_turn(graph, inputs, config, thread_id, sessions):
            terminal = event
    except Exception as exc:
        logger.exception("chat turn failed for thread_id=%s", thread_id)
        sessions.set_status(thread_id, "failed")
        raise ErrorResponse(
            BadGatewayError(message="Research agent failed to complete this turn")
        ) from exc

    assert terminal is not None
    if terminal["type"] == "done":
        return SuccessResponse(
            data=ChatResponse(
                thread_id=thread_id,
                response=terminal["report"],
                is_followup=False,
                report=terminal["report"],
            )
        )
    return SuccessResponse(
        data=ChatResponse(thread_id=thread_id, response=terminal["response"], is_followup=True)
    )


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Advance one chat turn, streaming progress/source events as the graph runs, via SSE.

    Event shapes:
    - `{"type": "progress", "step": str, "detail"?: str}` — a top-level stage started, or (from
      inside the supervisor) one delegated research topic began.
    - `{"type": "source", "topic": str, "summary": str}` — one delegated topic finished.
    - `{"type": "clarify", "thread_id": str, "response": str}` — terminal: the agent needs more
      information before it can research; the turn ends here.
    - `{"type": "done", "thread_id": str, "report": str}` — terminal: the final report is ready.
    - `{"type": "error", "thread_id": str, "message": str}` — terminal: the run failed.
    """
    thread_id = request.thread_id or str(uuid.uuid4())
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    graph = app.state.graph
    sessions: SessionStore = app.state.sessions
    sessions.touch(thread_id, title=request.message[:TITLE_MAX_LENGTH])
    inputs = {"messages": [HumanMessage(content=request.message)]}

    async def events() -> AsyncIterator[str]:
        try:
            async for event in _run_graph_turn(graph, inputs, config, thread_id, sessions):
                yield _sse(event)
        except Exception as exc:
            logger.exception("chat/stream turn failed for thread_id=%s", thread_id)
            sessions.set_status(thread_id, "failed")
            yield _sse({"type": "error", "thread_id": thread_id, "message": str(exc)})

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/research/sessions", response_model=SuccessResponse[SessionsResponse])
async def list_sessions() -> SuccessResponse[SessionsResponse]:
    """List every known research thread, most recently started first, for the sidebar."""
    sessions: SessionStore = app.state.sessions
    return SuccessResponse(
        data=SessionsResponse(
            sessions=[
                SessionSummary(
                    id=s.thread_id,
                    title=s.title,
                    created_at=s.created_at.isoformat(),
                    status=s.status,
                )
                for s in sessions.list_recent()
            ]
        )
    )


@app.get(
    "/research/{thread_id}",
    response_model=SuccessResponse[ResearchStatusResponse],
    responses={status.HTTP_404_NOT_FOUND: fastAPIErrorResponseModels[status.HTTP_404_NOT_FOUND]},
)
async def get_research_status(thread_id: str) -> SuccessResponse[ResearchStatusResponse]:
    """Read one thread's current status: the session store's `failed` if set, else the graph's
    own checkpoint (a failed run may leave an incomplete checkpoint the graph can't classify)."""
    sessions: SessionStore = app.state.sessions
    session = sessions.get(thread_id)
    if session is not None and session.status == "failed":
        return SuccessResponse(
            data=ResearchStatusResponse(
                thread_id=thread_id, status="failed", research_brief=None, report=None
            )
        )

    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    graph = app.state.graph
    state = await graph.aget_state(config)
    if not state.values:
        raise ErrorResponse(NotFoundError(message="Unknown thread_id"))

    values = state.values
    if values.get("final_report"):
        research_status: str = "done"
    elif values.get("needs_clarification"):
        research_status = "clarifying"
    else:
        research_status = "running"

    return SuccessResponse(
        data=ResearchStatusResponse(
            thread_id=thread_id,
            status=research_status,  # type: ignore[arg-type]
            research_brief=values.get("research_brief") or None,
            report=values.get("final_report") or None,
        )
    )


@app.get(
    "/research/{thread_id}/report",
    response_model=SuccessResponse[ReportResponse],
    responses={status.HTTP_404_NOT_FOUND: fastAPIErrorResponseModels[status.HTTP_404_NOT_FOUND]},
)
async def get_research_report(thread_id: str) -> SuccessResponse[ReportResponse]:
    """Fetch a completed thread's report and sources, so the drawer can reopen without a rerun."""
    sessions: SessionStore = app.state.sessions
    session = sessions.get(thread_id)
    if session is None or session.report is None:
        raise ErrorResponse(NotFoundError(message="Report not available for this thread_id"))

    return SuccessResponse(
        data=ReportResponse(thread_id=thread_id, report=session.report, sources=session.sources)
    )
