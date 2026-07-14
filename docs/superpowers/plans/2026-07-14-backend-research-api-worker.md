# Backend: Storage, Research Graph, API, Worker, Exports — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the Deep Research Market Agent backend so the real API contract in `docs/ui-builder-system-prompt.md` §4 is backed by working code — Postgres persistence, a LangGraph multi-agent research pipeline (brief → parallel research → compress → report → idea one-pager), an arq worker, SSE progress streaming, and PDF/Excel export — matching the architecture in `docs/superpowers/specs/2026-07-12-deepresearch-market-agent-design.md`.

**Architecture:** FastAPI (stateless API) enqueues arq jobs on Redis; an arq worker runs a LangGraph `StateGraph` per run, persisting audit-log events and results to Postgres and publishing live progress to a Redis pub/sub channel that the API relays to clients over SSE. Exports render report+one-pager to PDF (WeasyPrint) / XLSX (openpyxl) and land in MinIO.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async) + asyncpg + Alembic, arq + redis-py, LangGraph, `anthropic` SDK directly (no langchain model wrapper — matches the existing `resilience/llm_retry.py` built for raw Anthropic calls), WeasyPrint, openpyxl, MinIO client. Existing `webtools/*` and `resilience/*` modules are reused unchanged.

## Global Constraints

- Python 3.12+, fully typed, `mypy --strict` must pass (`backend/pyproject.toml` `[tool.mypy]`) — no untyped defs in application code.
- `ruff` lint + format must pass (`backend/pyproject.toml` `[tool.ruff]`, line-length 100).
- Pydantic v2 for every I/O boundary (API schemas, config, structured LLM outputs).
- All external HTTP/LLM calls wrapped with the existing `resilience/http_retry.py` (`HTTP_RETRY`) / `resilience/llm_retry.py` (`LLM_RETRY`) decorators — never call `httpx`/`anthropic` un-retried.
- Repository pattern for all Postgres access — graph/worker/API code depends on repository interfaces, never raw SQL inline in routes or nodes.
- Alembic migrations only — no hand-edited schema, no `create_all` outside tests.
- Secrets only via `agentdrops.config.Settings` (`pydantic-settings`, env-sourced) — never hardcoded.
- Tests: `pytest` with `asyncio_mode = auto` (already configured); integration/repository tests use `testcontainers` against a real Postgres container (Docker is available in this environment — confirmed via `docker compose version`).
- Match the API contract in `docs/ui-builder-system-prompt.md` §4 exactly (field names, enum values, event shape) — the frontend plan will be written against this contract verbatim.
- Every module goes in the package layout already fixed by the design spec (`storage/`, `research/`, `idearefine/`, `exports/`, `worker/`, `api/`) under `backend/src/agentdrops/`.
- Frequent commits: one commit per task (or per logical step group within a task), following the existing commit style (`feat(backend): ...`, `refactor(backend): ...`) visible in `git log`.
- Before running any test in Tasks 2+, copy `.env.example` to `backend/.env` and fill in real API keys (`ANTHROPIC_API_KEY`, `EXA_API_KEY`, `TAVILY_API_KEY`, `NEWSAPI_KEY`, `REDDIT_CLIENT_ID`/`SECRET`) — `Settings` requires all of them even for tests that don't exercise those integrations, since Pydantic validates the whole model on construction.

---

### Task 1: Dependencies, settings, and local infra

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/src/agentdrops/config.py`
- Modify: `backend/tests/unit/test_config.py`
- Create: `docker-compose.yml` (repo root)
- Create: `backend/Dockerfile`
- Create: `.env.example` (repo root)

**Interfaces:**
- Produces: `Settings` fields `max_concurrent_research_units: int`, `max_researcher_iterations: int`, `max_react_tool_calls: int` (all with defaults, used by Tasks 9/8), and existing `database_url`/`redis_url`/`minio_*` fields (already present) now backed by real running services via `docker-compose.yml`.

- [ ] **Step 1: Add backend dependencies**

Edit `backend/pyproject.toml` `[project] dependencies` list to add (keep existing entries):

```toml
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "sqlalchemy[asyncio]>=2.0.30",
    "asyncpg>=0.29",
    "alembic>=1.13",
    "arq>=0.26",
    "redis>=5.0",
    "langgraph>=0.2.60",
    "minio>=7.2",
    "weasyprint>=62",
    "openpyxl>=3.1",
    "sse-starlette>=2.1",
```

And to `[project.optional-dependencies] dev`, add:

```toml
    "testcontainers[postgres,redis]>=4.7",
```

- [ ] **Step 2: Install and lock**

Run: `cd backend && uv sync --all-extras`
Expected: resolves and installs without conflicts (exit code 0).

- [ ] **Step 3: Add new settings fields**

In `backend/src/agentdrops/config.py`, add three fields to `Settings` (after `reddit_user_agent`, before `database_url`):

```python
    max_concurrent_research_units: int = 3
    max_researcher_iterations: int = 3
    max_react_tool_calls: int = 8
```

- [ ] **Step 4: Extend the settings test**

In `backend/tests/unit/test_config.py`, add assertions to `test_settings_loads_required_fields_from_env` after the existing `reddit_user_agent` assertion:

```python
    assert settings.max_concurrent_research_units == 3
    assert settings.max_researcher_iterations == 3
    assert settings.max_react_tool_calls == 8
```

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_config.py -v`
Expected: both tests PASS.

- [ ] **Step 6: Write docker-compose.yml**

Create `docker-compose.yml` at the repo root:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: agentdrops
      POSTGRES_PASSWORD: agentdrops
      POSTGRES_DB: agentdrops
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U agentdrops"]
      interval: 5s
      timeout: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 10

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports: ["9000:9000", "9001:9001"]
    volumes: ["miniodata:/data"]
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 5s
      timeout: 5s
      retries: 10

  backend:
    build: ./backend
    command: uvicorn agentdrops.api.app:create_app --factory --host 0.0.0.0 --port 8000
    env_file: .env
    ports: ["8000:8000"]
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
      minio: { condition: service_healthy }

  worker:
    build: ./backend
    command: arq agentdrops.worker.main.WorkerSettings
    env_file: .env
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
      minio: { condition: service_healthy }

volumes:
  pgdata:
  miniodata:
```

- [ ] **Step 7: Write backend Dockerfile**

Create `backend/Dockerfile`:

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev

COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic

ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "agentdrops.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 8: Write .env.example**

Create `.env.example` at the repo root:

```bash
ANTHROPIC_API_KEY=
EXA_API_KEY=
TAVILY_API_KEY=
NEWSAPI_KEY=
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=

DATABASE_URL=postgresql+asyncpg://agentdrops:agentdrops@localhost:5432/agentdrops
REDIS_URL=redis://localhost:6379/0
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
```

- [ ] **Step 9: Bring up infra and verify**

Run: `docker compose up -d postgres redis minio && docker compose ps`
Expected: all three services show `healthy`.

- [ ] **Step 10: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/src/agentdrops/config.py backend/tests/unit/test_config.py docker-compose.yml backend/Dockerfile .env.example
git commit -m "feat(backend): add infra deps, settings, and docker-compose for postgres/redis/minio"
```

---

### Task 2: Postgres models and Alembic migration

**Files:**
- Create: `backend/src/agentdrops/storage/__init__.py`
- Create: `backend/src/agentdrops/storage/postgres/__init__.py`
- Create: `backend/src/agentdrops/storage/postgres/models.py`
- Create: `backend/src/agentdrops/storage/postgres/session.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/0001_initial.py`
- Test: `backend/tests/integration/__init__.py`, `backend/tests/integration/storage/__init__.py`, `backend/tests/integration/storage/test_migration.py`

**Interfaces:**
- Produces: `Base` (declarative base), `RunModel`, `RunEventModel`, `SourceModel`, `ExportModel` (SQLAlchemy 2.0 mapped classes); `create_engine(database_url: str) -> AsyncEngine`, `create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]`, `session_scope(factory) -> AsyncIterator[AsyncSession]` (async context manager, commits on success / rolls back on exception) — all consumed by Task 3's repositories.

- [ ] **Step 1: Write the failing migration test**

Create `backend/tests/integration/__init__.py` and `backend/tests/integration/storage/__init__.py` (both empty).

Create `backend/tests/integration/storage/test_migration.py`:

```python
import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer

from agentdrops.storage.postgres.models import RunModel


@pytest.fixture(scope="module")
def postgres_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as pg:
        sync_url = pg.get_connection_url()
        yield sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")


@pytest.fixture(scope="module")
def migrated_url(postgres_url: str) -> str:
    cfg = Config(str(__file__).rsplit("/backend/", 1)[0] + "/backend/alembic.ini")
    cfg.set_main_option("script_location", str(__file__).rsplit("/tests/", 1)[0] + "/alembic")
    cfg.set_main_option("sqlalchemy.url", postgres_url.replace("+asyncpg", "+psycopg2"))
    command.upgrade(cfg, "head")
    return postgres_url


async def test_alembic_migration_creates_runs_table(migrated_url: str) -> None:
    engine = create_async_engine(migrated_url)
    async with engine.connect() as conn:
        result = await conn.execute(select(RunModel.__table__).limit(0))
        assert result.keys() is not None
    await engine.dispose()


async def test_run_model_round_trips(migrated_url: str) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = create_async_engine(migrated_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = uuid.uuid4()
    async with factory() as session:
        session.add(RunModel(id=run_id, topic="AI note-taking apps", status="queued"))
        await session.commit()
    async with factory() as session:
        fetched = await session.get(RunModel, run_id)
        assert fetched is not None
        assert fetched.topic == "AI note-taking apps"
        assert fetched.status == "queued"
    await engine.dispose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/integration/storage/test_migration.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdrops.storage'` (nothing exists yet).

- [ ] **Step 3: Write the SQLAlchemy models**

Create `backend/src/agentdrops/storage/__init__.py` (empty) and `backend/src/agentdrops/storage/postgres/__init__.py` (empty).

Create `backend/src/agentdrops/storage/postgres/models.py`:

```python
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class RunModel(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic: Mapped[str] = mapped_column(String(500))
    constraints: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    research_brief: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_report: Mapped[str | None] = mapped_column(Text, nullable=True)
    idea_onepager: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    events: Mapped[list["RunEventModel"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    sources: Mapped[list["SourceModel"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    exports: Mapped[list["ExportModel"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class RunEventModel(Base):
    __tablename__ = "run_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    node_name: Mapped[str] = mapped_column(String(50))
    event_type: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    run: Mapped["RunModel"] = relationship(back_populates="events")


class SourceModel(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    tool_name: Mapped[str] = mapped_column(String(20))
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    snippet: Mapped[str] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(server_default=func.now())

    run: Mapped["RunModel"] = relationship(back_populates="sources")


class ExportModel(Base):
    __tablename__ = "exports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    format: Mapped[str] = mapped_column(String(10))
    minio_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="generating")
    generated_at: Mapped[datetime | None] = mapped_column(nullable=True)

    run: Mapped["RunModel"] = relationship(back_populates="exports")
```

- [ ] **Step 4: Write the session helper**

Create `backend/src/agentdrops/storage/postgres/session.py`:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

- [ ] **Step 5: Write Alembic scaffolding**

Create `backend/alembic.ini`:

```ini
[alembic]
script_location = alembic
sqlalchemy.url =

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

Create `backend/alembic/script.py.mako`:

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

Create `backend/alembic/env.py`:

```python
import asyncio
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from agentdrops.config import get_settings
from agentdrops.storage.postgres.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    configured = config.get_main_option("sqlalchemy.url")
    return configured if configured else get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    url = get_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
    connectable = create_async_engine(url)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

Note: `do_run_migrations`'s `Any` import is unused if typed with `Connection` — remove the `Any` import (only `Connection` is used).

Create `backend/alembic/versions/0001_initial.py`:

```python
"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("topic", sa.String(500), nullable=False),
        sa.Column("constraints", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("research_brief", sa.Text(), nullable=True),
        sa.Column("final_report", sa.Text(), nullable=True),
        sa.Column("idea_onepager", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "run_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_name", sa.String(50), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_run_events_run_id", "run_events", ["run_id"])
    op.create_table(
        "sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.String(20), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_sources_run_id", "sources", ["run_id"])
    op.create_table(
        "exports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("format", sa.String(10), nullable=False),
        sa.Column("minio_key", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="generating"),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_exports_run_id", "exports", ["run_id"])


def downgrade() -> None:
    op.drop_table("exports")
    op.drop_table("sources")
    op.drop_table("run_events")
    op.drop_table("runs")
```

- [ ] **Step 6: Fix the test's path resolution**

The fixture in Step 1 builds paths with brittle `.rsplit` calls. Replace `migrated_url` in `test_migration.py` with a version anchored on the file's own location:

```python
import pathlib

_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def migrated_url(postgres_url: str) -> str:
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", postgres_url.replace("+asyncpg", "+psycopg2"))
    command.upgrade(cfg, "head")
    return postgres_url
```

(`parents[3]` from `backend/tests/integration/storage/test_migration.py` resolves to `backend/`.)

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/integration/storage/test_migration.py -v`
Expected: both tests PASS (Docker pulls `postgres:16-alpine` on first run — allow extra time).

- [ ] **Step 8: Run mypy and ruff**

Run: `cd backend && uv run mypy src/agentdrops/storage && uv run ruff check src/agentdrops/storage alembic`
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add backend/src/agentdrops/storage backend/alembic.ini backend/alembic backend/tests/integration
git commit -m "feat(backend): add Postgres models and initial Alembic migration"
```

---

### Task 3: Repository layer

**Files:**
- Create: `backend/src/agentdrops/storage/postgres/repositories/__init__.py`
- Create: `backend/src/agentdrops/storage/postgres/repositories/runs.py`
- Create: `backend/src/agentdrops/storage/postgres/repositories/events.py`
- Create: `backend/src/agentdrops/storage/postgres/repositories/sources.py`
- Create: `backend/src/agentdrops/storage/postgres/repositories/exports.py`
- Test: `backend/tests/integration/storage/conftest.py`
- Test: `backend/tests/integration/storage/test_repositories.py`

**Interfaces:**
- Consumes: `Base`, `RunModel`, `RunEventModel`, `SourceModel`, `ExportModel` from Task 2's `storage/postgres/models.py`; `create_engine`, `create_session_factory`, `session_scope` from Task 2's `storage/postgres/session.py`.
- Produces (consumed by Task 4's API routes, Task 14's worker, Task 15's SSE route, Task 16's export routes):
  - `RunsRepository(session_factory)`: `async def create(topic: str, constraints: str | None) -> RunModel`, `async def get(run_id: uuid.UUID) -> RunModel | None`, `async def list_page(limit: int, offset: int) -> tuple[list[RunModel], int]`, `async def update_status(run_id: uuid.UUID, status: str, *, error: str | None = None) -> None`, `async def save_research_output(run_id: uuid.UUID, *, research_brief: str | None = None, final_report: str | None = None, idea_onepager: dict[str, Any] | None = None) -> None`.
  - `EventsRepository(session_factory)`: `async def append(run_id: uuid.UUID, node_name: str, event_type: str, message: str, payload: dict[str, Any] | None = None) -> RunEventModel`, `async def list_for_run(run_id: uuid.UUID) -> list[RunEventModel]`.
  - `SourcesRepository(session_factory)`: `async def add_many(run_id: uuid.UUID, sources: list[dict[str, Any]]) -> None`, `async def list_for_run(run_id: uuid.UUID) -> list[SourceModel]`.
  - `ExportsRepository(session_factory)`: `async def create(run_id: uuid.UUID, format: str) -> ExportModel`, `async def get(run_id: uuid.UUID, format: str) -> ExportModel | None`, `async def mark_ready(export_id: uuid.UUID, minio_key: str) -> None`, `async def mark_failed(export_id: uuid.UUID) -> None`.

- [ ] **Step 1: Write the failing repository tests**

Create `backend/tests/integration/storage/conftest.py`:

```python
from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer

from agentdrops.storage.postgres.session import create_engine, create_session_factory

_BACKEND_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def postgres_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as pg:
        sync_url = pg.get_connection_url()
        async_url = sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
        cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
        cfg.set_main_option("sqlalchemy.url", sync_url)
        command.upgrade(cfg, "head")
        yield async_url


@pytest.fixture
async def session_factory(postgres_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(postgres_url)
    yield create_session_factory(engine)
    await engine.dispose()
```

