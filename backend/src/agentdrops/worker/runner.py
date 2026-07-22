"""Drives one chat turn inside a Celery worker via `ChatService`, relaying every event to Redis
pub/sub — the worker-process counterpart of `api/v1/chat.py`'s routes, which used to drive
`ChatService.run_turn` directly before execution moved off the request/response cycle.
"""

import logging

from redis.asyncio import Redis

from agentdrops.jobs.events import publish_event
from agentdrops.service.chat_service import ChatService

logger = logging.getLogger(__name__)


async def run_turn(
    chat_service: ChatService, thread_id: str, message: str, *, operation: str, redis: Redis
) -> None:
    try:
        async for event in chat_service.run_turn(thread_id, message, operation=operation):
            await publish_event(redis, thread_id, event)
    except Exception as exc:
        logger.exception("worker turn failed for thread_id=%s", thread_id)
        await chat_service.record_failure(thread_id, operation=operation, error=str(exc))
        await publish_event(
            redis, thread_id, {"type": "error", "thread_id": thread_id, "message": str(exc)}
        )
