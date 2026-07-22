"""Sessions service: recent research threads for the sidebar."""

from agentdrops.api.v1.schema import SessionSummary
from agentdrops.repository.sessions import SessionStore


class SessionsService:
    """Lists known research threads for the sidebar."""

    def __init__(self, sessions: SessionStore) -> None:
        self._sessions = sessions

    async def list_recent(self) -> list[SessionSummary]:
        """Every known research thread, most recently started first."""
        return [
            SessionSummary(
                id=s.thread_id,
                title=s.title,
                created_at=s.created_at.isoformat(),
                status=s.status,
            )
            for s in await self._sessions.list_recent()
        ]
