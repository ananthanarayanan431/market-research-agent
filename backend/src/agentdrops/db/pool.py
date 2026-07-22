"""Shared asyncpg connection pool, built once in the FastAPI lifespan (see `agentdrops/main.py`).

A `jsonb` type codec is registered on every pooled connection so `sessions.sources` and
`audit_log.detail` round-trip as native Python lists/dicts instead of raw JSON strings — the
repository layer (`agentdrops.repository`) never calls `json.dumps`/`json.loads` itself.
"""

import json

import asyncpg

from agentdrops.config import Settings


def _asyncpg_dsn(database_url: str) -> str:
    """`DATABASE_URL` uses the SQLAlchemy-style `+asyncpg` driver marker; asyncpg's own DSN
    parser expects plain `postgresql://`."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://")


async def _init_connection(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog", format="text"
    )


async def create_pool(settings: Settings) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn=_asyncpg_dsn(settings.database_url), min_size=2, max_size=10, init=_init_connection
    )
