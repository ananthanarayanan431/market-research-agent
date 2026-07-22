"""Chat endpoints: advance one research turn, either as a single response or an SSE stream."""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import StreamingResponse

from agentdrops.api.v1.schema import ChatRequest, ChatResponse
from agentdrops.service.chat_service import ChatService
from agentdrops.types.error_codes import BadGatewayError, fastAPIErrorResponseModels
from agentdrops.types.response import ErrorResponse, SuccessResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


def _sse(payload: dict[str, Any]) -> str:
    """Format one SSE event as a `data:` line, per the text/event-stream framing."""
    return f"data: {json.dumps(payload)}\n\n"


_CHAT_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_502_BAD_GATEWAY: fastAPIErrorResponseModels[status.HTTP_502_BAD_GATEWAY]
}


@router.post(
    "/chat",
    response_model=SuccessResponse[ChatResponse],
    status_code=status.HTTP_200_OK,
    summary="Advance a chat turn",
    responses=_CHAT_ERROR_RESPONSES,
)
async def chat(request: Request, body: ChatRequest) -> SuccessResponse[ChatResponse]:
    """Advance one chat turn: clarify, research, and report, resuming state via `thread_id`."""
    thread_id = body.thread_id or str(uuid.uuid4())
    service: ChatService = request.app.state.chat_service

    terminal: dict[str, Any] | None = None
    try:
        async for event in service.run_turn(thread_id, body.message, operation="chat"):
            terminal = event
    except Exception as exc:
        logger.exception("chat turn failed for thread_id=%s", thread_id)
        await service.record_failure(thread_id, operation="chat", error=str(exc))
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


@router.post(
    "/chat/stream",
    status_code=status.HTTP_200_OK,
    summary="Advance a chat turn, streamed via SSE",
)
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
    service: ChatService = request.app.state.chat_service

    async def events() -> AsyncIterator[str]:
        try:
            async for event in service.run_turn(
                thread_id, body.message, operation="chat_stream"
            ):
                yield _sse(event)
        except Exception as exc:
            logger.exception("chat/stream turn failed for thread_id=%s", thread_id)
            await service.record_failure(thread_id, operation="chat_stream", error=str(exc))
            yield _sse({"type": "error", "thread_id": thread_id, "message": str(exc)})

    return StreamingResponse(events(), media_type="text/event-stream")
