"""Postgres-backed session registry: title/status/report/sources per thread.

Backs the sidebar listing and the reopen-a-completed-run endpoints. Persisted via the ORM
(`agentdrops.db.models.SessionTable`) against the `sessions` table
(`db/migrations/versions/0001_create_sessions_and_audit_log.py`), so state survives a process
restart — unlike the compiled graph's `InMemorySaver` checkpointer, which this does not touch.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from typing import cast as type_cast

from sqlalchemy import cast as sql_cast
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import func

from agentdrops.db.models import SessionTable

Status = Literal["clarifying", "running", "done", "failed"]


@dataclass
class SessionRecord:
    """One research thread's session-level metadata, as opposed to the graph's own state."""

    thread_id: str
    title: str
    created_at: datetime
    status: Status = "clarifying"
    report: str | None = None
    sources: list[dict[str, str]] = field(default_factory=list)


def _to_record(row: SessionTable) -> SessionRecord:
    return SessionRecord(
        thread_id=row.thread_id,
        title=row.title,
        created_at=row.created_at,
        status=type_cast(Status, row.status),
        report=row.report,
        sources=row.sources,
    )


class SessionStore:
    """Tracks one `SessionRecord` per thread_id in Postgres, via a shared ORM session factory."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def touch(self, thread_id: str, *, title: str) -> SessionRecord:
        """Create a session record the first time a thread is seen; a no-op afterward."""
        async with self._session_factory() as session:
            stmt = (
                insert(SessionTable)
                .values(thread_id=thread_id, title=title)
                .on_conflict_do_nothing(index_elements=["thread_id"])
                .returning(SessionTable)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                row = await session.get(SessionTable, thread_id)
            await session.commit()
            assert row is not None
            return _to_record(row)

    async def set_status(
        self, thread_id: str, status: Status, *, report: str | None = None
    ) -> None:
        async with self._session_factory() as session:
            values: dict[str, object] = {"status": status, "updated_at": func.now()}
            if report is not None:
                values["report"] = report
            await session.execute(
                update(SessionTable).where(SessionTable.thread_id == thread_id).values(**values)
            )
            await session.commit()

    async def add_source(self, thread_id: str, topic: str, summary: str) -> None:
        async with self._session_factory() as session:
            new_item = [{"topic": topic, "summary": summary}]
            await session.execute(
                update(SessionTable)
                .where(SessionTable.thread_id == thread_id)
                .values(
                    sources=SessionTable.sources.op("||")(sql_cast(new_item, JSONB)),
                    updated_at=func.now(),
                )
            )
            await session.commit()

    async def get(self, thread_id: str) -> SessionRecord | None:
        async with self._session_factory() as session:
            row = await session.get(SessionTable, thread_id)
            return _to_record(row) if row is not None else None

    async def list_recent(self) -> list[SessionRecord]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(SessionTable).order_by(SessionTable.created_at.desc())
            )
            return [_to_record(row) for row in result.scalars().all()]
