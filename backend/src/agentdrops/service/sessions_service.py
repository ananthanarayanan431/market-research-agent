"""Sessions service: recent research threads for the sidebar."""

from agentdrops.api.v1.schema import SessionSummary
from agentdrops.repository.sessions import DeleteResult, SessionRecord, SessionStore


def _to_summary(record: SessionRecord) -> SessionSummary:
    return SessionSummary(
        id=record.thread_id,
        title=record.title,
        created_at=record.created_at.isoformat(),
        status=record.status,
        pinned=record.pinned,
    )


class SessionsService:
    """Lists and manages known research threads for the sidebar."""

    def __init__(self, sessions: SessionStore) -> None:
        self._sessions = sessions

    async def list_recent(self, query: str | None = None) -> list[SessionSummary]:
        """Pinned first, then most recently started; `query` filters by title."""
        return [_to_summary(s) for s in await self._sessions.list_recent(query)]

    async def update(
        self, thread_id: str, *, title: str | None = None, pinned: bool | None = None
    ) -> SessionSummary | None:
        """Rename and/or pin a session. Returns None if `thread_id` is unknown."""
        record = None
        if title is not None:
            record = await self._sessions.rename(thread_id, title)
            if record is None:
                return None
        if pinned is not None:
            record = await self._sessions.set_pinned(thread_id, pinned)
            if record is None:
                return None
        if record is None:
            record = await self._sessions.get(thread_id)
        return _to_summary(record) if record is not None else None

    async def delete(self, thread_id: str) -> DeleteResult:
        """Delete a session; refuses (`"in_progress"`) while its turn is still `queued`/`running`
        so the worker's terminal writes don't race a `sessions` row that vanished mid-turn."""
        return await self._sessions.delete(thread_id)
