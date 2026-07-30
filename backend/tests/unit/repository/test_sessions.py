"""Integration tests for `SessionStore` against a real Postgres — see conftest.py for the
auto-skip-if-unreachable `session_factory` fixture."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentdrops.db.models import AuditLogTable
from agentdrops.repository.audit import AuditLog
from agentdrops.repository.sessions import SessionStore


async def test_touch_creates_a_session_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SessionStore(session_factory)
    first = await store.touch("t1", title="EV charging in the EU")
    second = await store.touch("t1", title="ignored on the second call")

    assert first.thread_id == second.thread_id == "t1"
    assert first.title == "EV charging in the EU"
    assert second.title == "EV charging in the EU"
    assert first.status == "queued"


async def test_touch_defaults_to_queued(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SessionStore(session_factory)
    session = await store.touch("t-queued", title="EV charging in the EU")

    assert session.status == "queued"


async def test_set_status_updates_status_and_optional_report(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SessionStore(session_factory)
    await store.touch("t2", title="EV charging in the EU")

    await store.set_status("t2", "running")
    running = await store.get("t2")
    assert running is not None
    assert running.status == "running"
    assert running.report is None

    await store.set_status("t2", "done", report="# Report")
    done = await store.get("t2")
    assert done is not None
    assert done.status == "done"
    assert done.report == "# Report"


async def test_set_status_stores_clarify_question_suggestions_and_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SessionStore(session_factory)
    await store.touch("t4", title="EV charging in the EU")

    await store.set_status(
        "t4",
        "clarifying",
        clarify_question="Which region?",
        clarify_suggestions=["North America", "Global"],
    )
    clarifying = await store.get("t4")
    assert clarifying is not None
    assert clarifying.clarify_question == "Which region?"
    assert clarifying.clarify_suggestions == ["North America", "Global"]

    await store.set_status("t4", "failed", error="LLM provider unavailable")
    failed = await store.get("t4")
    assert failed is not None
    assert failed.error == "LLM provider unavailable"


async def test_add_source_appends_to_sources(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SessionStore(session_factory)
    await store.touch("t3", title="EV charging in the EU")

    await store.add_source("t3", "EU", "EU findings")
    await store.add_source("t3", "US", "US findings")

    session = await store.get("t3")
    assert session is not None
    assert session.sources == [
        {"topic": "EU", "summary": "EU findings"},
        {"topic": "US", "summary": "US findings"},
    ]


async def test_get_returns_none_for_unknown_thread(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assert await SessionStore(session_factory).get("does-not-exist") is None


async def test_list_recent_orders_most_recent_first(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SessionStore(session_factory)
    await store.touch("older", title="First")
    await store.touch("newer", title="Second")

    recent = await store.list_recent()

    assert [s.thread_id for s in recent] == ["newer", "older"]


async def test_list_recent_filters_by_title_query(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SessionStore(session_factory)
    await store.touch("t-ev", title="EV charging in the EU")
    await store.touch("t-fintech", title="Fintech market in the US")

    recent = await store.list_recent(query="fintech")

    assert [s.thread_id for s in recent] == ["t-fintech"]


async def test_list_recent_treats_literal_percent_in_query_as_literal(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SessionStore(session_factory)
    await store.touch("t-percent", title="Q3 growth is up 50% YoY")
    # Same "50" substring, no literal "%" — an unescaped search would treat the query's own "%"
    # as a wildcard and match this too; escaping should exclude it.
    await store.touch("t-no-percent", title="Q3 growth is up 50X YoY")

    recent = await store.list_recent(query="50%")

    assert [s.thread_id for s in recent] == ["t-percent"]


async def test_list_recent_treats_literal_underscore_in_query_as_literal(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SessionStore(session_factory)
    await store.touch("t-underscore", title="internal_codename project")
    await store.touch("t-other", title="internalXcodename project")

    recent = await store.list_recent(query="internal_codename")

    assert [s.thread_id for s in recent] == ["t-underscore"]


async def test_list_recent_puts_pinned_sessions_first(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SessionStore(session_factory)
    await store.touch("older", title="First")
    await store.touch("newer", title="Second")
    await store.set_pinned("older", True)

    recent = await store.list_recent()

    assert [s.thread_id for s in recent] == ["older", "newer"]


async def test_rename_updates_title(session_factory: async_sessionmaker[AsyncSession]) -> None:
    store = SessionStore(session_factory)
    await store.touch("t-rename", title="Original title")

    renamed = await store.rename("t-rename", "New title")

    assert renamed is not None
    assert renamed.title == "New title"
    assert (await store.get("t-rename")).title == "New title"  # type: ignore[union-attr]


async def test_rename_returns_none_for_unknown_thread(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assert await SessionStore(session_factory).rename("does-not-exist", "New title") is None


async def test_set_pinned_toggles_pinned_flag(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SessionStore(session_factory)
    await store.touch("t-pin", title="EV charging in the EU")

    pinned = await store.set_pinned("t-pin", True)
    assert pinned is not None
    assert pinned.pinned is True

    unpinned = await store.set_pinned("t-pin", False)
    assert unpinned is not None
    assert unpinned.pinned is False


async def test_delete_removes_session_and_reports_it_existed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SessionStore(session_factory)
    await store.touch("t-delete", title="EV charging in the EU")
    await store.set_status("t-delete", "clarifying")

    assert await store.delete("t-delete") == "deleted"
    assert await store.get("t-delete") is None


async def test_delete_returns_not_found_for_unknown_thread(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assert await SessionStore(session_factory).delete("does-not-exist") == "not_found"


async def test_delete_refuses_a_queued_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SessionStore(session_factory)
    await store.touch("t-queued-delete", title="EV charging in the EU")
    await store.set_status("t-queued-delete", "queued")

    assert await store.delete("t-queued-delete") == "in_progress"
    assert await store.get("t-queued-delete") is not None


async def test_delete_refuses_a_running_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SessionStore(session_factory)
    await store.touch("t-running-delete", title="EV charging in the EU")
    await store.set_status("t-running-delete", "running")

    assert await store.delete("t-running-delete") == "in_progress"
    assert await store.get("t-running-delete") is not None


async def test_delete_cascades_to_the_session_s_audit_log_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`audit_log.thread_id` has `ondelete="CASCADE"` (see `db/models/audit_log.py`) specifically
    so deleting a session doesn't leave orphaned audit rows behind, or fail with a foreign-key
    violation because deletion is blocked by rows that reference it. This is the retention policy:
    a deleted session's audit trail is deleted with it, not retained independently."""
    store = SessionStore(session_factory)
    audit = AuditLog(session_factory)
    await store.touch("t-delete-audit", title="EV charging in the EU")
    await store.set_status("t-delete-audit", "done", report="# Report")
    await audit.record("t-delete-audit", operation="chat", status="done")

    async with session_factory() as session:
        rows_before = (
            (
                await session.execute(
                    select(AuditLogTable).where(AuditLogTable.thread_id == "t-delete-audit")
                )
            )
            .scalars()
            .all()
        )
        assert len(rows_before) == 1

    assert await store.delete("t-delete-audit") == "deleted"

    async with session_factory() as session:
        rows_after = (
            (
                await session.execute(
                    select(AuditLogTable).where(AuditLogTable.thread_id == "t-delete-audit")
                )
            )
            .scalars()
            .all()
        )
        assert rows_after == []
