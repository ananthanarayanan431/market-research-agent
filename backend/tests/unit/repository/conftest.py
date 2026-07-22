"""Shared fixture for repository integration tests: a real asyncpg pool against the
docker-compose Postgres, auto-skipped when that Postgres isn't reachable."""

from collections.abc import AsyncIterator

import asyncpg
import pytest

from agentdrops.db.pool import create_pool
from tests.unit.agents.conftest import make_settings


@pytest.fixture
async def pool() -> AsyncIterator[asyncpg.Pool]:
    settings = make_settings(
        database_url="postgresql+asyncpg://agentdrops:agentdrops@localhost:5432/agentdrops"
    )
    try:
        db_pool = await create_pool(settings)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Postgres not reachable at {settings.database_url}: {exc}")
    async with db_pool.acquire() as conn:
        await conn.execute("TRUNCATE sessions, audit_log RESTART IDENTITY CASCADE")
    yield db_pool
    await db_pool.close()
