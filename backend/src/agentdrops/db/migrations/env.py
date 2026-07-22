# backend/src/agentdrops/db/migrations/env.py
"""Alembic environment: derives its DB URL from `Settings`/`DATABASE_URL`, not `alembic.ini`,
so there is one source of truth for the connection string. Migrations run synchronously via
SQLAlchemy + psycopg2 — the only place either is imported; app code always talks to Postgres
through asyncpg (`agentdrops.db.pool`)."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from agentdrops.config import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _sync_dsn() -> str:
    """SQLAlchemy's default driver for a bare `postgresql://` URL is psycopg2."""
    return get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_dsn(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _sync_dsn()
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
