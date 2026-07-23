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
from redis.asyncio import Redis

from agentdrops.api.v1.schema import ChatQueuedResponse, ChatRequest
from agentdrops.config.constants import CHAT_TITLE_MAX_LENGTH
from agentdrops.jobs.events import subscribe_events
from agentdrops.repository.sessions import SessionRecord, SessionStore
from agentdrops.types.response import SuccessResponse
from agentdrops.worker.tasks import run_turn_task

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

_TERMINAL_STATUSES = {"done", "clarifying", "failed"}
_TERMINAL_EVENT_TYPES = {"clarify", "done", "error"}


def _sse(payload: dict[str, Any]) -> str:
    """Format one SSE event as a `data:` line, per the text/event-stream framing."""
    return f"data: {json.dumps(payload)}\n\n"


def _terminal_event_from_session(thread_id: str, session: SessionRecord) -> dict[str, Any] | None:
    """Reconstruct the terminal SSE event from a session record already settled by the time
    `/chat/stream` subscribes — the race window between enqueueing and subscribing."""
    if session.status == "done":
        return {"type": "done", "thread_id": thread_id, "report": session.report}
    if session.status == "clarifying":
        return {
            "type": "clarify",
            "thread_id": thread_id,
            "response": session.clarify_question or "",
        }
    if session.status == "failed":
        return {
            "type": "error",
            "thread_id": thread_id,
            "message": session.error or "Research failed",
        }
    return None


@router.post(
    "/chat",
    response_model=SuccessResponse[ChatQueuedResponse],
    status_code=status.HTTP_200_OK,
    summary="Enqueue a chat turn",
)
async def chat(request: Request, body: ChatRequest) -> SuccessResponse[ChatQueuedResponse]:
    """Enqueue one chat turn for background execution; poll GET /research/{thread_id} for the
    result, or use /chat/stream instead to observe it live."""
    thread_id = body.thread_id or str(uuid.uuid4())
    sessions: SessionStore = request.app.state.sessions
    await sessions.touch(thread_id, title=body.message[:CHAT_TITLE_MAX_LENGTH])
    run_turn_task.delay(thread_id, body.message, "chat")
    return SuccessResponse(data=ChatQueuedResponse(thread_id=thread_id))


@router.post(
    "/chat/stream",
    status_code=status.HTTP_200_OK,
    summary="Advance a chat turn, streamed via SSE",
)
async def chat_stream(request: Request, body: ChatRequest) -> StreamingResponse:
    """Enqueue one chat turn, then stream its progress/source events as the worker runs it, via
    SSE — event shapes unchanged from before this turn ran in a background worker:

    - `{"type": "progress", "step": str, "detail"?: str}` — a top-level stage started, or (from
      inside the supervisor) one delegated research topic began.
    - `{"type": "source", "topic": str, "summary": str}` — one delegated topic finished.
    - `{"type": "clarify", "thread_id": str, "response": str}` — terminal: the agent needs more
      information before it can research; the turn ends here.
    - `{"type": "done", "thread_id": str, "report": str}` — terminal: the final report is ready.
    - `{"type": "error", "thread_id": str, "message": str}` — terminal: the run failed.
    """
    thread_id = body.thread_id or str(uuid.uuid4())
    sessions: SessionStore = request.app.state.sessions
    redis: Redis = request.app.state.redis
    await sessions.touch(thread_id, title=body.message[:CHAT_TITLE_MAX_LENGTH])
    run_turn_task.delay(thread_id, body.message, "chat_stream")

    async def events() -> AsyncIterator[str]:
        # The task may have already finished by the time we get here (enqueue-then-subscribe
        # race) — check the session record first rather than subscribing blind and hanging.
        session = await sessions.get(thread_id)
        if session is not None and session.status in _TERMINAL_STATUSES:
            terminal = _terminal_event_from_session(thread_id, session)
            if terminal is not None:
                yield _sse(terminal)
                return
        try:
            async for event in subscribe_events(redis, thread_id):
                yield _sse(event)
                if event.get("type") in _TERMINAL_EVENT_TYPES:
                    return
        except Exception as exc:
            # e.g. the Redis connection drops mid-stream — surface it to the client instead of
            # letting the SSE response hang open with no further events ever arriving.
            logger.exception("chat/stream subscription failed for thread_id=%s", thread_id)
            yield _sse({"type": "error", "thread_id": thread_id, "message": str(exc)})

    return StreamingResponse(events(), media_type="text/event-stream")