Note: `backend/tests/integration/storage/test_migration.py` from Task 2 duplicates the container+migration setup inline; leave it as-is (it's a standalone migration-focused test) — this `conftest.py` is scoped to `test_repositories.py` and any future repository tests in this directory.

Create `backend/tests/integration/storage/test_repositories.py`:

```python
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentdrops.storage.postgres.repositories.events import EventsRepository
from agentdrops.storage.postgres.repositories.exports import ExportsRepository
from agentdrops.storage.postgres.repositories.runs import RunsRepository
from agentdrops.storage.postgres.repositories.sources import SourcesRepository


async def test_runs_repository_create_and_get(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repo = RunsRepository(session_factory)
    run = await repo.create(topic="AI note-taking apps", constraints="US market only")
    assert run.status == "queued"

    fetched = await repo.get(run.id)
    assert fetched is not None
    assert fetched.topic == "AI note-taking apps"
    assert fetched.constraints == "US market only"


async def test_runs_repository_get_missing_returns_none(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    import uuid

    repo = RunsRepository(session_factory)
    assert await repo.get(uuid.uuid4()) is None


async def test_runs_repository_update_status_and_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repo = RunsRepository(session_factory)
    run = await repo.create(topic="topic", constraints=None)

    await repo.update_status(run.id, "failed", error="boom")

    fetched = await repo.get(run.id)
    assert fetched is not None
    assert fetched.status == "failed"
    assert fetched.error == "boom"


async def test_runs_repository_save_research_output(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repo = RunsRepository(session_factory)
    run = await repo.create(topic="topic", constraints=None)

    await repo.save_research_output(
        run.id,
        research_brief="brief text",
        final_report="# Report",
        idea_onepager={"problem_statement": "p", "recommended_direction": "d",
                       "key_assumptions": [], "mvp_scope": [], "not_doing": [],
                       "open_questions": []},
    )

    fetched = await repo.get(run.id)
    assert fetched is not None
    assert fetched.research_brief == "brief text"
    assert fetched.final_report == "# Report"
    assert fetched.idea_onepager is not None
    assert fetched.idea_onepager["recommended_direction"] == "d"


async def test_runs_repository_list_page_orders_newest_first(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repo = RunsRepository(session_factory)
    first = await repo.create(topic="first", constraints=None)
    second = await repo.create(topic="second", constraints=None)

    runs, total = await repo.list_page(limit=10, offset=0)

    ids = [r.id for r in runs]
    assert ids.index(second.id) < ids.index(first.id)
    assert total >= 2


async def test_events_repository_append_and_list(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    runs_repo = RunsRepository(session_factory)
    events_repo = EventsRepository(session_factory)
    run = await runs_repo.create(topic="topic", constraints=None)

    await events_repo.append(run.id, "supervisor", "started", "Starting research")
    await events_repo.append(
        run.id, "researcher", "tool_call", "Searching Reddit",
        payload={"tool": "reddit_search", "sub_topic": "retention"},
    )

    events = await events_repo.list_for_run(run.id)
    assert len(events) == 2
    assert events[0].node_name == "supervisor"
    assert events[1].payload == {"tool": "reddit_search", "sub_topic": "retention"}


async def test_sources_repository_add_many_and_list(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    runs_repo = RunsRepository(session_factory)
    sources_repo = SourcesRepository(session_factory)
    run = await runs_repo.create(topic="topic", constraints=None)

    await sources_repo.add_many(
        run.id,
        [
            {"tool_name": "exa", "url": "https://a.com", "title": "A", "snippet": "a"},
            {"tool_name": "reddit", "url": "https://b.com", "title": "B", "snippet": "b"},
        ],
    )

    sources = await sources_repo.list_for_run(run.id)
    assert len(sources) == 2
    assert {s.tool_name for s in sources} == {"exa", "reddit"}


async def test_exports_repository_lifecycle(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    runs_repo = RunsRepository(session_factory)
    exports_repo = ExportsRepository(session_factory)
    run = await runs_repo.create(topic="topic", constraints=None)

    export = await exports_repo.create(run.id, "pdf")
    assert export.status == "generating"

    assert await exports_repo.get(run.id, "pdf") is not None

    await exports_repo.mark_ready(export.id, "exports/run/report.pdf")
    ready = await exports_repo.get(run.id, "pdf")
    assert ready is not None
    assert ready.status == "ready"
    assert ready.minio_key == "exports/run/report.pdf"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/integration/storage/test_repositories.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdrops.storage.postgres.repositories'`.

- [ ] **Step 3: Implement RunsRepository**

Create `backend/src/agentdrops/storage/postgres/repositories/__init__.py` (empty).

Create `backend/src/agentdrops/storage/postgres/repositories/runs.py`:

```python
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentdrops.storage.postgres.models import RunModel


class RunsRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, topic: str, constraints: str | None) -> RunModel:
        async with self._session_factory() as session:
            run = RunModel(topic=topic, constraints=constraints, status="queued")
            session.add(run)
            await session.commit()
            await session.refresh(run)
            return run

    async def get(self, run_id: uuid.UUID) -> RunModel | None:
        async with self._session_factory() as session:
            return await session.get(RunModel, run_id)

    async def list_page(self, limit: int, offset: int) -> tuple[list[RunModel], int]:
        async with self._session_factory() as session:
            total = (await session.execute(select(func.count()).select_from(RunModel))).scalar_one()
            result = await session.execute(
                select(RunModel).order_by(RunModel.created_at.desc()).limit(limit).offset(offset)
            )
            return list(result.scalars().all()), total

    async def update_status(
        self, run_id: uuid.UUID, status: str, *, error: str | None = None
    ) -> None:
        async with self._session_factory() as session:
            run = await session.get(RunModel, run_id)
            if run is None:
                return
            run.status = status
            if error is not None:
                run.error = error
            await session.commit()

    async def save_research_output(
        self,
        run_id: uuid.UUID,
        *,
        research_brief: str | None = None,
        final_report: str | None = None,
        idea_onepager: dict[str, Any] | None = None,
    ) -> None:
        async with self._session_factory() as session:
            run = await session.get(RunModel, run_id)
            if run is None:
                return
            if research_brief is not None:
                run.research_brief = research_brief
            if final_report is not None:
                run.final_report = final_report
            if idea_onepager is not None:
                run.idea_onepager = idea_onepager
            await session.commit()
```

- [ ] **Step 4: Implement EventsRepository**

Create `backend/src/agentdrops/storage/postgres/repositories/events.py`:

```python
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentdrops.storage.postgres.models import RunEventModel


class EventsRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def append(
        self,
        run_id: uuid.UUID,
        node_name: str,
        event_type: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> RunEventModel:
        async with self._session_factory() as session:
            event = RunEventModel(
                run_id=run_id, node_name=node_name, event_type=event_type,
                message=message, payload=payload,
            )
            session.add(event)
            await session.commit()
            await session.refresh(event)
            return event

    async def list_for_run(self, run_id: uuid.UUID) -> list[RunEventModel]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(RunEventModel)
                .where(RunEventModel.run_id == run_id)
                .order_by(RunEventModel.created_at.asc())
            )
            return list(result.scalars().all())
```

- [ ] **Step 5: Implement SourcesRepository**

Create `backend/src/agentdrops/storage/postgres/repositories/sources.py`:

```python
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentdrops.storage.postgres.models import SourceModel


class SourcesRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add_many(self, run_id: uuid.UUID, sources: list[dict[str, Any]]) -> None:
        if not sources:
            return
        async with self._session_factory() as session:
            for item in sources:
                session.add(
                    SourceModel(
                        run_id=run_id,
                        tool_name=item["tool_name"],
                        url=item["url"],
                        title=item["title"],
                        snippet=item["snippet"],
                    )
                )
            await session.commit()

    async def list_for_run(self, run_id: uuid.UUID) -> list[SourceModel]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(SourceModel)
                .where(SourceModel.run_id == run_id)
                .order_by(SourceModel.retrieved_at.asc())
            )
            return list(result.scalars().all())
```

- [ ] **Step 6: Implement ExportsRepository**

Create `backend/src/agentdrops/storage/postgres/repositories/exports.py`:

```python
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentdrops.storage.postgres.models import ExportModel


class ExportsRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, run_id: uuid.UUID, format: str) -> ExportModel:
        async with self._session_factory() as session:
            export = ExportModel(run_id=run_id, format=format, status="generating")
            session.add(export)
            await session.commit()
            await session.refresh(export)
            return export

    async def get(self, run_id: uuid.UUID, format: str) -> ExportModel | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ExportModel)
                .where(ExportModel.run_id == run_id, ExportModel.format == format)
                .order_by(ExportModel.generated_at.desc().nullslast())
            )
            return result.scalars().first()

    async def mark_ready(self, export_id: uuid.UUID, minio_key: str) -> None:
        async with self._session_factory() as session:
            export = await session.get(ExportModel, export_id)
            if export is None:
                return
            export.status = "ready"
            export.minio_key = minio_key
            export.generated_at = datetime.now(UTC)
            await session.commit()

    async def mark_failed(self, export_id: uuid.UUID) -> None:
        async with self._session_factory() as session:
            export = await session.get(ExportModel, export_id)
            if export is None:
                return
            export.status = "failed"
            await session.commit()
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/integration/storage/test_repositories.py -v`
Expected: all tests PASS.

- [ ] **Step 8: Run mypy and ruff**

Run: `cd backend && uv run mypy src/agentdrops/storage && uv run ruff check src/agentdrops/storage tests/integration`
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add backend/src/agentdrops/storage/postgres/repositories backend/tests/integration/storage
git commit -m "feat(backend): add Postgres repository layer for runs/events/sources/exports"
```

---

### Task 4: FastAPI schemas, app factory, and `/runs` routes

**Files:**
- Create: `backend/src/agentdrops/api/__init__.py`
- Create: `backend/src/agentdrops/api/schemas/__init__.py`
- Create: `backend/src/agentdrops/api/schemas/runs.py`
- Create: `backend/src/agentdrops/api/deps.py`
- Create: `backend/src/agentdrops/api/app.py`
- Create: `backend/src/agentdrops/api/routes/__init__.py`
- Create: `backend/src/agentdrops/api/routes/runs.py`
- Test: `backend/tests/integration/api/__init__.py`
- Test: `backend/tests/integration/api/conftest.py`
- Test: `backend/tests/integration/api/test_runs_routes.py`

**Interfaces:**
- Consumes: `RunsRepository`, `SourcesRepository` from Task 3.
- Produces: `create_app() -> FastAPI` (consumed by Task 15's SSE route additions and by `Dockerfile`/`docker-compose.yml` from Task 1); dependency provider functions `get_runs_repository`, `get_events_repository`, `get_sources_repository`, `get_exports_repository`, `get_arq_pool` (consumed by Task 15's events route and Task 16's export routes — all routers import these same functions so `dependency_overrides` in tests covers every route module).

- [ ] **Step 1: Write the failing API tests**

Create `backend/tests/integration/api/__init__.py` (empty).

Create `backend/tests/integration/api/conftest.py`:

```python
import pathlib
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer

from agentdrops.api.deps import (
    get_arq_pool,
    get_events_repository,
    get_exports_repository,
    get_runs_repository,
    get_sources_repository,
)
from agentdrops.api.routes.runs import router as runs_router
from agentdrops.storage.postgres.repositories.events import EventsRepository
from agentdrops.storage.postgres.repositories.exports import ExportsRepository
from agentdrops.storage.postgres.repositories.runs import RunsRepository
from agentdrops.storage.postgres.repositories.sources import SourcesRepository
from agentdrops.storage.postgres.session import create_engine, create_session_factory

_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[2]


class FakeArqPool:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, tuple[Any, ...]]] = []

    async def enqueue_job(self, function: str, *args: Any) -> None:
        self.enqueued.append((function, args))


@pytest.fixture(scope="module")
def postgres_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as pg:
        sync_url = pg.get_connection_url()
        cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
        cfg.set_main_option("sqlalchemy.url", sync_url)
        command.upgrade(cfg, "head")
        yield sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")


@pytest.fixture
async def session_factory(postgres_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(postgres_url)
    yield create_session_factory(engine)
    await engine.dispose()


@pytest.fixture
def fake_arq_pool() -> FakeArqPool:
    return FakeArqPool()


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession], fake_arq_pool: FakeArqPool
) -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    app.include_router(runs_router)
    app.dependency_overrides[get_runs_repository] = lambda: RunsRepository(session_factory)
    app.dependency_overrides[get_events_repository] = lambda: EventsRepository(session_factory)
    app.dependency_overrides[get_sources_repository] = lambda: SourcesRepository(session_factory)
    app.dependency_overrides[get_exports_repository] = lambda: ExportsRepository(session_factory)
    app.dependency_overrides[get_arq_pool] = lambda: fake_arq_pool
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
```

Create `backend/tests/integration/api/test_runs_routes.py`:

```python
from agentdrops.storage.postgres.repositories.runs import RunsRepository
from agentdrops.storage.postgres.repositories.sources import SourcesRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def test_create_run_enqueues_job_and_returns_201(client, fake_arq_pool) -> None:  # type: ignore[no-untyped-def]
    response = await client.post("/runs", json={"topic": "AI note-taking apps"})
    assert response.status_code == 201
    body = response.json()
    assert "run_id" in body
    assert fake_arq_pool.enqueued == [("run_research_job", (body["run_id"],))]


async def test_list_runs_returns_paginated_summaries(
    client, session_factory: async_sessionmaker[AsyncSession]  # type: ignore[no-untyped-def]
) -> None:
    repo = RunsRepository(session_factory)
    await repo.create(topic="first", constraints=None)
    await repo.create(topic="second", constraints=None)

    response = await client.get("/runs", params={"limit": 1, "offset": 0})

    assert response.status_code == 200
    body = response.json()
    assert len(body["runs"]) == 1
    assert body["total"] >= 2
    assert body["limit"] == 1
    assert body["offset"] == 0


