"""Shared async SQLAlchemy engine + session factory, built once in the FastAPI lifespan.

`DATABASE_URL` is already the SQLAlchemy-style `postgresql+asyncpg://` DSN (`.env.example`), so
it's passed to `create_async_engine` unmodified — asyncpg is used only as the dialect driver,
never imported directly by app code. Repository classes (`agentdrops.repository`) take the
session factory and open one `AsyncSession` per call, never a bare engine or connection held
across requests.
"""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from agentdrops.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    # pool_pre_ping: cheap `SELECT 1` before handing out a pooled connection, so a connection
    # dropped by the server/a proxy while idle in the pool surfaces as a transparent reconnect
    # instead of an `OperationalError` on the next request that happens to draw it.
    return create_async_engine(
        settings.database_url, pool_size=10, max_overflow=0, pool_pre_ping=True
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
