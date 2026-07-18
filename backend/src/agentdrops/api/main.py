"""FastAPI app exposing the market-research agent over /chat and /chat/stream."""

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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
    """Build the shared httpx client, compiled graph, and session registry, once per process."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=30.0) as client:
        app.state.graph = build_market_researcher(settings, client)
        app.state.sessions = SessionStore()
        yield


app = FastAPI(title="Agentdrops Market Research Agent", lifespan=lifespan)

# Dev-only: the Next.js frontend runs on a different origin (localhost:3000) and streams
# /chat/stream via fetch, which requires CORS headers even for same-machine requests.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Advance one chat turn: clarify, research, and report, resuming state via `thread_id`."""
    thread_id = request.thread_id or str(uuid.uuid4())
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    sessions: SessionStore = app.state.sessions
    sessions.touch(thread_id, title=request.message[:TITLE_MAX_LENGTH])

    graph = app.state.graph
    inputs = {"messages": [HumanMessage(content=request.message)]}
    result = await graph.ainvoke(inputs, config=config)

    final_report = result.get("final_report")
    if final_report:
        sessions.set_status(thread_id, "done", report=final_report)
        return ChatResponse(
            thread_id=thread_id,
            response=final_report,
            is_followup=False,
            report=final_report,
        )

    sessions.set_status(thread_id, "clarifying")
    last_message = result["messages"][-1]
    return ChatResponse(thread_id=thread_id, response=str(last_message.content), is_followup=True)


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
    """
    thread_id = request.thread_id or str(uuid.uuid4())
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    graph = app.state.graph
    sessions: SessionStore = app.state.sessions
    sessions.touch(thread_id, title=request.message[:TITLE_MAX_LENGTH])
    inputs = {"messages": [HumanMessage(content=request.message)]}

    async def events() -> AsyncIterator[str]:
        async for stream_type, chunk in graph.astream(
            inputs, config=config, stream_mode=["updates", "custom"]
        ):
            if stream_type == "custom":
                if chunk.get("type") == "source":
                    sessions.add_source(thread_id, chunk["topic"], chunk["summary"])
                yield _sse(chunk)
                continue
            for node_name, node_output in chunk.items():
                if node_name == "clarify_with_user" and node_output.get("needs_clarification"):
                    question = str(node_output["messages"][-1].content)
                    sessions.set_status(thread_id, "clarifying")
                    yield _sse({"type": "clarify", "thread_id": thread_id, "response": question})
                    return
                if node_name == "final_report_generation":
                    report = node_output["final_report"]
                    sessions.set_status(thread_id, "done", report=report)
                    yield _sse({"type": "done", "thread_id": thread_id, "report": report})
                    return
                if node_name == "supervisor":
                    sessions.set_status(thread_id, "running")
                label = NODE_LABELS.get(node_name)
                if label:
                    yield _sse({"type": "progress", "step": label})

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/research/sessions", response_model=SessionsResponse)
async def list_sessions() -> SessionsResponse:
    """List every known research thread, most recently started first, for the sidebar."""
    sessions: SessionStore = app.state.sessions
    return SessionsResponse(
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


@app.get("/research/{thread_id}", response_model=ResearchStatusResponse)
async def get_research_status(thread_id: str) -> ResearchStatusResponse:
    """Read one thread's current status straight from the graph's checkpoint."""
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    graph = app.state.graph
    state = await graph.aget_state(config)
    if not state.values:
        raise HTTPException(status_code=404, detail="Unknown thread_id")

    values = state.values
    if values.get("final_report"):
        status: str = "done"
    elif values.get("needs_clarification"):
        status = "clarifying"
    else:
        status = "running"

    return ResearchStatusResponse(
        thread_id=thread_id,
        status=status,  # type: ignore[arg-type]
        research_brief=values.get("research_brief") or None,
        report=values.get("final_report") or None,
    )


@app.get("/research/{thread_id}/report", response_model=ReportResponse)
async def get_research_report(thread_id: str) -> ReportResponse:
    """Fetch a completed thread's report and sources, so the drawer can reopen without a rerun."""
    sessions: SessionStore = app.state.sessions
    session = sessions.get(thread_id)
    if session is None or session.report is None:
        raise HTTPException(status_code=404, detail="Report not available for this thread_id")

    return ReportResponse(thread_id=thread_id, report=session.report, sources=session.sources)
