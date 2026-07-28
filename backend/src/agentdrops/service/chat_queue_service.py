"""Chat queue service: enqueues one chat turn for background execution. The router-facing
counterpart of `ChatService`, which the Celery worker still uses to actually drive a turn —
`api/v1/chat.py` no longer touches `SessionStore` directly."""

from agentdrops.config.constants import CHAT_TITLE_MAX_LENGTH
from agentdrops.repository.sessions import SessionStore
from agentdrops.worker.tasks import run_turn_task


class ChatQueueService:
    def __init__(self, sessions: SessionStore) -> None:
        self._sessions = sessions

    async def enqueue(self, thread_id: str, message: str, *, operation: str) -> None:
        await self._sessions.touch(thread_id, title=message[:CHAT_TITLE_MAX_LENGTH])
        await self._sessions.set_status(thread_id, "queued")
        run_turn_task.delay(thread_id, message, operation)

    async def mark_failed(self, thread_id: str, error: str) -> None:
        """Mark a turn failed due to an API-side enqueue/subscribe problem (e.g. Redis or a broker
        outage) — never overwrites a session the worker already settled (`done`/`clarifying`/
        `failed`), since in that case the turn's own outcome is already correctly recorded and what
        went wrong is purely our own delivery/connection problem, not the turn's result."""
        session = await self._sessions.get(thread_id)
        if session is not None and session.status in ("done", "clarifying", "failed"):
            return
        await self._sessions.set_status(thread_id, "failed", error=error)
