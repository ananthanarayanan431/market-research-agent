"""Shared fixture for repository integration tests: a real SQLAlchemy async session factory
against the docker-compose Postgres, auto-skipped when that Postgres isn't reachable."""

from collections.abc import AsyncIterator

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentdrops.db.engine import create_engine, create_session_factory
from tests.unit.agents.conftest import make_settings


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """`asyncpg.PostgresError` (not just `OSError`) covers a wrong-but-reachable Postgres too —
    e.g. the docker-compose `agentdrops` role missing from whatever server is actually listening
    on 5432 — which should skip these integration tests the same as a refused connection."""
    settings = make_settings(
        database_url="postgresql+asyncpg://agentdrops:agentdrops@localhost:5432/agentdrops"
    )
    engine = create_engine(settings)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE sessions, audit_log RESTART IDENTITY CASCADE"))
    except (OSError, asyncpg.PostgresError) as exc:
        await engine.dispose()
        pytest.skip(f"Postgres not reachable at {settings.database_url}: {exc}")
    yield create_session_factory(engine)
    await engine.dispose()
