"""Chat endpoints: advance one research turn, either as a single response or an SSE stream."""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from agentdrops.api.sessions import SessionStore
from agentdrops.api.v1.schema import ChatRequest, ChatResponse
from agentdrops.observability.logging import bind_run_id
from agentdrops.observability.tracing import traced_span
from agentdrops.types.error_codes import BadGatewayError, fastAPIErrorResponseModels
from agentdrops.types.response import ErrorResponse, SuccessResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

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


_CHAT_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_502_BAD_GATEWAY: fastAPIErrorResponseModels[status.HTTP_502_BAD_GATEWAY]
}


@router.post("/chat", response_model=SuccessResponse[ChatResponse], responses=_CHAT_ERROR_RESPONSES)
async def chat(request: Request, body: ChatRequest) -> SuccessResponse[ChatResponse]:
    """Advance one chat turn: clarify, research, and report, resuming state via `thread_id`."""
    thread_id = body.thread_id or str(uuid.uuid4())
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    sessions: SessionStore = request.app.state.sessions
    sessions.touch(thread_id, title=body.message[:TITLE_MAX_LENGTH])
    graph = request.app.state.graph
    inputs = {"messages": [HumanMessage(content=body.message)]}

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


@router.post("/chat/stream")
async def chat_stream(request: Request, body: ChatRequest) -> StreamingResponse:
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
    thread_id = body.thread_id or str(uuid.uuid4())
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    graph = request.app.state.graph
    sessions: SessionStore = request.app.state.sessions
    sessions.touch(thread_id, title=body.message[:TITLE_MAX_LENGTH])
    inputs = {"messages": [HumanMessage(content=body.message)]}

    async def events() -> AsyncIterator[str]:
        try:
            async for event in _run_graph_turn(graph, inputs, config, thread_id, sessions):
                yield _sse(event)
        except Exception as exc:
            logger.exception("chat/stream turn failed for thread_id=%s", thread_id)
            sessions.set_status(thread_id, "failed")
            yield _sse({"type": "error", "thread_id": thread_id, "message": str(exc)})

    return StreamingResponse(events(), media_type="text/event-stream")
