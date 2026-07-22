"""Postgres-backed session registry: title/status/report/sources per thread.

Backs the sidebar listing and the reopen-a-completed-run endpoints. Persisted in the `sessions`
table (`db/migrations/versions/0001_create_sessions_and_audit_log.py`), so state survives a
process restart — unlike the compiled graph's `InMemorySaver` checkpointer, which this change
does not touch.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

import asyncpg

Status = Literal["clarifying", "running", "done", "failed"]

_COLUMNS = "thread_id, title, status, report, sources, created_at"


@dataclass
class SessionRecord:
    """One research thread's session-level metadata, as opposed to the graph's own state."""

    thread_id: str
    title: str
    created_at: datetime
    status: Status = "clarifying"
    report: str | None = None
    sources: list[dict[str, str]] = field(default_factory=list)


def _row_to_record(row: asyncpg.Record) -> SessionRecord:
    return SessionRecord(
        thread_id=row["thread_id"],
        title=row["title"],
        created_at=row["created_at"],
        status=row["status"],
        report=row["report"],
        sources=row["sources"],
    )


class SessionStore:
    """Tracks one `SessionRecord` per thread_id in Postgres, via a shared connection pool."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def touch(self, thread_id: str, *, title: str) -> SessionRecord:
        """Create a session record the first time a thread is seen; a no-op afterward."""
        row = await self._pool.fetchrow(
            f"""
            INSERT INTO sessions (thread_id, title)
            VALUES ($1, $2)
            ON CONFLICT (thread_id) DO NOTHING
            RETURNING {_COLUMNS}
            """,
            thread_id,
            title,
        )
        if row is None:
            row = await self._pool.fetchrow(
                f"SELECT {_COLUMNS} FROM sessions WHERE thread_id = $1", thread_id
            )
        assert row is not None
        return _row_to_record(row)

    async def set_status(
        self, thread_id: str, status: Status, *, report: str | None = None
    ) -> None:
        await self._pool.execute(
            "UPDATE sessions SET status = $2, report = COALESCE($3, report), "
            "updated_at = now() WHERE thread_id = $1",
            thread_id,
            status,
            report,
        )

    async def add_source(self, thread_id: str, topic: str, summary: str) -> None:
        await self._pool.execute(
            "UPDATE sessions SET sources = sources || $2::jsonb, updated_at = now() "
            "WHERE thread_id = $1",
            thread_id,
            [{"topic": topic, "summary": summary}],
        )

    async def get(self, thread_id: str) -> SessionRecord | None:
        row = await self._pool.fetchrow(
            f"SELECT {_COLUMNS} FROM sessions WHERE thread_id = $1", thread_id
        )
        return _row_to_record(row) if row is not None else None

    async def list_recent(self) -> list[SessionRecord]:
        rows = await self._pool.fetch(f"SELECT {_COLUMNS} FROM sessions ORDER BY created_at DESC")
        return [_row_to_record(row) for row in rows]
