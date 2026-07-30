"""Integration tests for `AuditLog` against a real Postgres — see conftest.py for the
auto-skip-if-unreachable `session_factory` fixture."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentdrops.db.models import AuditLogTable
from agentdrops.repository.audit import AuditLog
from agentdrops.repository.sessions import SessionStore


async def test_record_inserts_one_row_per_call(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await SessionStore(session_factory).touch("t1", title="EV charging in the EU")
    audit = AuditLog(session_factory)

    await audit.record("t1", operation="chat", status="done", detail={"report_chars": 1200})

    async with session_factory() as session:
        rows = (
            (await session.execute(select(AuditLogTable).where(AuditLogTable.thread_id == "t1")))
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].operation == "chat"
    assert rows[0].status == "done"
    assert rows[0].detail == {"report_chars": 1200}


async def test_record_defaults_detail_to_empty_object(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await SessionStore(session_factory).touch("t2", title="EV charging in the EU")
    audit = AuditLog(session_factory)

    await audit.record("t2", operation="chat_stream", status="clarify")

    async with session_factory() as session:
        row = (
            await session.execute(select(AuditLogTable).where(AuditLogTable.thread_id == "t2"))
        ).scalar_one()
    assert row.detail == {}
