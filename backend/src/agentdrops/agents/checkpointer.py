"""Postgres-backed LangGraph checkpointer, shared by the API (read-only `aget_state` calls) and
the Celery worker (the only process that calls `astream`), so both see the same graph state.

`settings.database_url` is the SQLAlchemy-style `postgresql+asyncpg://` DSN `db/engine.py` uses
for the session-store engine — `langgraph-checkpoint-postgres` uses `psycopg` (v3) directly, which
expects the plain `postgresql://` form, so the dialect prefix is stripped here rather than by
changing the shared setting itself.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agentdrops.config import Settings

_ASYNCPG_DIALECT_PREFIX = "postgresql+asyncpg://"


def strip_asyncpg_dialect(database_url: str) -> str:
    if database_url.startswith(_ASYNCPG_DIALECT_PREFIX):
        return "postgresql://" + database_url[len(_ASYNCPG_DIALECT_PREFIX) :]
    return database_url


@asynccontextmanager
async def checkpointer(settings: Settings) -> AsyncIterator[BaseCheckpointSaver[Any]]:
    dsn = strip_asyncpg_dialect(settings.database_url)
    async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
        await saver.setup()
        yield saver
