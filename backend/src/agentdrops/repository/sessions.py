"""Postgres-backed session registry: title/status/report/sources per thread.

Backs the sidebar listing and the reopen-a-completed-run endpoints. Persisted via the ORM
(`agentdrops.db.models.SessionTable`) against the `sessions` table
(`db/migrations/versions/0001_create_sessions_and_audit_log.py`), so state survives a process
restart, independently of the compiled graph's own Postgres-backed checkpointer
(`agents/checkpointer.py`), which this store does not touch.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from typing import cast as type_cast

from sqlalchemy import cast as sql_cast
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import func

from agentdrops.db.models import SessionTable

Status = Literal["queued", "clarifying", "running", "done", "failed"]
DeleteResult = Literal["deleted", "not_found", "in_progress"]

# Statuses where the Celery worker either owns the row right now or is about to: deleting the
# `sessions` row underneath it makes the worker's terminal `set_status`/`AuditLog.record` calls
# race a row that no longer exists, which trips `fk_audit_log_thread_id_sessions` and discards an
# already-completed report.
_IN_FLIGHT_STATUSES: frozenset[Status] = frozenset({"queued", "running"})


@dataclass
class SessionRecord:
    """One research thread's session-level metadata, as opposed to the graph's own state."""

    thread_id: str
    title: str
    created_at: datetime
    status: Status = "queued"
    report: str | None = None
    sources: list[dict[str, str]] = field(default_factory=list)
    clarify_question: str | None = None
    error: str | None = None
    pinned: bool = False


def _to_record(row: SessionTable) -> SessionRecord:
    return SessionRecord(
        thread_id=row.thread_id,
        title=row.title,
        created_at=row.created_at,
        status=type_cast(Status, row.status),
        report=row.report,
        sources=row.sources,
        clarify_question=row.clarify_question,
        error=row.error,
        pinned=row.pinned,
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
        self,
        thread_id: str,
        status: Status,
        *,
        report: str | None = None,
        clarify_question: str | None = None,
        error: str | None = None,
    ) -> None:
        async with self._session_factory() as session:
            values: dict[str, object] = {"status": status, "updated_at": func.now()}
            if report is not None:
                values["report"] = report
            if clarify_question is not None:
                values["clarify_question"] = clarify_question
            if error is not None:
                values["error"] = error
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

    async def list_recent(self, query: str | None = None) -> list[SessionRecord]:
        """Pinned sessions first, then most recently started; `query` filters by title
        (case-insensitive substring) for the sidebar's search box."""
        async with self._session_factory() as session:
            stmt = select(SessionTable).order_by(
                SessionTable.pinned.desc(), SessionTable.created_at.desc()
            )
            if query:
                stmt = stmt.where(SessionTable.title.ilike(f"%{query}%"))
            result = await session.execute(stmt)
            return [_to_record(row) for row in result.scalars().all()]

    async def rename(self, thread_id: str, title: str) -> SessionRecord | None:
        async with self._session_factory() as session:
            result = await session.execute(
                update(SessionTable)
                .where(SessionTable.thread_id == thread_id)
                .values(title=title, updated_at=func.now())
                .returning(SessionTable)
            )
            row = result.scalar_one_or_none()
            await session.commit()
            return _to_record(row) if row is not None else None

    async def set_pinned(self, thread_id: str, pinned: bool) -> SessionRecord | None:
        async with self._session_factory() as session:
            result = await session.execute(
                update(SessionTable)
                .where(SessionTable.thread_id == thread_id)
                .values(pinned=pinned, updated_at=func.now())
                .returning(SessionTable)
            )
            row = result.scalar_one_or_none()
            await session.commit()
            return _to_record(row) if row is not None else None

    async def delete(self, thread_id: str) -> DeleteResult:
        """Remove a session row, refusing while a turn is still in flight (`queued`/`running`).
        The status check and the delete happen in one statement, so a concurrent worker
        `set_status` call can't race it into deleting a row it just decided was safe to remove."""
        async with self._session_factory() as session:
            result = await session.execute(
                delete(SessionTable)
                .where(
                    SessionTable.thread_id == thread_id,
                    SessionTable.status.not_in(_IN_FLIGHT_STATUSES),
                )
                .returning(SessionTable.thread_id)
            )
            if result.scalar_one_or_none() is not None:
                await session.commit()
                return "deleted"
            existing = await session.get(SessionTable, thread_id)
            await session.commit()
            return "in_progress" if existing is not None else "not_found"
