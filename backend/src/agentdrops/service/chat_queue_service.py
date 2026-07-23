"""Chat queue service: enqueues one chat turn for background execution and reconstructs the
terminal SSE event for a session that already settled before `/chat/stream`'s subscriber
attached. The router-facing counterpart of `ChatService`, which the Celery worker still uses to
actually drive a turn — `api/v1/chat.py` no longer touches `SessionStore` directly."""

from agentdrops.config.constants import CHAT_TITLE_MAX_LENGTH
from agentdrops.repository.sessions import SessionRecord, SessionStore
from agentdrops.worker.tasks import run_turn_task


class ChatQueueService:
    def __init__(self, sessions: SessionStore) -> None:
        self._sessions = sessions

    async def enqueue(self, thread_id: str, message: str, *, operation: str) -> None:
        await self._sessions.touch(thread_id, title=message[:CHAT_TITLE_MAX_LENGTH])
        run_turn_task.delay(thread_id, message, operation)

    async def get_session(self, thread_id: str) -> SessionRecord | None:
        return await self._sessions.get(thread_id)
