"""Chat queue service: enqueues one chat turn for background execution, and (for the streaming
route) owns the subscribe/enqueue/relay orchestration around it — `api/v1/chat.py` only extracts
request data and turns the resulting events into SSE. The router-facing counterpart of
`ChatService`, which the Celery worker still uses to actually drive a turn."""

import logging
from collections.abc import AsyncIterator
from typing import Any

from redis.asyncio import Redis

from agentdrops.config.constants import truncate_title
from agentdrops.jobs.events import consume_subscription, open_subscription
from agentdrops.repository.sessions import SessionStore
from agentdrops.worker.tasks import run_turn_task

logger = logging.getLogger(__name__)

_TERMINAL_EVENT_TYPES = {"clarify", "done", "error"}

_STREAM_ENQUEUE_ERROR_MESSAGE = "Failed to start or continue this research turn"


class ChatQueueService:
    def __init__(self, sessions: SessionStore, redis: Redis) -> None:
        self._sessions = sessions
        self._redis = redis

    async def enqueue(
        self, thread_id: str, message: str, *, operation: str, use_context_hub: bool = False
    ) -> None:
        await self._sessions.touch(thread_id, title=truncate_title(message))
        await self._sessions.set_status(thread_id, "queued")
        run_turn_task.delay(thread_id, message, operation, use_context_hub)

    async def mark_failed(self, thread_id: str, error: str) -> None:
        """Mark a turn failed due to an API-side enqueue/subscribe problem (e.g. Redis or a broker
        outage) — never overwrites a session the worker already settled (`done`/`clarifying`/
        `failed`), since in that case the turn's own outcome is already correctly recorded and what
        went wrong is purely our own delivery/connection problem, not the turn's result."""
        session = await self._sessions.get(thread_id)
        if session is not None and session.status in ("done", "clarifying", "failed"):
            return
        await self._sessions.set_status(thread_id, "failed", error=error)

    async def stream(
        self, thread_id: str, message: str, use_context_hub: bool = False
    ) -> AsyncIterator[dict[str, Any]]:
        """Subscribe to `thread_id`'s event channel, then enqueue one chat turn, yielding its
        progress/source events as the worker runs it — see `api/v1/chat.py::chat_stream` for the
        SSE event shapes this produces.

        Subscribing *before* enqueueing (rather than after) closes the race where a fast worker
        could publish an event before the caller started listening for it — plain Redis pub/sub
        has no replay, so a message published to nobody is lost forever.
        """
        try:
            async with open_subscription(self._redis, thread_id) as pubsub:
                await self.enqueue(
                    thread_id, message, operation="chat_stream", use_context_hub=use_context_hub
                )
                async for event in consume_subscription(pubsub):
                    yield event
                    if event.get("type") in _TERMINAL_EVENT_TYPES:
                        return
        except Exception:
            # e.g. Redis is unreachable, or enqueueing the Celery task failed — surface it to the
            # caller instead of leaving the stream open with nothing ever arriving, and mark the
            # session failed so it doesn't stay wedged at "queued" forever.
            logger.exception("chat/stream failed for thread_id=%s", thread_id)
            try:
                await self.mark_failed(thread_id, _STREAM_ENQUEUE_ERROR_MESSAGE)
            except Exception:
                logger.exception("failed to mark session failed for thread_id=%s", thread_id)
            yield {
                "type": "error",
                "thread_id": thread_id,
                "message": _STREAM_ENQUEUE_ERROR_MESSAGE,
            }