async def test_get_run_returns_404_for_missing_run(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.get("/runs/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


async def test_get_run_returns_detail_with_sources(
    client, session_factory: async_sessionmaker[AsyncSession]  # type: ignore[no-untyped-def]
) -> None:
    runs_repo = RunsRepository(session_factory)
    sources_repo = SourcesRepository(session_factory)
    run = await runs_repo.create(topic="AI note-taking apps", constraints="B2B focus")
    await sources_repo.add_many(
        run.id, [{"tool_name": "exa", "url": "https://a.com", "title": "A", "snippet": "a"}]
    )

    response = await client.get(f"/runs/{run.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["topic"] == "AI note-taking apps"
    assert body["constraints"] == "B2B focus"
    assert body["status"] == "queued"
    assert len(body["sources"]) == 1
    assert body["sources"][0]["tool_name"] == "exa"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/integration/api/test_runs_routes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdrops.api'`.

- [ ] **Step 3: Write the Pydantic schemas**

Create `backend/src/agentdrops/api/__init__.py` and `backend/src/agentdrops/api/schemas/__init__.py` (both empty).

Create `backend/src/agentdrops/api/schemas/runs.py`:

```python
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

RunStatus = Literal["queued", "running", "completed", "failed"]


class RunCreateRequest(BaseModel):
    topic: str
    constraints: str | None = None


class RunCreateResponse(BaseModel):
    run_id: uuid.UUID


class RunSummary(BaseModel):
    id: uuid.UUID
    topic: str
    status: RunStatus
    created_at: datetime
    updated_at: datetime


class RunListResponse(BaseModel):
    runs: list[RunSummary]
    total: int
    limit: int
    offset: int


class IdeaOnePager(BaseModel):
    problem_statement: str
    recommended_direction: str
    key_assumptions: list[str]
    mvp_scope: list[str]
    not_doing: list[str]
    open_questions: list[str]


class SourceOut(BaseModel):
    id: uuid.UUID
    tool_name: str
    url: str
    title: str
    snippet: str
    retrieved_at: datetime


class RunDetail(BaseModel):
    id: uuid.UUID
    topic: str
    constraints: str | None
    status: RunStatus
    research_brief: str | None
    final_report: str | None
    idea_onepager: IdeaOnePager | None
    sources: list[SourceOut]
    error: str | None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 4: Write dependency providers**

Create `backend/src/agentdrops/api/deps.py`:

```python
from arq import ArqRedis
from fastapi import Request

from agentdrops.storage.postgres.repositories.events import EventsRepository
from agentdrops.storage.postgres.repositories.exports import ExportsRepository
from agentdrops.storage.postgres.repositories.runs import RunsRepository
from agentdrops.storage.postgres.repositories.sources import SourcesRepository


def get_runs_repository(request: Request) -> RunsRepository:
    return RunsRepository(request.app.state.session_factory)


def get_events_repository(request: Request) -> EventsRepository:
    return EventsRepository(request.app.state.session_factory)


def get_sources_repository(request: Request) -> SourcesRepository:
    return SourcesRepository(request.app.state.session_factory)


def get_exports_repository(request: Request) -> ExportsRepository:
    return ExportsRepository(request.app.state.session_factory)


async def get_arq_pool(request: Request) -> ArqRedis:
    pool: ArqRedis = request.app.state.arq_pool
    return pool
```

- [ ] **Step 5: Write the runs routes**

Create `backend/src/agentdrops/api/routes/__init__.py` (empty).

Create `backend/src/agentdrops/api/routes/runs.py`:

```python
import uuid
from typing import Annotated

from arq import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Query

from agentdrops.api.deps import get_arq_pool, get_runs_repository, get_sources_repository
from agentdrops.api.schemas.runs import (
    IdeaOnePager,
    RunCreateRequest,
    RunCreateResponse,
    RunDetail,
    RunListResponse,
    RunSummary,
    SourceOut,
)
from agentdrops.storage.postgres.repositories.runs import RunsRepository
from agentdrops.storage.postgres.repositories.sources import SourcesRepository

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", response_model=RunCreateResponse, status_code=201)
async def create_run(
    body: RunCreateRequest,
    runs_repo: Annotated[RunsRepository, Depends(get_runs_repository)],
    arq_pool: Annotated[ArqRedis, Depends(get_arq_pool)],
) -> RunCreateResponse:
    run = await runs_repo.create(topic=body.topic, constraints=body.constraints)
    await arq_pool.enqueue_job("run_research_job", str(run.id))
    return RunCreateResponse(run_id=run.id)


@router.get("", response_model=RunListResponse)
async def list_runs(
    runs_repo: Annotated[RunsRepository, Depends(get_runs_repository)],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> RunListResponse:
    runs, total = await runs_repo.list_page(limit=limit, offset=offset)
    return RunListResponse(
        runs=[
            RunSummary(
                id=r.id,
                topic=r.topic,
                status=r.status,  # type: ignore[arg-type]
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in runs
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(
    run_id: uuid.UUID,
    runs_repo: Annotated[RunsRepository, Depends(get_runs_repository)],
    sources_repo: Annotated[SourcesRepository, Depends(get_sources_repository)],
) -> RunDetail:
    run = await runs_repo.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    sources = await sources_repo.list_for_run(run_id)
    return RunDetail(
        id=run.id,
        topic=run.topic,
        constraints=run.constraints,
        status=run.status,  # type: ignore[arg-type]
        research_brief=run.research_brief,
        final_report=run.final_report,
        idea_onepager=IdeaOnePager(**run.idea_onepager) if run.idea_onepager else None,
        sources=[
            SourceOut(
                id=s.id,
                tool_name=s.tool_name,
                url=s.url,
                title=s.title,
                snippet=s.snippet,
                retrieved_at=s.retrieved_at,
            )
            for s in sources
        ],
        error=run.error,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )
```

- [ ] **Step 6: Write the app factory**

Create `backend/src/agentdrops/api/app.py`:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agentdrops.api.routes.runs import router as runs_router
from agentdrops.config import get_settings
from agentdrops.storage.postgres.session import create_engine, create_session_factory


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url)
        app.state.session_factory = create_session_factory(engine)
        app.state.arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        try:
            yield
        finally:
            await app.state.arq_pool.close()
            await engine.dispose()

    app = FastAPI(title="Deep Research Market Agent API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(runs_router)
    return app
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/integration/api/test_runs_routes.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 8: Run mypy and ruff**

Run: `cd backend && uv run mypy src/agentdrops/api && uv run ruff check src/agentdrops/api tests/integration/api`
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add backend/src/agentdrops/api backend/tests/integration/api
git commit -m "feat(backend): add FastAPI app factory and /runs routes"
```

---

### Task 5: Research graph state, event emitter, and idea one-pager schema

**Files:**
- Create: `backend/src/agentdrops/research/__init__.py`
- Create: `backend/src/agentdrops/research/state.py`
- Create: `backend/src/agentdrops/research/prompts.py`
- Create: `backend/src/agentdrops/research/schemas.py`
- Create: `backend/src/agentdrops/idearefine/__init__.py`
- Create: `backend/src/agentdrops/idearefine/schemas.py`
- Test: `backend/tests/unit/research/__init__.py`
- Test: `backend/tests/unit/research/test_state.py`

**Interfaces:**
- Produces: `Source` (dataclass: `tool_name`, `url`, `title`, `snippet`), `EventEmitter` (Protocol: `async def __call__(self, node_name: str, event_type: str, message: str, payload: dict[str, Any] | None = None) -> None`), `ResearcherBranchState` (TypedDict: `sub_topic: str`), `AgentState` (TypedDict with `Annotated[list[str], operator.add]` reducer fields `compressed_notes` and `Annotated[list[Source], operator.add]` field `all_sources`) — all consumed by every node task (6-13). `ResearchBriefOutput` (Pydantic: `brief: str`) consumed by Task 7. `IdeaOnePagerSchema` (Pydantic, matches `docs/ui-builder-system-prompt.md` §4 `idea_onepager` shape exactly) consumed by Task 12 and stored via Task 3's `RunsRepository.save_research_output`.

- [ ] **Step 1: Write the failing state test**

Create `backend/tests/unit/research/__init__.py` (empty).

Create `backend/tests/unit/research/test_state.py`:

```python
import operator
from typing import Annotated, get_type_hints

from agentdrops.research.state import AgentState, Source


def test_source_is_a_plain_value_dataclass() -> None:
    source = Source(tool_name="exa", url="https://a.com", title="A", snippet="a")
    assert source.tool_name == "exa"
    assert source.url == "https://a.com"


def test_agent_state_reducer_fields_use_operator_add() -> None:
    hints = get_type_hints(AgentState, include_extras=True)
    assert hints["compressed_notes"] == Annotated[list[str], operator.add]
    assert hints["all_sources"] == Annotated[list[Source], operator.add]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/research/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdrops.research'`.

- [ ] **Step 3: Write state.py**

Create `backend/src/agentdrops/research/__init__.py` (empty).

Create `backend/src/agentdrops/research/state.py`:

```python
import operator
from dataclasses import dataclass
from typing import Annotated, Any, Protocol, TypedDict

from agentdrops.idearefine.schemas import IdeaOnePagerSchema


@dataclass(frozen=True)
class Source:
    tool_name: str
    url: str
    title: str
    snippet: str


class EventEmitter(Protocol):
    async def __call__(
        self,
        node_name: str,
        event_type: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None: ...


class ResearcherBranchState(TypedDict):
    sub_topic: str


class AgentState(TypedDict, total=False):
    topic: str
    constraints: str | None
    research_brief: str
    pending_sub_topics: list[str]
    research_complete: bool
    supervisor_iteration: int
    compressed_notes: Annotated[list[str], operator.add]
    all_sources: Annotated[list[Source], operator.add]
    final_report: str
    idea_onepager: IdeaOnePagerSchema | None
```

- [ ] **Step 4: Write idea one-pager schema**

Create `backend/src/agentdrops/idearefine/__init__.py` (empty).

Create `backend/src/agentdrops/idearefine/schemas.py`:

```python
from pydantic import BaseModel, Field


class IdeaOnePagerSchema(BaseModel):
    problem_statement: str
    recommended_direction: str
    key_assumptions: list[str] = Field(default_factory=list)
    mvp_scope: list[str] = Field(default_factory=list)
    not_doing: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
```

- [ ] **Step 5: Write research brief schema**

Create `backend/src/agentdrops/research/schemas.py`:

```python
from pydantic import BaseModel, Field


class ResearchBriefOutput(BaseModel):
    brief: str = Field(
        description=(
            "Structured research brief in markdown covering: objectives, key research "
            "questions, target scope, and any constraints."
        )
    )
```

- [ ] **Step 6: Write prompts module**

Create `backend/src/agentdrops/research/prompts.py`:

```python
RESEARCH_BRIEF_SYSTEM_PROMPT = """You are a research lead. Given a market/topic and \
optional constraints, produce a structured research brief in markdown with sections: \
Objectives, Key Questions, Scope & Constraints. Be concise and concrete."""

SUPERVISOR_SYSTEM_PROMPT = """You are the lead researcher supervising a market research \
investigation. You have a research brief. Use the `conduct_research` tool to delegate up \
to {max_concurrent} sub-topics per round to sub-researchers who will each investigate one \
sub-topic using web, news, and community search tools. Use `think_tool` between rounds to \
reflect on what has been learned and what is still missing. When you have enough information \
to write a comprehensive report, call `research_complete`. You have at most {max_iterations} \
rounds of delegation."""

RESEARCHER_SYSTEM_PROMPT = """You are a research sub-agent investigating one sub-topic of a \
larger market research effort. Use the available search tools (web, news, community/Reddit) \
to gather concrete, well-sourced findings. Use `think_tool` to reflect between searches. Once \
you have sufficient findings for this sub-topic, stop calling tools and write a concise summary \
of what you found, citing sources by title."""

COMPRESS_RESEARCH_SYSTEM_PROMPT = """Compress the following raw research notes for one \
sub-topic into a clean, dense summary (3-6 sentences) preserving concrete facts, figures, and \
named sources. Do not add commentary or caveats not present in the notes."""

FINAL_REPORT_SYSTEM_PROMPT = """You are a market research analyst. Write a comprehensive, \
long-form market research report in markdown using the research brief and the compressed \
findings below. Include headings, an executive summary, and inline citations as \
[Source Title](url) linking to the URLs mentioned in the findings."""
```

(The idea-refine prompts live in `idearefine/prompts.py`, created in Task 12, per the package layout in `docs/superpowers/specs/2026-07-12-deepresearch-market-agent-design.md`.)

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/research/test_state.py -v`
Expected: both tests PASS.

- [ ] **Step 8: Run mypy and ruff**

Run: `cd backend && uv run mypy src/agentdrops/research src/agentdrops/idearefine && uv run ruff check src/agentdrops/research src/agentdrops/idearefine tests/unit/research`
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add backend/src/agentdrops/research backend/src/agentdrops/idearefine backend/tests/unit/research
git commit -m "feat(backend): add research graph state, prompts, and idea one-pager schema"
```

---

### Task 6: LLM helpers — structured output and tool-use loop

**Files:**
- Create: `backend/src/agentdrops/research/llm.py`
- Test: `backend/tests/unit/research/test_llm.py`

**Interfaces:**
- Consumes: `LLM_RETRY` from existing `resilience/llm_retry.py`.
- Produces: `async def call_structured(client: anthropic.AsyncAnthropic, *, system: str, user: str, schema: type[ModelT], model: str = DEFAULT_MODEL, max_tokens: int = 4096) -> ModelT` (consumed by Tasks 7, 12); `ToolHandler = Callable[[str, dict[str, Any]], Awaitable[str]]` and `async def run_tool_loop(client, *, system, initial_user_message, tools, tool_handler, stop_tool_names, model=DEFAULT_MODEL, max_tokens=4096, max_iterations=8) -> list[dict[str, Any]]` returning the full message history (consumed by Tasks 8, 9); `DEFAULT_MODEL: str` constant.

Both functions call the real Anthropic API (`client.messages.create`) — tests use a fake client with a scripted `messages.create` so no network/API key is needed, matching the DI pattern already used for `webtools/*` (client passed in, not constructed internally).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/research/test_llm.py`:

```python
from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import BaseModel

from agentdrops.research.llm import call_structured, run_tool_loop


class _Output(BaseModel):
    value: str


@dataclass
class _ToolUseBlock:
    type: str
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class _TextBlock:
    type: str
    text: str


@dataclass
class _Message:
    content: list[Any]
    stop_reason: str


class _FakeMessages:
    def __init__(self, responses: list[_Message]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> _Message:
        self.calls.append(kwargs)
        return self._responses[len(self.calls) - 1]


class _FakeClient:
    def __init__(self, responses: list[_Message]) -> None:
        self.messages = _FakeMessages(responses)


async def test_call_structured_returns_parsed_schema_from_tool_use() -> None:
    response = _Message(
        content=[_ToolUseBlock(type="tool_use", id="t1", name="emit__output", input={"value": "hi"})],
        stop_reason="tool_use",
    )
    client = _FakeClient([response])

    result = await call_structured(client, system="sys", user="usr", schema=_Output)  # type: ignore[arg-type]

    assert result == _Output(value="hi")


async def test_call_structured_raises_if_no_tool_use_returned() -> None:
    response = _Message(content=[_TextBlock(type="text", text="oops")], stop_reason="end_turn")
    client = _FakeClient([response])

    with pytest.raises(ValueError, match="did not return"):
        await call_structured(client, system="sys", user="usr", schema=_Output)  # type: ignore[arg-type]


async def test_run_tool_loop_calls_handler_and_stops_on_stop_tool() -> None:
    first = _Message(
        content=[_ToolUseBlock(type="tool_use", id="a", name="search", input={"query": "x"})],
        stop_reason="tool_use",
    )
    second = _Message(
        content=[_ToolUseBlock(type="tool_use", id="b", name="done", input={})],
        stop_reason="tool_use",
    )
    client = _FakeClient([first, second])
    handled: list[tuple[str, dict[str, Any]]] = []

    async def handler(name: str, input_: dict[str, Any]) -> str:
        handled.append((name, input_))
        return "result text"

    messages = await run_tool_loop(
        client,  # type: ignore[arg-type]
        system="sys",
        initial_user_message="go",
        tools=[],
        tool_handler=handler,
        stop_tool_names={"done"},
        max_iterations=5,
    )

    assert handled == [("search", {"query": "x"})]
    assert len(messages) == 4  # user, assistant(1st), user(tool result), assistant(2nd)


async def test_run_tool_loop_stops_after_max_iterations() -> None:
    looping = _Message(
        content=[_ToolUseBlock(type="tool_use", id="a", name="search", input={"query": "x"})],
        stop_reason="tool_use",
    )
    client = _FakeClient([looping, looping, looping])

    async def handler(name: str, input_: dict[str, Any]) -> str:
        return "result"

    messages = await run_tool_loop(
        client,  # type: ignore[arg-type]
        system="sys",
        initial_user_message="go",
        tools=[],
        tool_handler=handler,
        stop_tool_names={"done"},
        max_iterations=3,
    )

    assert client.messages.calls.__len__() == 3
    assert len(messages) == 1 + 3 * 2  # initial user + 3 * (assistant + tool-result user)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/research/test_llm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdrops.research.llm'`.

- [ ] **Step 3: Implement research/llm.py**

Create `backend/src/agentdrops/research/llm.py`:

```python
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from agentdrops.resilience.llm_retry import LLM_RETRY

DEFAULT_MODEL = "claude-sonnet-5"

ModelT = TypeVar("ModelT", bound=BaseModel)
ToolHandler = Callable[[str, dict[str, Any]], Awaitable[str]]


class AnthropicMessagesClient(Protocol):
    messages: Any


@LLM_RETRY
async def _create_message(
    client: AnthropicMessagesClient,
    *,
    model: str,
    max_tokens: int,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_choice: dict[str, Any] | None = None,
) -> Any:
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
        "tools": tools,
    }
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    return await client.messages.create(**kwargs)


async def call_structured(
    client: AnthropicMessagesClient,
    *,
    system: str,
    user: str,
    schema: type[ModelT],
    model: str = DEFAULT_MODEL,
    max_tokens: int = 4096,
) -> ModelT:
    tool_name = f"emit__{schema.__name__.lower()}"
    response = await _create_message(
        client,
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        tools=[
            {
                "name": tool_name,
                "description": f"Emit the {schema.__name__} result.",
                "input_schema": schema.model_json_schema(),
            }
        ],
        tool_choice={"type": "tool", "name": tool_name},
    )
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
            return schema.model_validate(block.input)
    raise ValueError(f"Model did not return a {tool_name} tool call")


def _extract_text(content: list[Any]) -> str:
    return "\n".join(block.text for block in content if getattr(block, "type", None) == "text")


async def run_tool_loop(
    client: AnthropicMessagesClient,
    *,
    system: str,
    initial_user_message: str,
    tools: list[dict[str, Any]],
    tool_handler: ToolHandler,
    stop_tool_names: set[str],
    model: str = DEFAULT_MODEL,
    max_tokens: int = 4096,
    max_iterations: int = 8,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "user", "content": initial_user_message}]
    for _ in range(max_iterations):
        response = await _create_message(
            client,
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=tools,
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            break
        tool_results: list[dict[str, Any]] = []
        stopped = False
        for block in response.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            if block.name in stop_tool_names:
                stopped = True
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": "acknowledged"}
                )
                continue
            result_text = await tool_handler(block.name, block.input)
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": result_text}
            )
        messages.append({"role": "user", "content": tool_results})
        if stopped:
            break
    return messages
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/research/test_llm.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 5: Run mypy and ruff**

Run: `cd backend && uv run mypy src/agentdrops/research/llm.py && uv run ruff check src/agentdrops/research/llm.py tests/unit/research/test_llm.py`
Expected: no errors. (If mypy flags the `Any`-typed `AnthropicMessagesClient.messages` attribute, that is expected/acceptable — the real `anthropic.AsyncAnthropic` client satisfies the Protocol structurally.)

- [ ] **Step 6: Commit**

```bash
git add backend/src/agentdrops/research/llm.py backend/tests/unit/research/test_llm.py
git commit -m "feat(backend): add structured-output and tool-use-loop LLM helpers"
```

---

### Task 7: `write_research_brief` node

**Files:**
- Create: `backend/src/agentdrops/research/nodes/__init__.py`
- Create: `backend/src/agentdrops/research/nodes/write_research_brief.py`
- Test: `backend/tests/unit/research/nodes/__init__.py`
- Test: `backend/tests/unit/research/nodes/test_write_research_brief.py`

**Interfaces:**
- Consumes: `call_structured` from Task 6; `AgentState`, `EventEmitter` from Task 5; `ResearchBriefOutput` from Task 5.
- Produces: `async def write_research_brief(state: AgentState, *, client: AnthropicMessagesClient, emit: EventEmitter) -> dict[str, str]` returning `{"research_brief": <markdown>}` — a LangGraph node function, consumed by Task 13's graph assembly.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/research/nodes/__init__.py` (empty).

Create `backend/tests/unit/research/nodes/test_write_research_brief.py`:

```python
from typing import Any
from unittest.mock import AsyncMock

from agentdrops.research.nodes.write_research_brief import write_research_brief


async def test_write_research_brief_calls_llm_and_returns_brief(monkeypatch: Any) -> None:
    async def fake_call_structured(client: Any, *, system: str, user: str, schema: Any) -> Any:
        assert "AI note-taking apps" in user
        assert "US market only" in user
        return schema(brief="# Brief\n\nObjectives...")

    monkeypatch.setattr(
        "agentdrops.research.nodes.write_research_brief.call_structured", fake_call_structured
    )
    emit = AsyncMock()

    result = await write_research_brief(
        {"topic": "AI note-taking apps", "constraints": "US market only"},
        client=object(),
        emit=emit,
    )

    assert result == {"research_brief": "# Brief\n\nObjectives..."}
    assert emit.await_count == 2
    assert emit.await_args_list[0].args[1] == "started"
    assert emit.await_args_list[1].args[1] == "completed"


async def test_write_research_brief_omits_constraints_line_when_absent(monkeypatch: Any) -> None:
    captured_user = {}

    async def fake_call_structured(client: Any, *, system: str, user: str, schema: Any) -> Any:
        captured_user["user"] = user
        return schema(brief="# Brief")

    monkeypatch.setattr(
        "agentdrops.research.nodes.write_research_brief.call_structured", fake_call_structured
    )
    emit = AsyncMock()

    await write_research_brief({"topic": "topic", "constraints": None}, client=object(), emit=emit)

    assert "Constraints" not in captured_user["user"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/research/nodes/test_write_research_brief.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdrops.research.nodes'`.

- [ ] **Step 3: Implement the node**

Create `backend/src/agentdrops/research/nodes/__init__.py` (empty).

Create `backend/src/agentdrops/research/nodes/write_research_brief.py`:

```python
from typing import Any

from agentdrops.research.llm import call_structured
from agentdrops.research.prompts import RESEARCH_BRIEF_SYSTEM_PROMPT
from agentdrops.research.schemas import ResearchBriefOutput
from agentdrops.research.state import EventEmitter


async def write_research_brief(
    state: dict[str, Any], *, client: Any, emit: EventEmitter
) -> dict[str, str]:
    topic = state["topic"]
    await emit("write_research_brief", "started", f'Turning "{topic}" into a research brief')

    user = f"Topic: {topic}"
    constraints = state.get("constraints")
    if constraints:
        user += f"\nConstraints: {constraints}"

    output = await call_structured(
        client, system=RESEARCH_BRIEF_SYSTEM_PROMPT, user=user, schema=ResearchBriefOutput
    )

    await emit("write_research_brief", "completed", "Research brief ready")
    return {"research_brief": output.brief}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/research/nodes/test_write_research_brief.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Run mypy and ruff**

Run: `cd backend && uv run mypy src/agentdrops/research/nodes && uv run ruff check src/agentdrops/research/nodes tests/unit/research/nodes`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/src/agentdrops/research/nodes backend/tests/unit/research/nodes
git commit -m "feat(backend): add write_research_brief graph node"
```

---

### Task 8: Tool adapter and `researcher` node

**Files:**
- Create: `backend/src/agentdrops/research/tools.py`
- Create: `backend/src/agentdrops/research/nodes/researcher.py`
- Test: `backend/tests/unit/research/test_tools.py`
- Test: `backend/tests/unit/research/nodes/test_researcher.py`

**Interfaces:**
- Consumes: `BaseSearchTool`, `SearchResult`, `SearchToolError` from existing `webtools/base.py`; `run_tool_loop` from Task 6; `Source`, `EventEmitter` from Task 5.
- Produces: `build_tool_specs(search_tools: list[BaseSearchTool]) -> list[dict[str, Any]]`, `build_tool_handler(search_tools: list[BaseSearchTool], *, on_source: Callable[[str, SearchResult], Awaitable[None]] | None = None) -> ToolHandler` (consumed by Task 10's supervisor node too); `async def researcher(state: dict[str, Any], *, client: Any, search_tools: list[BaseSearchTool], emit: EventEmitter, max_tool_calls: int) -> dict[str, Any]` returning `{"sub_topic": str, "raw_notes": str, "sources": list[Source]}` (consumed by Task 10's `researcher_branch` node).

- [ ] **Step 1: Write the failing tool-adapter test**

Create `backend/tests/unit/research/test_tools.py`:

```python
from typing import ClassVar

from agentdrops.research.tools import build_tool_handler, build_tool_specs
from agentdrops.webtools.base import BaseSearchTool, SearchResult


class _StubTool(BaseSearchTool):
    name: ClassVar[str] = "stub"

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        return [SearchResult(tool_name="stub", title=f"Result for {query}", url="https://x.com", snippet="s")]


def test_build_tool_specs_includes_one_per_tool_plus_think_tool() -> None:
    specs = build_tool_specs([_StubTool()])
    names = {s["name"] for s in specs}
    assert names == {"stub_search", "think_tool"}


async def test_tool_handler_invokes_matching_tool_and_reports_source() -> None:
    reported = []

    async def on_source(tool_name: str, result: SearchResult) -> None:
        reported.append((tool_name, result.title))

    handler = build_tool_handler([_StubTool()], on_source=on_source)

    output = await handler("stub_search", {"query": "AI notes"})

    assert "Result for AI notes" in output
    assert reported == [("stub", "Result for AI notes")]


async def test_tool_handler_think_tool_does_not_search() -> None:
    handler = build_tool_handler([_StubTool()])
    output = await handler("think_tool", {"reflection": "hmm"})
    assert output == "Reflection recorded."


async def test_tool_handler_unknown_tool_returns_message() -> None:
    handler = build_tool_handler([_StubTool()])
    output = await handler("mystery_tool", {})
    assert output == "Unknown tool: mystery_tool"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/research/test_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdrops.research.tools'`.

- [ ] **Step 3: Implement research/tools.py**

Create `backend/src/agentdrops/research/tools.py`:

```python
from collections.abc import Awaitable, Callable
from typing import Any

from agentdrops.research.llm import ToolHandler
from agentdrops.webtools.base import BaseSearchTool, SearchResult, SearchToolError


def build_tool_specs(search_tools: list[BaseSearchTool]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = [
        {
            "name": f"{tool.name}_search",
            "description": f"Search {tool.name} for information relevant to the sub-topic.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        }
        for tool in search_tools
    ]
    specs.append(
        {
            "name": "think_tool",
            "description": (
                "Record a strategic reflection before deciding the next step. "
                "Does not search anything."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"reflection": {"type": "string"}},
                "required": ["reflection"],
            },
        }
    )
    return specs


def build_tool_handler(
    search_tools: list[BaseSearchTool],
    *,
    on_source: Callable[[str, SearchResult], Awaitable[None]] | None = None,
) -> ToolHandler:
    tools_by_name = {f"{tool.name}_search": tool for tool in search_tools}

    async def handler(name: str, input_: dict[str, Any]) -> str:
        if name == "think_tool":
            return "Reflection recorded."
        tool = tools_by_name.get(name)
        if tool is None:
            return f"Unknown tool: {name}"
        try:
            results = await tool.search(input_["query"], max_results=input_.get("max_results", 5))
        except SearchToolError as exc:
            return f"Search failed: {exc}"
        if on_source is not None:
            for result in results:
                await on_source(tool.name, result)
        if not results:
            return "No results found."
        return "\n\n".join(f"{r.title} ({r.url})\n{r.snippet}" for r in results)

    return handler
```

- [ ] **Step 4: Run tool-adapter test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/research/test_tools.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 5: Write the failing researcher-node test**

Create `backend/tests/unit/research/nodes/test_researcher.py`:

```python
from typing import Any, ClassVar
from unittest.mock import AsyncMock

from agentdrops.research.nodes.researcher import researcher
from agentdrops.webtools.base import BaseSearchTool, SearchResult


class _StubTool(BaseSearchTool):
    name: ClassVar[str] = "stub"

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        return [
            SearchResult(
                tool_name="stub", title="Great finding", url="https://x.com", snippet="details"
            )
        ]


async def test_researcher_runs_tool_loop_and_collects_sources(monkeypatch: Any) -> None:
    async def fake_run_tool_loop(client: Any, *, system: str, initial_user_message: str,
                                  tools: Any, tool_handler: Any, stop_tool_names: Any,
                                  max_iterations: int) -> list[dict[str, Any]]:
        # Exercise the real handler once so source collection is verified end-to-end.
        await tool_handler("stub_search", {"query": "AI notes retention"})
        return [
            {"role": "user", "content": initial_user_message},
            {"role": "assistant", "content": [_text("Found that retention is a key driver.")]},
        ]

    monkeypatch.setattr(
        "agentdrops.research.nodes.researcher.run_tool_loop", fake_run_tool_loop
    )
    emit = AsyncMock()

    result = await researcher(
        {"sub_topic": "retention drivers"},
        client=object(),
        search_tools=[_StubTool()],
        emit=emit,
        max_tool_calls=8,
    )

    assert result["sub_topic"] == "retention drivers"
    assert "retention is a key driver" in result["raw_notes"]
    assert len(result["sources"]) == 1
    assert result["sources"][0].tool_name == "stub"
    assert emit.await_count >= 2


def _text(text: str) -> Any:
    from dataclasses import dataclass

    @dataclass
    class _TextBlock:
        type: str
        text: str

    return _TextBlock(type="text", text=text)
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/research/nodes/test_researcher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdrops.research.nodes.researcher'`.

- [ ] **Step 7: Implement the researcher node**

Create `backend/src/agentdrops/research/nodes/researcher.py`:

```python
from typing import Any

from agentdrops.research.llm import run_tool_loop
from agentdrops.research.prompts import RESEARCHER_SYSTEM_PROMPT
from agentdrops.research.state import EventEmitter, Source
from agentdrops.research.tools import build_tool_handler, build_tool_specs
from agentdrops.webtools.base import BaseSearchTool, SearchResult


def _extract_assistant_text(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for message in messages:
        if message["role"] != "assistant":
            continue
        for block in message["content"]:
            if getattr(block, "type", None) == "text":
                lines.append(block.text)
    return "\n".join(lines)


async def researcher(
    state: dict[str, Any],
    *,
    client: Any,
    search_tools: list[BaseSearchTool],
    emit: EventEmitter,
    max_tool_calls: int,
) -> dict[str, Any]:
    sub_topic = state["sub_topic"]
    await emit(
        "researcher", "started", f"Researching sub-topic: {sub_topic}",
        payload={"sub_topic": sub_topic},
    )

    collected_sources: list[Source] = []

    async def on_source(tool_name: str, result: SearchResult) -> None:
        collected_sources.append(
            Source(tool_name=tool_name, url=result.url, title=result.title, snippet=result.snippet)
        )
        await emit(
            "researcher", "tool_call", f"Found: {result.title}",
            payload={"tool": tool_name, "sub_topic": sub_topic, "url": result.url},
        )

    tool_handler = build_tool_handler(search_tools, on_source=on_source)
    tool_specs = build_tool_specs(search_tools)

    messages = await run_tool_loop(
        client,
        system=RESEARCHER_SYSTEM_PROMPT,
        initial_user_message=f"Research sub-topic: {sub_topic}",
        tools=tool_specs,
        tool_handler=tool_handler,
        stop_tool_names=set(),
        max_iterations=max_tool_calls,
    )
    raw_notes = _extract_assistant_text(messages)

    await emit(
        "researcher", "completed", f"Finished sub-topic: {sub_topic}",
        payload={"sub_topic": sub_topic},
    )
    return {"sub_topic": sub_topic, "raw_notes": raw_notes, "sources": collected_sources}
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/research/nodes/test_researcher.py -v`
Expected: PASS.

- [ ] **Step 9: Run mypy and ruff**

Run: `cd backend && uv run mypy src/agentdrops/research && uv run ruff check src/agentdrops/research tests/unit/research`
Expected: no errors.

- [ ] **Step 10: Commit**

```bash
git add backend/src/agentdrops/research/tools.py backend/src/agentdrops/research/nodes/researcher.py backend/tests/unit/research/test_tools.py backend/tests/unit/research/nodes/test_researcher.py
git commit -m "feat(backend): add webtools-to-LLM tool adapter and researcher graph node"
```

---

### Task 9: `compress_research` function

**Files:**
- Modify: `backend/src/agentdrops/research/schemas.py`
- Create: `backend/src/agentdrops/research/nodes/compress_research.py`
- Test: `backend/tests/unit/research/nodes/test_compress_research.py`

**Interfaces:**
- Consumes: `call_structured` from Task 6; `EventEmitter` from Task 5.
- Produces: `CompressedNoteOutput` (Pydantic: `summary: str`) added to `research/schemas.py`; `async def compress_research(sub_topic: str, raw_notes: str, *, client: Any, emit: EventEmitter) -> str` returning a `"### {sub_topic}\n{summary}"` markdown fragment (consumed by Task 10's `researcher_branch` node and Task 11's `final_report_generation` node, which joins these fragments).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/research/nodes/test_compress_research.py`:

```python
from typing import Any
from unittest.mock import AsyncMock

from agentdrops.research.nodes.compress_research import compress_research


async def test_compress_research_summarizes_notes(monkeypatch: Any) -> None:
    async def fake_call_structured(client: Any, *, system: str, user: str, schema: Any) -> Any:
        assert "retention drivers" in user
        assert "raw notes text" in user
        return schema(summary="Retention is driven by X and Y.")

    monkeypatch.setattr(
        "agentdrops.research.nodes.compress_research.call_structured", fake_call_structured
    )
    emit = AsyncMock()

    result = await compress_research(
        "retention drivers", "raw notes text", client=object(), emit=emit
    )

    assert result == "### retention drivers\nRetention is driven by X and Y."
    assert emit.await_count == 2


async def test_compress_research_short_circuits_on_empty_notes() -> None:
    emit = AsyncMock()

    result = await compress_research("retention drivers", "   ", client=object(), emit=emit)

    assert "No findings" in result
    assert emit.await_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/research/nodes/test_compress_research.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdrops.research.nodes.compress_research'`.

- [ ] **Step 3: Add the schema**

In `backend/src/agentdrops/research/schemas.py`, append after `ResearchBriefOutput`:

```python
class CompressedNoteOutput(BaseModel):
    summary: str = Field(
        description="A dense 3-6 sentence summary preserving concrete facts and named sources."
    )
```

- [ ] **Step 4: Implement the function**

Create `backend/src/agentdrops/research/nodes/compress_research.py`:

```python
from typing import Any

from agentdrops.research.llm import call_structured
from agentdrops.research.prompts import COMPRESS_RESEARCH_SYSTEM_PROMPT
from agentdrops.research.schemas import CompressedNoteOutput
from agentdrops.research.state import EventEmitter


async def compress_research(
    sub_topic: str, raw_notes: str, *, client: Any, emit: EventEmitter
) -> str:
    await emit(
        "compress_research", "started", f"Compressing findings for: {sub_topic}",
        payload={"sub_topic": sub_topic},
    )

    if not raw_notes.strip():
        await emit(
            "compress_research", "completed", f"No findings to compress for: {sub_topic}",
            payload={"sub_topic": sub_topic},
        )
        return f"### {sub_topic}\nNo findings for this sub-topic."

    output = await call_structured(
        client,
        system=COMPRESS_RESEARCH_SYSTEM_PROMPT,
        user=f"Sub-topic: {sub_topic}\n\nRaw notes:\n{raw_notes}",
        schema=CompressedNoteOutput,
    )

    await emit(
        "compress_research", "completed", f"Compressed findings for: {sub_topic}",
        payload={"sub_topic": sub_topic},
    )
    return f"### {sub_topic}\n{output.summary}"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/research/nodes/test_compress_research.py -v`
Expected: both tests PASS.

- [ ] **Step 6: Run mypy and ruff**

Run: `cd backend && uv run mypy src/agentdrops/research && uv run ruff check src/agentdrops/research tests/unit/research`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add backend/src/agentdrops/research/schemas.py backend/src/agentdrops/research/nodes/compress_research.py backend/tests/unit/research/nodes/test_compress_research.py
git commit -m "feat(backend): add compress_research node"
```

---

### Task 10: `supervisor` node with parallel `Send`-based delegation

**Files:**
- Create: `backend/src/agentdrops/research/nodes/supervisor.py`
- Test: `backend/tests/unit/research/nodes/test_supervisor.py`

**Interfaces:**
- Consumes: `run_tool_loop` from Task 6; `researcher` from Task 8; `compress_research` from Task 9; `EventEmitter`, `Source` from Task 5; `langgraph.types.Send`.
- Produces: `async def supervisor(state: dict[str, Any], *, client: Any, emit: EventEmitter, max_concurrent: int, max_iterations: int) -> dict[str, Any]` returning `{"pending_sub_topics": list[str], "research_complete": bool, "supervisor_iteration": int}`; `def route_after_supervisor(state: dict[str, Any]) -> list[Send] | str` (returns `"final_report_generation"` or a list of `Send("researcher_branch", {"sub_topic": ...})`); `async def researcher_branch(state: dict[str, Any], *, client: Any, search_tools: list[BaseSearchTool], emit: EventEmitter, max_tool_calls: int) -> dict[str, Any]` returning `{"compressed_notes": [str], "all_sources": list[Source]}` (all three consumed by Task 13's graph assembly).

**Design note:** the spec's architecture names a `supervisor` node and, separately, `researcher` + `compress_research`. This task fuses "one round-trip of research for one sub-topic" (`researcher` then `compress_research`) into a single LangGraph node (`researcher_branch`) so it can be fanned out in parallel via `Send` and reduced back into `AgentState` through the `operator.add` reducers on `compressed_notes`/`all_sources` defined in Task 5 — this is the standard LangGraph map-reduce pattern for "supervisor delegates N parallel sub-agents". The emitted SSE `node_name` values (`"researcher"`, `"compress_research"`) still match the frontend contract exactly; only the internal Python function name differs from the conceptual node.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/research/nodes/test_supervisor.py`:

```python
from typing import Any
from unittest.mock import AsyncMock

from agentdrops.research.nodes.supervisor import researcher_branch, route_after_supervisor, supervisor
from agentdrops.research.state import Source
from langgraph.types import Send


async def test_supervisor_collects_delegated_sub_topics(monkeypatch: Any) -> None:
    async def fake_run_tool_loop(client: Any, *, system: str, initial_user_message: str,
                                  tools: Any, tool_handler: Any, stop_tool_names: Any,
                                  max_iterations: int) -> list[dict[str, Any]]:
        await tool_handler("conduct_research", {"sub_topic": "pricing models"})
        await tool_handler("conduct_research", {"sub_topic": "competitor landscape"})
        return []

    monkeypatch.setattr("agentdrops.research.nodes.supervisor.run_tool_loop", fake_run_tool_loop)
    emit = AsyncMock()

    result = await supervisor(
        {"research_brief": "brief", "compressed_notes": []},
        client=object(), emit=emit, max_concurrent=3, max_iterations=3,
    )

    assert result["pending_sub_topics"] == ["pricing models", "competitor landscape"]
    assert result["research_complete"] is False
    assert result["supervisor_iteration"] == 1


async def test_supervisor_respects_max_concurrent_cap(monkeypatch: Any) -> None:
    async def fake_run_tool_loop(client: Any, *, system: str, initial_user_message: str,
                                  tools: Any, tool_handler: Any, stop_tool_names: Any,
                                  max_iterations: int) -> list[dict[str, Any]]:
        for topic in ["a", "b", "c", "d"]:
            await tool_handler("conduct_research", {"sub_topic": topic})
        return []

    monkeypatch.setattr("agentdrops.research.nodes.supervisor.run_tool_loop", fake_run_tool_loop)

    result = await supervisor(
        {"research_brief": "brief", "compressed_notes": []},
        client=object(), emit=AsyncMock(), max_concurrent=2, max_iterations=3,
    )

    assert result["pending_sub_topics"] == ["a", "b"]


async def test_supervisor_marks_complete_when_model_calls_research_complete(monkeypatch: Any) -> None:
    async def fake_run_tool_loop(client: Any, *, system: str, initial_user_message: str,
                                  tools: Any, tool_handler: Any, stop_tool_names: Any,
                                  max_iterations: int) -> list[dict[str, Any]]:
        await tool_handler("research_complete", {})
        return []

    monkeypatch.setattr("agentdrops.research.nodes.supervisor.run_tool_loop", fake_run_tool_loop)

    result = await supervisor(
        {"research_brief": "brief", "compressed_notes": []},
        client=object(), emit=AsyncMock(), max_concurrent=3, max_iterations=3,
    )

    assert result["research_complete"] is True


async def test_supervisor_forces_complete_at_max_iterations(monkeypatch: Any) -> None:
    async def fake_run_tool_loop(client: Any, *, system: str, initial_user_message: str,
                                  tools: Any, tool_handler: Any, stop_tool_names: Any,
                                  max_iterations: int) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr("agentdrops.research.nodes.supervisor.run_tool_loop", fake_run_tool_loop)

    result = await supervisor(
        {"research_brief": "brief", "compressed_notes": [], "supervisor_iteration": 2},
        client=object(), emit=AsyncMock(), max_concurrent=3, max_iterations=3,
    )

    assert result["supervisor_iteration"] == 3
    assert result["research_complete"] is True


def test_route_after_supervisor_returns_final_report_when_complete() -> None:
    assert route_after_supervisor({"research_complete": True, "pending_sub_topics": []}) == (
        "final_report_generation"
    )


def test_route_after_supervisor_returns_final_report_when_no_pending_topics() -> None:
    assert route_after_supervisor({"research_complete": False, "pending_sub_topics": []}) == (
        "final_report_generation"
    )


def test_route_after_supervisor_fans_out_sends_for_pending_topics() -> None:
    sends = route_after_supervisor(
        {"research_complete": False, "pending_sub_topics": ["a", "b"]}
    )
    assert isinstance(sends, list)
    assert all(isinstance(s, Send) for s in sends)
    assert [s.node for s in sends] == ["researcher_branch", "researcher_branch"]
    assert [s.arg["sub_topic"] for s in sends] == ["a", "b"]


async def test_researcher_branch_combines_researcher_and_compress(monkeypatch: Any) -> None:
    async def fake_researcher(state: Any, *, client: Any, search_tools: Any, emit: Any,
                               max_tool_calls: int) -> dict[str, Any]:
        return {
            "sub_topic": state["sub_topic"],
            "raw_notes": "some notes",
            "sources": [Source(tool_name="exa", url="https://a.com", title="A", snippet="a")],
        }

    async def fake_compress_research(sub_topic: str, raw_notes: str, *, client: Any, emit: Any) -> str:
        return f"### {sub_topic}\ncompressed"

    monkeypatch.setattr("agentdrops.research.nodes.supervisor.researcher", fake_researcher)
    monkeypatch.setattr(
        "agentdrops.research.nodes.supervisor.compress_research", fake_compress_research
    )

    result = await researcher_branch(
        {"sub_topic": "pricing models"}, client=object(), search_tools=[], emit=AsyncMock(),
        max_tool_calls=8,
    )

    assert result["compressed_notes"] == ["### pricing models\ncompressed"]
    assert len(result["all_sources"]) == 1
    assert result["all_sources"][0].tool_name == "exa"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/research/nodes/test_supervisor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdrops.research.nodes.supervisor'`.

- [ ] **Step 3: Implement the node**

Create `backend/src/agentdrops/research/nodes/supervisor.py`:

```python
from typing import Any

from langgraph.types import Send

from agentdrops.research.llm import run_tool_loop
from agentdrops.research.nodes.compress_research import compress_research
from agentdrops.research.nodes.researcher import researcher
from agentdrops.research.prompts import SUPERVISOR_SYSTEM_PROMPT
from agentdrops.research.state import EventEmitter
from agentdrops.webtools.base import BaseSearchTool

_SUPERVISOR_TOOLS: list[dict[str, Any]] = [
    {
        "name": "conduct_research",
        "description": "Delegate one sub-topic to a sub-researcher for this round.",
        "input_schema": {
            "type": "object",
            "properties": {"sub_topic": {"type": "string"}},
            "required": ["sub_topic"],
        },
    },
    {
        "name": "research_complete",
        "description": "Signal that enough research has been gathered to write the final report.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "think_tool",
        "description": "Record a strategic reflection before deciding the next step.",
        "input_schema": {
            "type": "object",
            "properties": {"reflection": {"type": "string"}},
            "required": ["reflection"],
        },
    },
]

_MAX_PLANNING_TURNS = 6


async def supervisor(
    state: dict[str, Any],
    *,
    client: Any,
    emit: EventEmitter,
    max_concurrent: int,
    max_iterations: int,
) -> dict[str, Any]:
    iteration = state.get("supervisor_iteration", 0) + 1
    await emit("supervisor", "started", f"Planning research round {iteration}",
               payload={"iteration": iteration})

    pending_sub_topics: list[str] = []
    research_complete = False

    async def handler(name: str, input_: dict[str, Any]) -> str:
        nonlocal research_complete
        if name == "conduct_research":
            sub_topic = input_["sub_topic"]
            if len(pending_sub_topics) < max_concurrent:
                pending_sub_topics.append(sub_topic)
            return f"Delegated: {sub_topic}"
        if name == "research_complete":
            research_complete = True
            return "Marked research complete."
        return "Reflection recorded."

    system = SUPERVISOR_SYSTEM_PROMPT.format(
        max_concurrent=max_concurrent, max_iterations=max_iterations
    )
    notes_so_far = "\n".join(state.get("compressed_notes", [])) or "(none yet)"
    user = f"Research brief:\n{state['research_brief']}\n\nCompressed findings so far:\n{notes_so_far}"

    await run_tool_loop(
        client,
        system=system,
        initial_user_message=user,
        tools=_SUPERVISOR_TOOLS,
        tool_handler=handler,
        stop_tool_names={"research_complete"},
        max_iterations=_MAX_PLANNING_TURNS,
    )

    if iteration >= max_iterations:
        research_complete = True

    message = "Research complete" if research_complete else (
        f"Round {iteration}: delegating {len(pending_sub_topics)} sub-topic(s)"
    )
    await emit(
        "supervisor", "completed", message,
        payload={"sub_topics": pending_sub_topics, "research_complete": research_complete},
    )

    return {
        "pending_sub_topics": pending_sub_topics,
        "research_complete": research_complete,
        "supervisor_iteration": iteration,
    }


def route_after_supervisor(state: dict[str, Any]) -> "list[Send] | str":
    if state.get("research_complete") or not state.get("pending_sub_topics"):
        return "final_report_generation"
    return [
        Send("researcher_branch", {"sub_topic": sub_topic})
        for sub_topic in state["pending_sub_topics"]
    ]


async def researcher_branch(
    state: dict[str, Any],
    *,
    client: Any,
    search_tools: list[BaseSearchTool],
    emit: EventEmitter,
    max_tool_calls: int,
) -> dict[str, Any]:
    result = await researcher(
        state, client=client, search_tools=search_tools, emit=emit, max_tool_calls=max_tool_calls
    )
    compressed = await compress_research(
        result["sub_topic"], result["raw_notes"], client=client, emit=emit
    )
    return {"compressed_notes": [compressed], "all_sources": result["sources"]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/research/nodes/test_supervisor.py -v`
Expected: all 9 tests PASS.

- [ ] **Step 5: Run mypy and ruff**

Run: `cd backend && uv run mypy src/agentdrops/research && uv run ruff check src/agentdrops/research tests/unit/research`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/src/agentdrops/research/nodes/supervisor.py backend/tests/unit/research/nodes/test_supervisor.py
git commit -m "feat(backend): add supervisor node with parallel Send-based researcher delegation"
```

---

### Task 11: `call_text` LLM helper and `final_report_generation` node

**Files:**
- Modify: `backend/src/agentdrops/research/llm.py`
- Modify: `backend/tests/unit/research/test_llm.py`
- Create: `backend/src/agentdrops/research/nodes/final_report_generation.py`
- Test: `backend/tests/unit/research/nodes/test_final_report_generation.py`

**Interfaces:**
- Consumes: `_create_message` (existing private helper in `research/llm.py` from Task 6).
- Produces: `async def call_text(client: AnthropicMessagesClient, *, system: str, user: str, model: str = DEFAULT_MODEL, max_tokens: int = 8192) -> str` added to `research/llm.py` (consumed by Task 11's node here and reusable by any future free-text node); `async def final_report_generation(state: dict[str, Any], *, client: Any, emit: EventEmitter) -> dict[str, str]` returning `{"final_report": <markdown>}` (consumed by Task 13's graph assembly).

- [ ] **Step 1: Write the failing `call_text` test**

In `backend/tests/unit/research/test_llm.py`, add (reusing the `_Message`/`_TextBlock`/`_FakeClient` fixtures already defined in that file):

```python
from agentdrops.research.llm import call_text


async def test_call_text_extracts_text_from_response() -> None:
    response = _Message(content=[_TextBlock(type="text", text="# Report\n\nBody text.")], stop_reason="end_turn")
    client = _FakeClient([response])

    result = await call_text(client, system="sys", user="usr")  # type: ignore[arg-type]

    assert result == "# Report\n\nBody text."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/research/test_llm.py::test_call_text_extracts_text_from_response -v`
Expected: FAIL — `ImportError: cannot import name 'call_text'`.

- [ ] **Step 3: Add `call_text` to `research/llm.py`**

Append to `backend/src/agentdrops/research/llm.py` (after `run_tool_loop`):

```python
async def call_text(
    client: AnthropicMessagesClient,
    *,
    system: str,
    user: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 8192,
) -> str:
    response = await _create_message(
        client,
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        tools=[],
    )
    return _extract_text(response.content)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/research/test_llm.py -v`
Expected: all tests, including the new one, PASS.

- [ ] **Step 5: Write the failing node test**

Create `backend/tests/unit/research/nodes/test_final_report_generation.py`:

```python
from typing import Any
from unittest.mock import AsyncMock

from agentdrops.research.nodes.final_report_generation import final_report_generation


async def test_final_report_generation_combines_brief_and_notes(monkeypatch: Any) -> None:
    async def fake_call_text(client: Any, *, system: str, user: str, max_tokens: int) -> str:
        assert "the brief" in user
        assert "### pricing models" in user
        return "# Final Report\n\nBody."

    monkeypatch.setattr(
        "agentdrops.research.nodes.final_report_generation.call_text", fake_call_text
    )
    emit = AsyncMock()

    result = await final_report_generation(
        {"research_brief": "the brief", "compressed_notes": ["### pricing models\nsummary"]},
        client=object(), emit=emit,
    )

    assert result == {"final_report": "# Final Report\n\nBody."}
    assert emit.await_count == 2


async def test_final_report_generation_handles_no_notes(monkeypatch: Any) -> None:
    async def fake_call_text(client: Any, *, system: str, user: str, max_tokens: int) -> str:
        assert "no findings gathered" in user
        return "# Report"

    monkeypatch.setattr(
        "agentdrops.research.nodes.final_report_generation.call_text", fake_call_text
    )

    result = await final_report_generation(
        {"research_brief": "brief", "compressed_notes": []}, client=object(), emit=AsyncMock()
    )

    assert result == {"final_report": "# Report"}
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/research/nodes/test_final_report_generation.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 7: Implement the node**

Create `backend/src/agentdrops/research/nodes/final_report_generation.py`:

```python
from typing import Any

from agentdrops.research.llm import call_text
from agentdrops.research.prompts import FINAL_REPORT_SYSTEM_PROMPT
from agentdrops.research.state import EventEmitter


async def final_report_generation(
    state: dict[str, Any], *, client: Any, emit: EventEmitter
) -> dict[str, str]:
    await emit("final_report_generation", "started", "Writing final report")

    notes = "\n\n".join(state.get("compressed_notes", [])) or "(no findings gathered)"
    user = f"Research brief:\n{state['research_brief']}\n\nCompressed findings:\n{notes}"

    report = await call_text(client, system=FINAL_REPORT_SYSTEM_PROMPT, user=user, max_tokens=8192)

    await emit("final_report_generation", "completed", "Final report ready")
    return {"final_report": report}
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/research/nodes/test_final_report_generation.py -v`
Expected: both tests PASS.

- [ ] **Step 9: Run mypy and ruff**

Run: `cd backend && uv run mypy src/agentdrops/research && uv run ruff check src/agentdrops/research tests/unit/research`
Expected: no errors.

- [ ] **Step 10: Commit**

```bash
git add backend/src/agentdrops/research/llm.py backend/tests/unit/research/test_llm.py backend/src/agentdrops/research/nodes/final_report_generation.py backend/tests/unit/research/nodes/test_final_report_generation.py
git commit -m "feat(backend): add call_text helper and final_report_generation node"
```

---

### Task 12: `idea_refine_generation` node (3 phases)

**Files:**
- Create: `backend/src/agentdrops/idearefine/prompts.py`
- Modify: `backend/src/agentdrops/idearefine/schemas.py`
- Create: `backend/src/agentdrops/idearefine/node.py`
- Test: `backend/tests/unit/idearefine/__init__.py`
- Test: `backend/tests/unit/idearefine/test_node.py`

**Interfaces:**
- Consumes: `call_structured` from Task 6; `EventEmitter` from Task 5; `IdeaOnePagerSchema` from Task 5.
- Produces: `UnderstandExpandOutput`, `EvaluateConvergeOutput` (Pydantic, added to `idearefine/schemas.py`); `async def idea_refine_generation(state: dict[str, Any], *, client: Any, emit: EventEmitter) -> dict[str, Any]` returning `{"idea_onepager": IdeaOnePagerSchema}` (consumed by Task 13's graph assembly, which persists it via Task 3's `RunsRepository.save_research_output`).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/idearefine/__init__.py` (empty).

Create `backend/tests/unit/idearefine/test_node.py`:

```python
from typing import Any
from unittest.mock import AsyncMock

from agentdrops.idearefine.node import idea_refine_generation
from agentdrops.idearefine.schemas import EvaluateConvergeOutput, IdeaOnePagerSchema, UnderstandExpandOutput


async def test_idea_refine_generation_runs_three_phases_in_order(monkeypatch: Any) -> None:
    calls: list[str] = []

    async def fake_call_structured(client: Any, *, system: str, user: str, schema: Any) -> Any:
        if schema is UnderstandExpandOutput:
            calls.append("understand_expand")
            assert "# Final Report" in user
            return UnderstandExpandOutput(
                how_might_we="How might we help users retain notes?",
                idea_variations=["variation A", "variation B"],
                open_questions=["What is willingness to pay?"],
            )
        if schema is EvaluateConvergeOutput:
            calls.append("evaluate_converge")
            assert "How might we help users retain notes?" in user
            return EvaluateConvergeOutput(directions=[])
        if schema is IdeaOnePagerSchema:
            calls.append("sharpen_ship")
            return IdeaOnePagerSchema(
                problem_statement="p", recommended_direction="d", key_assumptions=["a"],
                mvp_scope=["m"], not_doing=["n"], open_questions=["o"],
            )
        raise AssertionError(f"unexpected schema {schema}")

    monkeypatch.setattr("agentdrops.idearefine.node.call_structured", fake_call_structured)
    emit = AsyncMock()

    result = await idea_refine_generation(
        {"final_report": "# Final Report\n\nBody."}, client=object(), emit=emit
    )

    assert calls == ["understand_expand", "evaluate_converge", "sharpen_ship"]
    assert result["idea_onepager"].recommended_direction == "d"
    # started + completed per phase = 6 events
    assert emit.await_count == 6
    phases_emitted = [call.kwargs.get("payload", {}).get("phase") for call in emit.await_args_list]
    assert phases_emitted == [
        "understand_expand", "understand_expand", "evaluate_converge", "evaluate_converge",
        "sharpen_ship", "sharpen_ship",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/idearefine/test_node.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdrops.idearefine.node'`.

- [ ] **Step 3: Write idea-refine prompts**

Create `backend/src/agentdrops/idearefine/prompts.py`:

```python
UNDERSTAND_EXPAND_SYSTEM_PROMPT = """Given the market research report below, restate the \
core opportunity as a "How Might We" statement, generate 5-8 idea variations using distinct \
lenses (inversion, constraint removal, audience shift, combination, simplification, 10x, \
expert lens), and list open questions the research does not resolve."""

EVALUATE_CONVERGE_SYSTEM_PROMPT = """Given the "How Might We" statement and idea variations \
below, cluster the resonant variations into 2-3 concrete directions. For each direction, \
stress-test it on user value, feasibility, and differentiation, and name its hidden \
assumptions."""

SHARPEN_SHIP_SYSTEM_PROMPT = """Given the evaluated directions below, pick the strongest one \
and produce a final one-pager: problem statement, recommended direction, key assumptions to \
validate, MVP scope, a "not doing" list, and open questions."""
```

- [ ] **Step 4: Extend the schemas**

In `backend/src/agentdrops/idearefine/schemas.py`, append after `IdeaOnePagerSchema`:

```python
class UnderstandExpandOutput(BaseModel):
    how_might_we: str
    idea_variations: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class DirectionEvaluation(BaseModel):
    name: str
    user_value: str
    feasibility: str
    differentiation: str
    hidden_assumptions: list[str] = Field(default_factory=list)


class EvaluateConvergeOutput(BaseModel):
    directions: list[DirectionEvaluation] = Field(default_factory=list)
```

- [ ] **Step 5: Implement the node**

Create `backend/src/agentdrops/idearefine/node.py`:

```python
from typing import Any

from agentdrops.idearefine.prompts import (
    EVALUATE_CONVERGE_SYSTEM_PROMPT,
    SHARPEN_SHIP_SYSTEM_PROMPT,
    UNDERSTAND_EXPAND_SYSTEM_PROMPT,
)
from agentdrops.idearefine.schemas import EvaluateConvergeOutput, IdeaOnePagerSchema, UnderstandExpandOutput
from agentdrops.research.llm import call_structured
from agentdrops.research.state import EventEmitter


async def idea_refine_generation(
    state: dict[str, Any], *, client: Any, emit: EventEmitter
) -> dict[str, Any]:
    report = state["final_report"]

    await emit("idea_refine_generation", "started", "Expanding idea variations",
               payload={"phase": "understand_expand"})
    understood = await call_structured(
        client, system=UNDERSTAND_EXPAND_SYSTEM_PROMPT, user=report, schema=UnderstandExpandOutput
    )
    await emit("idea_refine_generation", "completed", "Idea variations generated",
               payload={"phase": "understand_expand"})

    await emit("idea_refine_generation", "started", "Evaluating candidate directions",
               payload={"phase": "evaluate_converge"})
    variations_text = "\n".join(f"- {v}" for v in understood.idea_variations)
    evaluate_user = (
        f"How Might We: {understood.how_might_we}\n\nIdea variations:\n{variations_text}"
    )
    evaluated = await call_structured(
        client, system=EVALUATE_CONVERGE_SYSTEM_PROMPT, user=evaluate_user,
        schema=EvaluateConvergeOutput,
    )
    await emit("idea_refine_generation", "completed", "Directions evaluated",
               payload={"phase": "evaluate_converge"})

    await emit("idea_refine_generation", "started", "Sharpening final recommendation",
               payload={"phase": "sharpen_ship"})
    directions_text = "\n".join(
        f"- {d.name}: value={d.user_value}; feasibility={d.feasibility}; "
        f"differentiation={d.differentiation}; assumptions={d.hidden_assumptions}"
        for d in evaluated.directions
    )
    sharpen_user = f"How Might We: {understood.how_might_we}\n\nEvaluated directions:\n{directions_text}"
    onepager = await call_structured(
        client, system=SHARPEN_SHIP_SYSTEM_PROMPT, user=sharpen_user, schema=IdeaOnePagerSchema
    )
    await emit("idea_refine_generation", "completed", "Idea one-pager ready",
               payload={"phase": "sharpen_ship"})

    return {"idea_onepager": onepager}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/idearefine/test_node.py -v`
Expected: PASS.

- [ ] **Step 7: Run mypy and ruff**

Run: `cd backend && uv run mypy src/agentdrops/idearefine && uv run ruff check src/agentdrops/idearefine tests/unit/idearefine`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add backend/src/agentdrops/idearefine backend/tests/unit/idearefine
git commit -m "feat(backend): add idea_refine_generation node (understand/evaluate/sharpen)"
```

---

### Task 13: Graph assembly (`StateGraph`)

**Files:**
- Create: `backend/src/agentdrops/research/graph.py`
- Test: `backend/tests/unit/research/test_graph.py`

**Interfaces:**
- Consumes: every node from Tasks 7-12 (`write_research_brief`, `supervisor`/`route_after_supervisor`/`researcher_branch`, `final_report_generation`, `idea_refine_generation`); `AgentState` from Task 5.
- Produces: `def build_graph(*, client: Any, search_tools: list[BaseSearchTool], emit: EventEmitter, max_concurrent_research_units: int, max_researcher_iterations: int, max_react_tool_calls: int) -> CompiledStateGraph` — an object with `async def ainvoke(initial_state: dict[str, Any]) -> dict[str, Any]` (consumed by Task 14's `run_research_job`).

**Note on LangGraph API surface:** this task is written against `langgraph>=0.2.60`'s stable `StateGraph`/`add_conditional_edges`/`Send` API. If the installed version's exact signature differs (LangGraph's conditional-edges/`Command` API has evolved across minor versions), consult `python -c "import langgraph; print(langgraph.__version__)"` and the installed package's docstrings before deviating from this task's code — do not guess silently.

- [ ] **Step 1: Write the failing end-to-end graph test**

Create `backend/tests/unit/research/test_graph.py`:

```python
from dataclasses import dataclass
from typing import Any

from agentdrops.research.graph import build_graph


@dataclass
class _ToolUseBlock:
    type: str
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class _TextBlock:
    type: str
    text: str


@dataclass
class _Message:
    content: list[Any]
    stop_reason: str


class _ScriptedMessages:
    def __init__(self, responses: list[_Message]) -> None:
        self._responses = list(responses)

    async def create(self, **kwargs: Any) -> _Message:
        return self._responses.pop(0)


class _ScriptedClient:
    def __init__(self, responses: list[_Message]) -> None:
        self.messages = _ScriptedMessages(responses)


async def test_graph_runs_end_to_end_without_delegating_research() -> None:
    responses = [
        _Message(
            content=[_ToolUseBlock(type="tool_use", id="1", name="emit__researchbriefoutput",
                                    input={"brief": "# Brief"})],
            stop_reason="tool_use",
        ),
        _Message(
            content=[_ToolUseBlock(type="tool_use", id="2", name="research_complete", input={})],
            stop_reason="tool_use",
        ),
        _Message(content=[_TextBlock(type="text", text="# Final Report")], stop_reason="end_turn"),
        _Message(
            content=[_ToolUseBlock(type="tool_use", id="3", name="emit__understandexpandoutput",
                                    input={"how_might_we": "hmw", "idea_variations": [],
                                           "open_questions": []})],
            stop_reason="tool_use",
        ),
        _Message(
            content=[_ToolUseBlock(type="tool_use", id="4", name="emit__evaluateconvergeoutput",
                                    input={"directions": []})],
            stop_reason="tool_use",
        ),
        _Message(
            content=[_ToolUseBlock(
                type="tool_use", id="5", name="emit__ideaonepagerschema",
                input={"problem_statement": "p", "recommended_direction": "d",
                       "key_assumptions": [], "mvp_scope": [], "not_doing": [], "open_questions": []},
            )],
            stop_reason="tool_use",
        ),
    ]
    client = _ScriptedClient(responses)
    events: list[tuple[str, str, str]] = []

    async def emit(node_name: str, event_type: str, message: str,
                    payload: dict[str, Any] | None = None) -> None:
        events.append((node_name, event_type, message))

    graph = build_graph(
        client=client, search_tools=[], emit=emit,
        max_concurrent_research_units=3, max_researcher_iterations=3, max_react_tool_calls=8,
    )

    result = await graph.ainvoke({"topic": "AI note-taking apps", "constraints": None})

    assert result["final_report"] == "# Final Report"
    assert result["idea_onepager"].recommended_direction == "d"
    assert ("write_research_brief", "completed", "Research brief ready") in events
    assert ("supervisor", "completed", "Research complete") in events
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/research/test_graph.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdrops.research.graph'`.

- [ ] **Step 3: Implement graph assembly**

Create `backend/src/agentdrops/research/graph.py`:

```python
from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agentdrops.idearefine.node import idea_refine_generation
from agentdrops.research.nodes.final_report_generation import final_report_generation
from agentdrops.research.nodes.supervisor import researcher_branch, route_after_supervisor, supervisor
from agentdrops.research.nodes.write_research_brief import write_research_brief
from agentdrops.research.state import AgentState, EventEmitter
from agentdrops.webtools.base import BaseSearchTool


def build_graph(
    *,
    client: Any,
    search_tools: list[BaseSearchTool],
    emit: EventEmitter,
    max_concurrent_research_units: int,
    max_researcher_iterations: int,
    max_react_tool_calls: int,
) -> CompiledStateGraph:
    graph: StateGraph = StateGraph(AgentState)

    graph.add_node("write_research_brief", partial(write_research_brief, client=client, emit=emit))
    graph.add_node(
        "supervisor",
        partial(
            supervisor,
            client=client,
            emit=emit,
            max_concurrent=max_concurrent_research_units,
            max_iterations=max_researcher_iterations,
        ),
    )
    graph.add_node(
        "researcher_branch",
        partial(
            researcher_branch,
            client=client,
            search_tools=search_tools,
            emit=emit,
            max_tool_calls=max_react_tool_calls,
        ),
    )
    graph.add_node(
        "final_report_generation", partial(final_report_generation, client=client, emit=emit)
    )
    graph.add_node(
        "idea_refine_generation", partial(idea_refine_generation, client=client, emit=emit)
    )

    graph.add_edge(START, "write_research_brief")
    graph.add_edge("write_research_brief", "supervisor")
    graph.add_conditional_edges(
        "supervisor", route_after_supervisor, ["researcher_branch", "final_report_generation"]
    )
    graph.add_edge("researcher_branch", "supervisor")
    graph.add_edge("final_report_generation", "idea_refine_generation")
    graph.add_edge("idea_refine_generation", END)

    return graph.compile()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/research/test_graph.py -v`
Expected: PASS. If it fails on `add_conditional_edges` or `Send` argument errors, check the installed `langgraph` version's API (see note above) and adjust only the graph-wiring call, not the node functions.

- [ ] **Step 5: Run mypy and ruff**

Run: `cd backend && uv run mypy src/agentdrops/research/graph.py && uv run ruff check src/agentdrops/research/graph.py tests/unit/research/test_graph.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/src/agentdrops/research/graph.py backend/tests/unit/research/test_graph.py
git commit -m "feat(backend): assemble the LangGraph research StateGraph"
```

---

### Task 14: Redis event publisher and arq worker (`run_research_job`)

**Files:**
- Create: `backend/src/agentdrops/worker/__init__.py`
- Create: `backend/src/agentdrops/worker/events.py`
- Create: `backend/src/agentdrops/worker/tasks.py`
- Create: `backend/src/agentdrops/worker/main.py`
- Test: `backend/tests/unit/worker/__init__.py`
- Test: `backend/tests/unit/worker/test_events.py`
- Test: `backend/tests/unit/worker/test_tasks.py`

**Interfaces:**
- Consumes: `build_graph` from Task 13; `build_search_tools` from existing `webtools/registry.py`; `RunsRepository`, `EventsRepository`, `SourcesRepository` from Task 3; `Source` from Task 5.
- Produces: `class RedisEventPublisher` with `async def publish(run_id: str, node_name: str, event_type: str, message: str, payload: dict[str, Any] | None = None) -> None` publishing JSON to channel `f"run:{run_id}:events"` (consumed by Task 15's SSE route, which subscribes to the same channel naming convention); `async def run_research_job(ctx: dict[str, Any], run_id: str) -> None` (the arq task, registered in `WorkerSettings.functions`, consumed by Task 4's `POST /runs` via `arq_pool.enqueue_job("run_research_job", ...)`); `class WorkerSettings` with `functions`, `on_startup`, `on_shutdown`, `redis_settings` (arq entrypoint used by `docker-compose.yml`'s `worker` service from Task 1).

- [ ] **Step 1: Write the failing publisher test**

Create `backend/tests/unit/worker/__init__.py` (empty).

Create `backend/tests/unit/worker/test_events.py`:

```python
import json
from collections.abc import AsyncIterator

import pytest
from testcontainers.redis import RedisContainer

from agentdrops.worker.events import RedisEventPublisher


@pytest.fixture
async def redis_url() -> AsyncIterator[str]:
    with RedisContainer("redis:7-alpine") as container:
        yield f"redis://{container.get_container_host_ip()}:{container.get_exposed_port(6379)}/0"


async def test_publish_sends_json_payload_to_run_channel(redis_url: str) -> None:
    import redis.asyncio as redis_asyncio

    publisher = RedisEventPublisher(redis_url)
    subscriber = redis_asyncio.from_url(redis_url)
    pubsub = subscriber.pubsub()
    await pubsub.subscribe("run:abc123:events")
    await pubsub.get_message(timeout=1)  # discard the subscribe confirmation

    await publisher.publish("abc123", "supervisor", "started", "Planning", payload={"iteration": 1})

    message = await pubsub.get_message(timeout=2)
    assert message is not None
    data = json.loads(message["data"])
    assert data == {
        "node_name": "supervisor", "event_type": "started", "message": "Planning",
        "payload": {"iteration": 1},
    }

    await pubsub.unsubscribe()
    await subscriber.aclose()
    await publisher.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/worker/test_events.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdrops.worker'`.

- [ ] **Step 3: Implement the publisher**

Create `backend/src/agentdrops/worker/__init__.py` (empty).

Create `backend/src/agentdrops/worker/events.py`:

```python
import json
from typing import Any

import redis.asyncio as redis


class RedisEventPublisher:
    def __init__(self, redis_url: str) -> None:
        self._redis = redis.from_url(redis_url)

    def channel_for(self, run_id: str) -> str:
        return f"run:{run_id}:events"

    async def publish(
        self,
        run_id: str,
        node_name: str,
        event_type: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        data = json.dumps(
            {"node_name": node_name, "event_type": event_type, "message": message, "payload": payload}
        )
        await self._redis.publish(self.channel_for(run_id), data)

    async def close(self) -> None:
        await self._redis.aclose()
```

- [ ] **Step 4: Run publisher test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/worker/test_events.py -v`
Expected: PASS.

- [ ] **Step 5: Write the failing task test**

Create `backend/tests/unit/worker/test_tasks.py`:

```python
import uuid
from typing import Any

from agentdrops.research.state import Source
from agentdrops.worker.tasks import run_research_job


class _StubSettings:
    max_concurrent_research_units = 3
    max_researcher_iterations = 3
    max_react_tool_calls = 8


class _StubOnePager:
    def model_dump(self) -> dict[str, Any]:
        return {"problem_statement": "p"}


class _FakeRun:
    def __init__(self, run_id: uuid.UUID, topic: str, constraints: str | None) -> None:
        self.id = run_id
        self.topic = topic
        self.constraints = constraints


class _FakeRunsRepo:
    def __init__(self, run: _FakeRun) -> None:
        self._run = run
        self.status_calls: list[tuple[uuid.UUID, str, str | None]] = []
        self.saved: dict[str, Any] = {}

    async def get(self, run_id: uuid.UUID) -> _FakeRun | None:
        return self._run if run_id == self._run.id else None

    async def update_status(
        self, run_id: uuid.UUID, status: str, *, error: str | None = None
    ) -> None:
        self.status_calls.append((run_id, status, error))

    async def save_research_output(self, run_id: uuid.UUID, **kwargs: Any) -> None:
        self.saved = kwargs


class _FakeSourcesRepo:
    def __init__(self) -> None:
        self.added: list[dict[str, Any]] = []

    async def add_many(self, run_id: uuid.UUID, sources: list[dict[str, Any]]) -> None:
        self.added = sources


class _FakeEventsRepo:
    async def append(self, *args: Any, **kwargs: Any) -> None:
        return None


class _FakePublisher:
    async def publish(self, *args: Any, **kwargs: Any) -> None:
        return None


def _base_ctx(runs_repo: Any, sources_repo: Any) -> dict[str, Any]:
    return {
        "settings": _StubSettings(),
        "runs_repo": runs_repo,
        "events_repo": _FakeEventsRepo(),
        "sources_repo": sources_repo,
        "event_publisher": _FakePublisher(),
        "http_client": object(),
        "anthropic_client": object(),
    }


async def test_run_research_job_saves_output_and_marks_completed(monkeypatch: Any) -> None:
    run_id = uuid.uuid4()
    runs_repo = _FakeRunsRepo(_FakeRun(run_id, "AI note-taking apps", None))
    sources_repo = _FakeSourcesRepo()

    class _FakeGraph:
        @staticmethod
        async def ainvoke(initial_state: dict[str, Any]) -> dict[str, Any]:
            return {
                "research_brief": "brief",
                "final_report": "report",
                "idea_onepager": _StubOnePager(),
                "all_sources": [Source(tool_name="exa", url="https://a.com", title="A", snippet="a")],
            }

    monkeypatch.setattr("agentdrops.worker.tasks.build_search_tools", lambda settings, client: [])
    monkeypatch.setattr("agentdrops.worker.tasks.build_graph", lambda **kwargs: _FakeGraph())

    await run_research_job(_base_ctx(runs_repo, sources_repo), str(run_id))

    assert runs_repo.status_calls[0] == (run_id, "running", None)
    assert runs_repo.status_calls[-1] == (run_id, "completed", None)
    assert runs_repo.saved["final_report"] == "report"
    assert sources_repo.added == [
        {"tool_name": "exa", "url": "https://a.com", "title": "A", "snippet": "a"}
    ]


async def test_run_research_job_marks_failed_on_exception(monkeypatch: Any) -> None:
    run_id = uuid.uuid4()
    runs_repo = _FakeRunsRepo(_FakeRun(run_id, "topic", None))

    class _FailingGraph:
        @staticmethod
        async def ainvoke(initial_state: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("boom")

    monkeypatch.setattr("agentdrops.worker.tasks.build_search_tools", lambda settings, client: [])
    monkeypatch.setattr("agentdrops.worker.tasks.build_graph", lambda **kwargs: _FailingGraph())

    await run_research_job(_base_ctx(runs_repo, _FakeSourcesRepo()), str(run_id))

    assert runs_repo.status_calls[-1] == (run_id, "failed", "boom")


async def test_run_research_job_returns_early_if_run_missing() -> None:
    runs_repo = _FakeRunsRepo(_FakeRun(uuid.uuid4(), "topic", None))

    await run_research_job(_base_ctx(runs_repo, _FakeSourcesRepo()), str(uuid.uuid4()))

    assert runs_repo.status_calls == []
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/worker/test_tasks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdrops.worker.tasks'`.

- [ ] **Step 7: Implement the task**

Create `backend/src/agentdrops/worker/tasks.py`:

```python
import uuid
from typing import Any

from agentdrops.research.graph import build_graph
from agentdrops.research.state import EventEmitter, Source
from agentdrops.webtools.registry import build_search_tools


def _make_emitter(
    run_id: uuid.UUID, events_repo: Any, publisher: Any
) -> EventEmitter:
    async def emit(
        node_name: str, event_type: str, message: str, payload: dict[str, Any] | None = None
    ) -> None:
        await events_repo.append(run_id, node_name, event_type, message, payload)
        await publisher.publish(str(run_id), node_name, event_type, message, payload)

    return emit


async def run_research_job(ctx: dict[str, Any], run_id: str) -> None:
    settings = ctx["settings"]
    runs_repo = ctx["runs_repo"]
    events_repo = ctx["events_repo"]
    sources_repo = ctx["sources_repo"]
    publisher = ctx["event_publisher"]
    http_client = ctx["http_client"]
    anthropic_client = ctx["anthropic_client"]

    run_uuid = uuid.UUID(run_id)
    run = await runs_repo.get(run_uuid)
    if run is None:
        return

    await runs_repo.update_status(run_uuid, "running")
    emit = _make_emitter(run_uuid, events_repo, publisher)
    search_tools = build_search_tools(settings, http_client)

    graph = build_graph(
        client=anthropic_client,
        search_tools=search_tools,
        emit=emit,
        max_concurrent_research_units=settings.max_concurrent_research_units,
        max_researcher_iterations=settings.max_researcher_iterations,
        max_react_tool_calls=settings.max_react_tool_calls,
    )

    try:
        result = await graph.ainvoke({"topic": run.topic, "constraints": run.constraints})
    except Exception as exc:  # noqa: BLE001 - persisted as a failed run, not re-raised
        await runs_repo.update_status(run_uuid, "failed", error=str(exc))
        await emit("supervisor", "error", f"Run failed: {exc}")
        return

    idea_onepager = result.get("idea_onepager")
    await runs_repo.save_research_output(
        run_uuid,
        research_brief=result.get("research_brief"),
        final_report=result.get("final_report"),
        idea_onepager=idea_onepager.model_dump() if idea_onepager is not None else None,
    )

    all_sources: list[Source] = result.get("all_sources", [])
    if all_sources:
        await sources_repo.add_many(
            run_uuid,
            [
                {"tool_name": s.tool_name, "url": s.url, "title": s.title, "snippet": s.snippet}
                for s in all_sources
            ],
        )

    await runs_repo.update_status(run_uuid, "completed")
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/worker/test_tasks.py -v`
Expected: all 3 tests PASS.

- [ ] **Step 9: Write the worker entrypoint**

Create `backend/src/agentdrops/worker/main.py`:

```python
from typing import Any

import anthropic
import httpx
from arq.connections import RedisSettings

from agentdrops.config import get_settings
from agentdrops.storage.postgres.repositories.events import EventsRepository
from agentdrops.storage.postgres.repositories.exports import ExportsRepository
from agentdrops.storage.postgres.repositories.runs import RunsRepository
from agentdrops.storage.postgres.repositories.sources import SourcesRepository
from agentdrops.storage.postgres.session import create_engine, create_session_factory
from agentdrops.worker.events import RedisEventPublisher
from agentdrops.worker.tasks import run_research_job


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    ctx["settings"] = settings
    ctx["_engine"] = engine
    ctx["runs_repo"] = RunsRepository(session_factory)
    ctx["events_repo"] = EventsRepository(session_factory)
    ctx["sources_repo"] = SourcesRepository(session_factory)
    ctx["exports_repo"] = ExportsRepository(session_factory)
    ctx["event_publisher"] = RedisEventPublisher(settings.redis_url)
    ctx["http_client"] = httpx.AsyncClient(timeout=30.0)
    ctx["anthropic_client"] = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["http_client"].aclose()
    await ctx["event_publisher"].close()
    await ctx["_engine"].dispose()


class WorkerSettings:
    functions = [run_research_job]
    on_startup = staticmethod(startup)
    on_shutdown = staticmethod(shutdown)
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
```

- [ ] **Step 10: Run mypy and ruff**

Run: `cd backend && uv run mypy src/agentdrops/worker && uv run ruff check src/agentdrops/worker tests/unit/worker`
Expected: no errors.

- [ ] **Step 11: Commit**

```bash
git add backend/src/agentdrops/worker backend/tests/unit/worker
git commit -m "feat(backend): add Redis event publisher and arq run_research_job worker"
```

---

### Task 15: SSE `GET /runs/{id}/events` route

**Files:**
- Create: `backend/src/agentdrops/api/routes/events.py`
- Modify: `backend/src/agentdrops/api/app.py`
- Test: `backend/tests/integration/api/test_events_route.py`

**Interfaces:**
- Consumes: `EventsRepository` from Task 3; `RedisEventPublisher`'s channel naming convention (`f"run:{run_id}:events"`) from Task 14 — this route subscribes to the same channel a running worker publishes to.
- Produces: registers `GET /runs/{run_id}/events` on the app returned by `create_app()`, streaming Server-Sent Events matching `docs/ui-builder-system-prompt.md` §4's event shape exactly (`node_name`, `event_type`, `message`, `payload`, `created_at`).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/integration/api/test_events_route.py`:

```python
import asyncio
import json
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.redis import RedisContainer

from agentdrops.api.deps import get_events_repository
from agentdrops.api.routes.events import router as events_router
from agentdrops.storage.postgres.repositories.events import EventsRepository
from agentdrops.storage.postgres.repositories.runs import RunsRepository
from agentdrops.worker.events import RedisEventPublisher


@pytest.fixture(scope="module")
def redis_url() -> Any:
    with RedisContainer("redis:7-alpine") as container:
        yield f"redis://{container.get_container_host_ip()}:{container.get_exposed_port(6379)}/0"


@pytest.fixture
async def events_client(
    session_factory: async_sessionmaker[AsyncSession], redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> Any:
    monkeypatch.setenv("REDIS_URL", redis_url)
    from agentdrops.config import get_settings

    get_settings.cache_clear()

    app = FastAPI()
    app.include_router(events_router)
    app.dependency_overrides[get_events_repository] = lambda: EventsRepository(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    get_settings.cache_clear()


async def test_events_route_replays_and_terminates_on_terminal_event(
    events_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    runs_repo = RunsRepository(session_factory)
    events_repo = EventsRepository(session_factory)
    run = await runs_repo.create(topic="topic", constraints=None)
    await events_repo.append(run.id, "write_research_brief", "started", "Starting")
    await events_repo.append(
        run.id, "idea_refine_generation", "completed", "Idea one-pager ready",
        payload={"phase": "sharpen_ship"},
    )

    async with events_client.stream("GET", f"/runs/{run.id}/events") as response:
        lines = [line async for line in response.aiter_lines() if line.startswith("data:")]

    payloads = [json.loads(line.removeprefix("data:").strip()) for line in lines]
    assert payloads[0]["node_name"] == "write_research_brief"
    assert payloads[-1]["node_name"] == "idea_refine_generation"
    assert payloads[-1]["event_type"] == "completed"


async def test_events_route_live_tails_redis_after_replay(
    events_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], redis_url: str
) -> None:
    runs_repo = RunsRepository(session_factory)
    events_repo = EventsRepository(session_factory)
    run = await runs_repo.create(topic="topic", constraints=None)
    await events_repo.append(run.id, "write_research_brief", "started", "Starting")

    async def publish_soon() -> None:
        await asyncio.sleep(0.3)
        publisher = RedisEventPublisher(redis_url)
        await publisher.publish(str(run.id), "idea_refine_generation", "completed", "Done")
        await publisher.close()

    publish_task = asyncio.create_task(publish_soon())
    try:
        async with events_client.stream("GET", f"/runs/{run.id}/events") as response:
            lines = [line async for line in response.aiter_lines() if line.startswith("data:")]
    finally:
        await publish_task

    payloads = [json.loads(line.removeprefix("data:").strip()) for line in lines]
    assert payloads[0]["node_name"] == "write_research_brief"
    assert payloads[-1] == {
        "node_name": "idea_refine_generation", "event_type": "completed", "message": "Done",
        "payload": None,
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/integration/api/test_events_route.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdrops.api.routes.events'`.

- [ ] **Step 3: Implement the route**

Create `backend/src/agentdrops/api/routes/events.py`:

```python
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

import redis.asyncio as redis
from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from agentdrops.api.deps import get_events_repository
from agentdrops.config import get_settings
from agentdrops.storage.postgres.repositories.events import EventsRepository

router = APIRouter(prefix="/runs", tags=["events"])

_TERMINAL_NODE = "idea_refine_generation"


def _is_terminal(node_name: str, event_type: str) -> bool:
    return event_type == "error" or (node_name == _TERMINAL_NODE and event_type == "completed")


async def _event_stream(
    run_id: uuid.UUID, events_repo: EventsRepository, redis_url: str
) -> AsyncIterator[dict[str, str]]:
    for event in await events_repo.list_for_run(run_id):
        yield {
            "event": "message",
            "data": json.dumps(
                {
                    "node_name": event.node_name,
                    "event_type": event.event_type,
                    "message": event.message,
                    "payload": event.payload,
                    "created_at": event.created_at.isoformat(),
                }
            ),
        }
        if _is_terminal(event.node_name, event.event_type):
            return

    client = redis.from_url(redis_url)
    pubsub = client.pubsub()
    await pubsub.subscribe(f"run:{run_id}:events")
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            payload = json.loads(message["data"])
            yield {"event": "message", "data": json.dumps(payload)}
            if _is_terminal(payload["node_name"], payload["event_type"]):
                break
    finally:
        await pubsub.unsubscribe()
        await client.aclose()


@router.get("/{run_id}/events")
async def stream_events(
    run_id: uuid.UUID,
    events_repo: Annotated[EventsRepository, Depends(get_events_repository)],
) -> EventSourceResponse:
    settings = get_settings()
    return EventSourceResponse(_event_stream(run_id, events_repo, settings.redis_url))
```

- [ ] **Step 4: Register the router**

In `backend/src/agentdrops/api/app.py`, add the import and registration:

```python
from agentdrops.api.routes.events import router as events_router
```

And after `app.include_router(runs_router)`:

```python
    app.include_router(events_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/integration/api/test_events_route.py -v`
Expected: both tests PASS.

- [ ] **Step 6: Run mypy and ruff**

Run: `cd backend && uv run mypy src/agentdrops/api && uv run ruff check src/agentdrops/api tests/integration/api`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add backend/src/agentdrops/api/routes/events.py backend/src/agentdrops/api/app.py backend/tests/integration/api/test_events_route.py
git commit -m "feat(backend): add SSE GET /runs/{id}/events route with Postgres replay + Redis live-tail"
```

---

### Task 16: PDF/XLSX export generation and export routes

**Files:**
- Create: `backend/src/agentdrops/exports/__init__.py`
- Create: `backend/src/agentdrops/exports/pdf.py`
- Create: `backend/src/agentdrops/exports/xlsx.py`
- Create: `backend/src/agentdrops/storage/minio_client.py`
- Create: `backend/src/agentdrops/api/schemas/exports.py`
- Create: `backend/src/agentdrops/api/routes/exports.py`
- Modify: `backend/src/agentdrops/api/app.py`
- Modify: `backend/src/agentdrops/worker/tasks.py`
- Modify: `backend/src/agentdrops/worker/main.py`
- Test: `backend/tests/unit/exports/__init__.py`
- Test: `backend/tests/unit/exports/test_pdf.py`
- Test: `backend/tests/unit/exports/test_xlsx.py`
- Test: `backend/tests/integration/api/test_export_routes.py`

**Interfaces:**
- Consumes: `ExportsRepository`, `RunsRepository`, `SourcesRepository` from Task 3; `RunModel`, `SourceModel` from Task 2.
- Produces: `render_report_pdf(run: RunModel, sources: list[SourceModel]) -> bytes` (WeasyPrint); `render_report_xlsx(run: RunModel, sources: list[SourceModel]) -> bytes` (openpyxl); `class MinioClient` with `def put_object(key: str, data: bytes, content_type: str) -> None` and `def presigned_url(key: str, expires_seconds: int = 3600) -> str`; `async def generate_export_job(ctx: dict[str, Any], run_id: str, export_id: str, format: str) -> None` (arq task registered alongside `run_research_job`); `POST /runs/{run_id}/export` and `GET /runs/{run_id}/export/{format}` routes matching `docs/ui-builder-system-prompt.md` §4 exactly.

- [ ] **Step 1: Write the failing PDF/XLSX rendering tests**

Create `backend/tests/unit/exports/__init__.py` (empty).

Create `backend/tests/unit/exports/test_pdf.py`:

```python
import uuid
from datetime import UTC, datetime

from agentdrops.exports.pdf import render_report_pdf
from agentdrops.storage.postgres.models import RunModel, SourceModel


def test_render_report_pdf_produces_nonempty_pdf_bytes() -> None:
    run = RunModel(
        id=uuid.uuid4(), topic="AI note-taking apps", status="completed",
        final_report="# Report\n\nSome **bold** findings.",
        idea_onepager={
            "problem_statement": "p", "recommended_direction": "d", "key_assumptions": ["a"],
            "mvp_scope": ["m"], "not_doing": ["n"], "open_questions": ["o"],
        },
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    source = SourceModel(
        id=uuid.uuid4(), run_id=run.id, tool_name="exa", url="https://a.com", title="A",
        snippet="snippet", retrieved_at=datetime.now(UTC),
    )

    pdf_bytes = render_report_pdf(run, [source])

    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 500
```

Create `backend/tests/unit/exports/test_xlsx.py`:

```python
import uuid
from datetime import UTC, datetime
from io import BytesIO

import openpyxl

from agentdrops.exports.xlsx import render_report_xlsx
from agentdrops.storage.postgres.models import RunModel, SourceModel


def test_render_report_xlsx_produces_workbook_with_expected_sheets() -> None:
    run = RunModel(
        id=uuid.uuid4(), topic="AI note-taking apps", status="completed",
        final_report="# Report",
        idea_onepager={
            "problem_statement": "p", "recommended_direction": "d",
            "key_assumptions": ["assumption 1"], "mvp_scope": ["scope 1"],
            "not_doing": ["not this"], "open_questions": ["question 1"],
        },
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    source = SourceModel(
        id=uuid.uuid4(), run_id=run.id, tool_name="reddit", url="https://b.com", title="B",
        snippet="s", retrieved_at=datetime.now(UTC),
    )

    xlsx_bytes = render_report_xlsx(run, [source])

    workbook = openpyxl.load_workbook(BytesIO(xlsx_bytes))
    assert set(workbook.sheetnames) == {"Report", "Sources", "Idea One-Pager"}
    sources_sheet = workbook["Sources"]
    assert sources_sheet.cell(row=2, column=1).value == "reddit"
    onepager_sheet = workbook["Idea One-Pager"]
    values = [row[0].value for row in onepager_sheet.iter_rows(min_col=2, max_col=2)]
    assert "assumption 1" in values
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/exports -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdrops.exports'`.

- [ ] **Step 3: Implement PDF rendering**

Create `backend/src/agentdrops/exports/__init__.py` (empty).

Create `backend/src/agentdrops/exports/pdf.py`:

```python
import html

import markdown
from weasyprint import HTML

from agentdrops.storage.postgres.models import RunModel, SourceModel

_STYLE = """
<style>
  body { font-family: sans-serif; line-height: 1.5; }
  h1, h2, h3 { color: #111; }
  .sources li { margin-bottom: 0.5em; }
</style>
"""


def render_report_pdf(run: RunModel, sources: list[SourceModel]) -> bytes:
    report_html = markdown.markdown(run.final_report or "")
    onepager = run.idea_onepager or {}

    onepager_html = f"""
    <h2>Idea One-Pager</h2>
    <p><strong>Problem statement:</strong> {html.escape(onepager.get("problem_statement", ""))}</p>
    <p><strong>Recommended direction:</strong> {html.escape(onepager.get("recommended_direction", ""))}</p>
    <h3>Key assumptions</h3><ul>{"".join(f"<li>{html.escape(a)}</li>" for a in onepager.get("key_assumptions", []))}</ul>
    <h3>MVP scope</h3><ul>{"".join(f"<li>{html.escape(m)}</li>" for m in onepager.get("mvp_scope", []))}</ul>
    <h3>Not doing</h3><ul>{"".join(f"<li>{html.escape(n)}</li>" for n in onepager.get("not_doing", []))}</ul>
    <h3>Open questions</h3><ul>{"".join(f"<li>{html.escape(q)}</li>" for q in onepager.get("open_questions", []))}</ul>
    """

    sources_html = "<h2>Sources</h2><ul class='sources'>" + "".join(
        f'<li><a href="{html.escape(s.url)}">{html.escape(s.title)}</a> ({html.escape(s.tool_name)})</li>'
        for s in sources
    ) + "</ul>"

    full_html = f"<html><head>{_STYLE}</head><body><h1>{html.escape(run.topic)}</h1>{report_html}{onepager_html}{sources_html}</body></html>"
    result: bytes = HTML(string=full_html).write_pdf()
    return result
```

- [ ] **Step 4: Add the `markdown` dependency**

In `backend/pyproject.toml`, add to `[project] dependencies`:

```toml
    "markdown>=3.6",
```

Run: `cd backend && uv sync --all-extras`

- [ ] **Step 5: Implement XLSX rendering**

Create `backend/src/agentdrops/exports/xlsx.py`:

```python
from io import BytesIO

import openpyxl

from agentdrops.storage.postgres.models import RunModel, SourceModel


def render_report_xlsx(run: RunModel, sources: list[SourceModel]) -> bytes:
    workbook = openpyxl.Workbook()

    report_sheet = workbook.active
    report_sheet.title = "Report"
    report_sheet["A1"] = run.topic
    for i, line in enumerate((run.final_report or "").splitlines(), start=3):
        report_sheet.cell(row=i, column=1, value=line)

    sources_sheet = workbook.create_sheet("Sources")
    sources_sheet.append(["Tool", "Title", "URL", "Snippet"])
    for source in sources:
        sources_sheet.append([source.tool_name, source.title, source.url, source.snippet])

    onepager_sheet = workbook.create_sheet("Idea One-Pager")
    onepager = run.idea_onepager or {}
    onepager_sheet.append(["Problem statement", onepager.get("problem_statement", "")])
    onepager_sheet.append(["Recommended direction", onepager.get("recommended_direction", "")])
    for label, key in [
        ("Key assumption", "key_assumptions"),
        ("MVP scope item", "mvp_scope"),
        ("Not doing", "not_doing"),
        ("Open question", "open_questions"),
    ]:
        for item in onepager.get(key, []):
            onepager_sheet.append([label, item])

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
```

- [ ] **Step 6: Run rendering tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/exports -v`
Expected: both tests PASS. (WeasyPrint requires system libraries — already installed in `backend/Dockerfile` from Task 1; if running locally outside Docker, install `pango`/`cairo` per the WeasyPrint docs for your OS.)

- [ ] **Step 7: Implement the MinIO client**

Create `backend/src/agentdrops/storage/minio_client.py`:

```python
from datetime import timedelta
from io import BytesIO

from minio import Minio

_EXPORTS_BUCKET = "exports"


class MinioClient:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, *, secure: bool = False) -> None:
        self._client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        if not self._client.bucket_exists(_EXPORTS_BUCKET):
            self._client.make_bucket(_EXPORTS_BUCKET)

    def put_object(self, key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(
            _EXPORTS_BUCKET, key, BytesIO(data), length=len(data), content_type=content_type
        )

    def presigned_url(self, key: str, expires_seconds: int = 3600) -> str:
        url: str = self._client.presigned_get_object(
            _EXPORTS_BUCKET, key, expires=timedelta(seconds=expires_seconds)
        )
        return url
```

- [ ] **Step 8: Write export schemas and routes**

Create `backend/src/agentdrops/api/schemas/exports.py`:

```python
from typing import Literal

from pydantic import BaseModel

ExportFormat = Literal["pdf", "xlsx"]


class ExportCreateRequest(BaseModel):
    format: ExportFormat


class ExportCreateResponse(BaseModel):
    export_id: str
```

Create `backend/src/agentdrops/api/routes/exports.py`:

```python
import uuid
from typing import Annotated

from arq import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Response

from agentdrops.api.deps import get_arq_pool, get_exports_repository
from agentdrops.api.schemas.exports import ExportCreateRequest, ExportCreateResponse
from agentdrops.storage.postgres.repositories.exports import ExportsRepository

router = APIRouter(prefix="/runs", tags=["exports"])


@router.post("/{run_id}/export", response_model=ExportCreateResponse, status_code=201)
async def create_export(
    run_id: uuid.UUID,
    body: ExportCreateRequest,
    exports_repo: Annotated[ExportsRepository, Depends(get_exports_repository)],
    arq_pool: Annotated[ArqRedis, Depends(get_arq_pool)],
) -> ExportCreateResponse:
    export = await exports_repo.create(run_id, body.format)
    await arq_pool.enqueue_job(
        "generate_export_job", str(run_id), str(export.id), body.format
    )
    return ExportCreateResponse(export_id=str(export.id))


@router.get("/{run_id}/export/{format}")
async def get_export(
    run_id: uuid.UUID,
    format: str,
    exports_repo: Annotated[ExportsRepository, Depends(get_exports_repository)],
) -> Response:
    export = await exports_repo.get(run_id, format)
    if export is None:
        raise HTTPException(status_code=404, detail="Export not found")
    if export.status == "generating":
        return Response(status_code=202, content='{"status": "generating"}',
                         media_type="application/json")
    if export.status == "failed":
        raise HTTPException(status_code=500, detail="Export generation failed")

    from agentdrops.config import get_settings
    from agentdrops.storage.minio_client import MinioClient

    settings = get_settings()
    minio_client = MinioClient(
        settings.minio_endpoint, settings.minio_access_key, settings.minio_secret_key
    )
    url = minio_client.presigned_url(export.minio_key)
    return Response(status_code=303, headers={"Location": url})
```

- [ ] **Step 9: Register the export router**

In `backend/src/agentdrops/api/app.py`, add the import and registration:

```python
from agentdrops.api.routes.exports import router as exports_router
```

And after `app.include_router(events_router)`:

```python
    app.include_router(exports_router)
```

- [ ] **Step 10: Implement the export worker task**

In `backend/src/agentdrops/worker/tasks.py`, add after `run_research_job`:

```python
import uuid as _uuid

from agentdrops.exports.pdf import render_report_pdf
from agentdrops.exports.xlsx import render_report_xlsx


async def generate_export_job(ctx: dict[str, Any], run_id: str, export_id: str, format: str) -> None:
    runs_repo = ctx["runs_repo"]
    sources_repo = ctx["sources_repo"]
    exports_repo = ctx["exports_repo"]
    minio_client = ctx["minio_client"]

    run_uuid = _uuid.UUID(run_id)
    export_uuid = _uuid.UUID(export_id)

    run = await runs_repo.get(run_uuid)
    if run is None:
        await exports_repo.mark_failed(export_uuid)
        return

    sources = await sources_repo.list_for_run(run_uuid)

    try:
        if format == "pdf":
            data = render_report_pdf(run, sources)
            content_type = "application/pdf"
        else:
            data = render_report_xlsx(run, sources)
            content_type = (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        key = f"{run_id}/report.{format}"
        minio_client.put_object(key, data, content_type)
        await exports_repo.mark_ready(export_uuid, key)
    except Exception:  # noqa: BLE001 - export failures are isolated to the exports row
        await exports_repo.mark_failed(export_uuid)
```

Move the top-of-file-style imports (`render_report_pdf`, `render_report_xlsx`, `uuid as _uuid`) up to the existing `import` block at the top of `worker/tasks.py` instead of inline, per standard module layout — the inline placement above is only to show what's added.

- [ ] **Step 11: Wire MinIO client and export job into the worker**

In `backend/src/agentdrops/worker/main.py`:
- Add imports: `from agentdrops.storage.minio_client import MinioClient` and `from agentdrops.worker.tasks import generate_export_job, run_research_job` (replacing the old single-name import).
- In `startup`, add: `ctx["minio_client"] = MinioClient(settings.minio_endpoint, settings.minio_access_key, settings.minio_secret_key)`.
- In `WorkerSettings`, change `functions = [run_research_job]` to `functions = [run_research_job, generate_export_job]`.

- [ ] **Step 12: Write the failing export-route integration test**

Create `backend/tests/integration/api/test_export_routes.py`. This file builds its own small FastAPI app registering `exports_router` (the shared `conftest.py` from Task 4 only registers `runs_router`), reusing the `session_factory` and `fake_arq_pool` fixtures already defined in `tests/integration/api/conftest.py`:

```python
import uuid

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentdrops.api.deps import get_arq_pool, get_exports_repository
from agentdrops.api.routes.exports import router as exports_router
from agentdrops.storage.postgres.repositories.exports import ExportsRepository
from agentdrops.storage.postgres.repositories.runs import RunsRepository


async def _exports_client(session_factory, fake_arq_pool):  # type: ignore[no-untyped-def]
    app = FastAPI()
    app.include_router(exports_router)
    app.dependency_overrides[get_exports_repository] = lambda: ExportsRepository(session_factory)
    app.dependency_overrides[get_arq_pool] = lambda: fake_arq_pool
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_create_export_enqueues_job_and_returns_201(
    session_factory: async_sessionmaker[AsyncSession], fake_arq_pool
) -> None:  # type: ignore[no-untyped-def]
    runs_repo = RunsRepository(session_factory)
    run = await runs_repo.create(topic="topic", constraints=None)

    async with await _exports_client(session_factory, fake_arq_pool) as client:
        response = await client.post(f"/runs/{run.id}/export", json={"format": "pdf"})

    assert response.status_code == 201
    export_id = response.json()["export_id"]
    assert fake_arq_pool.enqueued == [
        ("generate_export_job", (str(run.id), export_id, "pdf"))
    ]


async def test_get_export_returns_202_while_generating(
    session_factory: async_sessionmaker[AsyncSession], fake_arq_pool
) -> None:  # type: ignore[no-untyped-def]
    runs_repo = RunsRepository(session_factory)
    exports_repo = ExportsRepository(session_factory)
    run = await runs_repo.create(topic="topic", constraints=None)
    await exports_repo.create(run.id, "pdf")

    async with await _exports_client(session_factory, fake_arq_pool) as client:
        response = await client.get(f"/runs/{run.id}/export/pdf")

    assert response.status_code == 202
    assert response.json() == {"status": "generating"}


async def test_get_export_returns_404_when_no_export_exists(
    session_factory: async_sessionmaker[AsyncSession], fake_arq_pool
) -> None:  # type: ignore[no-untyped-def]
    async with await _exports_client(session_factory, fake_arq_pool) as client:
        response = await client.get(f"/runs/{uuid.uuid4()}/export/pdf")

    assert response.status_code == 404
```

- [ ] **Step 13: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/integration/api/test_export_routes.py tests/unit/exports -v`
Expected: all tests PASS.

- [ ] **Step 14: Run mypy and ruff**

Run: `cd backend && uv run mypy src/agentdrops/exports src/agentdrops/storage/minio_client.py src/agentdrops/api src/agentdrops/worker && uv run ruff check src/agentdrops/exports src/agentdrops/storage/minio_client.py src/agentdrops/api src/agentdrops/worker tests/unit/exports tests/integration/api/test_export_routes.py`
Expected: no errors.

- [ ] **Step 15: Run the full backend test suite**

Run: `cd backend && uv run pytest -v && uv run mypy src && uv run ruff check src tests`
Expected: all tests pass; mypy/ruff clean across the whole backend.

- [ ] **Step 16: Commit**

```bash
git add backend/src/agentdrops/exports backend/src/agentdrops/storage/minio_client.py backend/src/agentdrops/api/schemas/exports.py backend/src/agentdrops/api/routes/exports.py backend/src/agentdrops/api/app.py backend/src/agentdrops/worker/tasks.py backend/src/agentdrops/worker/main.py backend/pyproject.toml backend/uv.lock backend/tests/unit/exports backend/tests/integration/api/test_export_routes.py
git commit -m "feat(backend): add PDF/XLSX export rendering, MinIO storage, and export routes"
```

---

## Post-Plan Manual Verification

After Task 16, bring the full stack up and smoke-test it manually before starting the frontend plan:

```bash
docker compose up -d postgres redis minio
cd backend && uv run alembic upgrade head
cd backend && uv run uvicorn agentdrops.api.app:create_app --factory --reload &
cd backend && uv run arq agentdrops.worker.main.WorkerSettings &
curl -X POST http://localhost:8000/runs -H "Content-Type: application/json" \
  -d '{"topic": "AI note-taking apps", "constraints": "US market only"}'
curl http://localhost:8000/runs/<run_id>
curl -N http://localhost:8000/runs/<run_id>/events
```

Confirm a run progresses from `queued` → `running` → `completed` (this exercises real Anthropic/Exa/Tavily/NewsAPI/Reddit API calls and will take several minutes and consume API credits), the SSE stream shows real events in the order described in `docs/ui-builder-system-prompt.md` §4, and `GET /runs/{id}` returns a populated `final_report` and `idea_onepager`.

## Known Gaps (out of scope for this plan, flagged for a follow-up)

- **Structured logging correlation:** the design spec calls for `structlog` JSON logs correlated by `run_id`, mirrored alongside `run_events`. The existing `logging.py` module provides the `structlog` configuration, but no task here wires `logger.bind(run_id=...)` calls through the new routes/nodes/worker. Functionally the audit trail is fully covered by Postgres `run_events` (Task 3) — this gap is about stdout log correlation for external log aggregation, not user-facing behavior.
- **CI pipeline:** no `.github/workflows` exists yet in this repo for either Plan 1 or this plan. The spec's "lint, type-check, unit tests, mocked-LLM integration test must pass before merge" gate is not automated — running `uv run ruff check`, `uv run mypy src`, and `uv run pytest` locally (as every task's steps do) is the only enforcement today.
