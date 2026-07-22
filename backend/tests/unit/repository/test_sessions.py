"""Integration tests for `SessionStore` against a real Postgres — see conftest.py for the
auto-skip-if-unreachable `pool` fixture."""

import asyncpg

from agentdrops.repository.sessions import SessionStore


async def test_touch_creates_a_session_once(pool: asyncpg.Pool) -> None:
    store = SessionStore(pool)
    first = await store.touch("t1", title="EV charging in the EU")
    second = await store.touch("t1", title="ignored on the second call")

    assert first.thread_id == second.thread_id == "t1"
    assert first.title == "EV charging in the EU"
    assert second.title == "EV charging in the EU"
    assert first.status == "clarifying"


async def test_set_status_updates_status_and_optional_report(pool: asyncpg.Pool) -> None:
    store = SessionStore(pool)
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


async def test_add_source_appends_to_sources(pool: asyncpg.Pool) -> None:
    store = SessionStore(pool)
    await store.touch("t3", title="EV charging in the EU")

    await store.add_source("t3", "EU", "EU findings")
    await store.add_source("t3", "US", "US findings")

    session = await store.get("t3")
    assert session is not None
    assert session.sources == [
        {"topic": "EU", "summary": "EU findings"},
        {"topic": "US", "summary": "US findings"},
    ]


async def test_get_returns_none_for_unknown_thread(pool: asyncpg.Pool) -> None:
    assert await SessionStore(pool).get("does-not-exist") is None


async def test_list_recent_orders_most_recent_first(pool: asyncpg.Pool) -> None:
    store = SessionStore(pool)
    await store.touch("older", title="First")
    await store.touch("newer", title="Second")

    recent = await store.list_recent()

    assert [s.thread_id for s in recent] == ["newer", "older"]
