"""Postgres-backed audit trail: one row per completed `/v1/chat` or `/v1/chat/stream` call.

Persisted via the ORM (`agentdrops.db.models.AuditLogTable`) against the `audit_log` table
(`db/migrations/versions/0001_create_sessions_and_audit_log.py`).
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentdrops.db.models import AuditLogTable


class AuditLog:
    """Records one outcome row per chat turn, via the shared ORM session factory."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record(
        self,
        thread_id: str,
        *,
        operation: str,
        status: str,
        detail: dict[str, object] | None = None,
    ) -> None:
        async with self._session_factory() as session:
            session.add(
                AuditLogTable(
                    thread_id=thread_id,
                    operation=operation,
                    status=status,
                    detail=detail or {},
                )
            )
            await session.commit()
