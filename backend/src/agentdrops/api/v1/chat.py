"""Chat endpoints: enqueue one research turn, either acknowledged immediately or observed live
via SSE. Execution itself happens in a Celery worker (`agentdrops.worker.tasks.run_turn_task`) —
see `agentdrops/worker/runner.py` for the worker-side counterpart of what this module used to do
directly through `ChatService.run_turn`.
"""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import StreamingResponse

from agentdrops.api.v1.schema import ChatQueuedResponse, ChatRequest
from agentdrops.service.chat_queue_service import ChatQueueService
from agentdrops.types.error_codes import BadGatewayError, fastAPIErrorResponseModels
from agentdrops.types.response import ErrorResponse, SuccessResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

_CHAT_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_502_BAD_GATEWAY: fastAPIErrorResponseModels[status.HTTP_502_BAD_GATEWAY]
}


def _sse(payload: dict[str, Any]) -> str:
    """Format one SSE event as a `data:` line, per the text/event-stream framing."""
    return f"data: {json.dumps(payload)}\n\n"


@router.post(
    "/chat",
    response_model=SuccessResponse[ChatQueuedResponse],
    status_code=status.HTTP_200_OK,
    summary="Enqueue a chat turn",
    responses=_CHAT_ERROR_RESPONSES,
)
async def chat(request: Request, body: ChatRequest) -> SuccessResponse[ChatQueuedResponse]:
    """Enqueue one chat turn for background execution; poll GET /research/{thread_id} for the
    result, or use /chat/stream instead to observe it live."""
    thread_id = body.thread_id or str(uuid.uuid4())
    queue: ChatQueueService = request.app.state.chat_queue_service
    try:
        await queue.enqueue(thread_id, body.message, operation="chat")
    except Exception as exc:
        logger.exception("failed to enqueue chat turn for thread_id=%s", thread_id)
        try:
            await queue.mark_failed(thread_id, str(exc))
        except Exception:
            logger.exception("failed to mark session failed for thread_id=%s", thread_id)
        raise ErrorResponse(
            BadGatewayError(message="Failed to enqueue this research turn")
        ) from exc
    return SuccessResponse(data=ChatQueuedResponse(thread_id=thread_id))


@router.post(
    "/chat/stream",
    status_code=status.HTTP_200_OK,
    summary="Advance a chat turn, streamed via SSE",
)
async def chat_stream(request: Request, body: ChatRequest) -> StreamingResponse:
    """Subscribe to this thread's event channel, then enqueue one chat turn, streaming its
    progress/source events as the worker runs it, via SSE — event shapes unchanged from before
    this turn ran in a background worker:

    - `{"type": "progress", "step": str, "detail"?: str, "topic"?: str}` — a top-level stage
      started, or (from inside the supervisor, `topic` set) one delegated research topic began.
    - `{"type": "source", "topic": str, "summary": str}` — one delegated topic finished.
    - `{"type": "source_url", "topic": str, "tool_name": str, "title": str, "url": str}` — one
      individual search result was found while researching a delegated topic.
    - `{"type": "clarify", "thread_id": str, "response": str, "suggestions": list[str]}` —
      terminal: the agent needs more information before it can research; the turn ends here.
    - `{"type": "done", "thread_id": str, "report": str}` — terminal: the final report is ready.
    - `{"type": "error", "thread_id": str, "message": str}` — terminal: the run failed.

    Subscribing *before* enqueueing (rather than after) closes the race where a fast worker
    could publish an event before the API started listening for it — plain Redis pub/sub has no
    replay, so a message published to nobody is lost forever.
    """
    thread_id = body.thread_id or str(uuid.uuid4())
    queue: ChatQueueService = request.app.state.chat_queue_service

    async def events() -> AsyncIterator[str]:
        async for event in queue.stream(thread_id, body.message):
            yield _sse(event)

    return StreamingResponse(events(), media_type="text/event-stream")
