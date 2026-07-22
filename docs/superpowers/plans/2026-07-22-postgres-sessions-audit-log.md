# Postgres Sessions + Audit Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the in-memory `SessionStore` with a Postgres-backed one and add a Postgres audit log of completed chat turns, per `docs/superpowers/specs/2026-07-21-postgres-sessions-audit-log-design.md`.

**Architecture:** A shared `asyncpg.Pool` (`backend/src/agentdrops/db/pool.py`) built once in `agentdrops/main.py`'s `lifespan`. `repository/sessions.py` and a new `repository/audit.py` hold the pool and issue raw SQL against two new tables (`sessions`, `audit_log`), created by an Alembic migration under `db/migrations/`. `api/v1/chat.py` and `api/v1/research.py` switch their `sessions.*` calls to `await`, and `chat.py` gains one `audit.record(...)` call per completed `/chat`/`/chat/stream` turn.

**Tech Stack:** `asyncpg` (runtime pool + queries), `alembic` + `psycopg2-binary` (migrations only, never imported by app code), Postgres 16 (already provisioned by `docker-compose.yml`).

## Global Constraints

- Python 3.12, `backend/` src-layout (`backend/src/agentdrops/`).
- `ruff check .` must pass: line-length 100, `select = ["E","F","I","UP","B","SIM","ASYNC"]`.
- `mypy src` must pass in strict mode.
- `pytest` config: `asyncio_mode = "auto"` (no `@pytest.mark.asyncio` needed), `pythonpath = ["src"]`, `testpaths = ["tests"]`. Every test directory has an `__init__.py`.
- No SQLAlchemy import anywhere under `src/agentdrops/` except `db/migrations/env.py` — app code talks to Postgres only through `asyncpg`.
- `DATABASE_URL` is `postgresql+asyncpg://agentdrops:agentdrops@localhost:5432/agentdrops` by default (`.env.example`, matches `docker-compose.yml`); asyncpg's own DSN parser needs the `+asyncpg` marker stripped before connecting.
- Commit messages follow this repo's existing style: `type: short description` (see `git log --oneline`), one commit per task below.
- `docker compose up -d` (run from `backend/`) starts Postgres on 5432 — integration tests in Tasks 4–5 need it running; they auto-skip via `pytest.skip` if it isn't reachable, per the design spec's testing section. Don't treat a skip as a task failure.

---

### Task 1: Add Postgres dependencies

**Files:**
- Modify: `backend/pyproject.toml`

**Interfaces:**
- Produces: `asyncpg`, `alembic`, `psycopg2-binary` importable in the `dev` venv; a new `db` extra.

- [ ] **Step 1: Add the dependencies**

In `backend/pyproject.toml`, add `"asyncpg>=0.29"` to `[project.dependencies]` (after `"uvicorn>=0.30",`):

```toml
    "fastapi>=0.115",
    "uvicorn>=0.30",
    "asyncpg>=0.29",
    "openai>=1.50",
```

Add a new `db` extra and pull it into `dev`:

```toml
[project.optional-dependencies]
providers = [
    "langchain-anthropic>=0.2",
    "langchain-google-genai>=2.0",
]
db = [
    "alembic>=1.13",
    "psycopg2-binary>=2.9",
]
dev = [
    "agentdrops[providers,db]",
    "pytest>=8.2",
    "pytest-asyncio>=0.23",
    "respx>=0.21",
    "ruff>=0.5",
    "mypy>=1.10",
]
```

Add a third mypy override block (after the existing `langchain.*` one) so strict mode doesn't demand stubs for these:

```toml
[[tool.mypy.overrides]]
module = ["asyncpg.*", "alembic.*"]
ignore_missing_imports = true
```

- [ ] **Step 2: Install and verify**

Run: `cd backend && .venv/bin/python -m pip install -e ".[dev]"`
Expected: `Successfully installed ... asyncpg-... alembic-... psycopg2-binary-...` (or similar — versions may float upward).

Run: `.venv/bin/python -c "import asyncpg, alembic, psycopg2"`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add backend/pyproject.toml
git commit -m "chore: add asyncpg and alembic dependencies"
```

---

### Task 2: Connection pool (`db/pool.py`)

**Files:**
- Create: `backend/src/agentdrops/db/__init__.py`
- Create: `backend/src/agentdrops/db/pool.py`
- Create: `backend/tests/unit/db/__init__.py`
- Create: `backend/tests/unit/db/test_pool.py`

**Interfaces:**
- Consumes: `agentdrops.config.Settings` (existing — `settings.database_url: str`).
- Produces: `create_pool(settings: Settings) -> asyncpg.Pool` (async), used by Task 6. `_asyncpg_dsn(database_url: str) -> str` (module-private, tested directly).

- [ ] **Step 1: Create the package init**

```python
# backend/src/agentdrops/db/__init__.py
"""Postgres connection pool and schema migrations. Data access lives in `agentdrops.repository`."""
```

- [ ] **Step 2: Write the failing test**

Create an empty `backend/tests/unit/db/__init__.py` (no content — matches every other test directory in `tests/unit/`).

```python
# backend/tests/unit/db/test_pool.py
from agentdrops.db.pool import _asyncpg_dsn


def test_strips_sqlalchemy_asyncpg_driver_marker() -> None:
    url = "postgresql+asyncpg://agentdrops:agentdrops@localhost:5432/agentdrops"
    assert _asyncpg_dsn(url) == "postgresql://agentdrops:agentdrops@localhost:5432/agentdrops"


def test_leaves_plain_postgresql_url_unchanged() -> None:
    url = "postgresql://agentdrops:agentdrops@localhost:5432/agentdrops"
    assert _asyncpg_dsn(url) == url
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/db/test_pool.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdrops.db.pool'`.

- [ ] **Step 4: Write the implementation**

```python
# backend/src/agentdrops/db/pool.py
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/db/test_pool.py -v`
Expected: `2 passed`.

- [ ] **Step 6: Lint and type-check**

Run: `.venv/bin/ruff check src/agentdrops/db tests/unit/db && .venv/bin/mypy src/agentdrops/db`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add backend/src/agentdrops/db/__init__.py backend/src/agentdrops/db/pool.py \
        backend/tests/unit/db/__init__.py backend/tests/unit/db/test_pool.py
git commit -m "feat: add asyncpg connection pool"
```

---

### Task 3: Alembic migrations (`sessions` + `audit_log` tables)

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/src/agentdrops/db/migrations/env.py`
- Create: `backend/src/agentdrops/db/migrations/script.py.mako`
- Create: `backend/src/agentdrops/db/migrations/versions/0001_create_sessions_and_audit_log.py`

**Interfaces:**
- Consumes: `agentdrops.config.get_settings()` (existing).
- Produces: `sessions` and `audit_log` tables in Postgres, consumed by Tasks 4–5. No Python symbols — this task's deliverable is schema, verified by running the migration.

- [ ] **Step 1: Write `alembic.ini`**

```ini
# backend/alembic.ini
[alembic]
script_location = src/agentdrops/db/migrations

[loggers]
keys = root,sqlalchemy,alembic

[logger_root]
level = WARNING
handlers = console
qualname =

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handlers]
keys = console

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatters]
keys = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 2: Write `env.py`**

```python
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
```

- [ ] **Step 3: Write `script.py.mako`** (Alembic's standard template, needed for any future `alembic revision -m "..."`)

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: Sequence[str] | None = ${repr(branch_labels)}
depends_on: Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 4: Write the `0001` migration**

```python
# backend/src/agentdrops/db/migrations/versions/0001_create_sessions_and_audit_log.py
"""create sessions and audit_log tables

Revision ID: 0001
Revises:
Create Date: 2026-07-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE sessions (
            thread_id   TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'clarifying',
            report      TEXT,
            sources     JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE audit_log (
            id          BIGSERIAL PRIMARY KEY,
            thread_id   TEXT NOT NULL REFERENCES sessions(thread_id) ON DELETE CASCADE,
            operation   TEXT NOT NULL,
            status      TEXT NOT NULL,
            detail      JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_audit_log_thread_id ON audit_log (thread_id)")


def downgrade() -> None:
    op.execute("DROP TABLE audit_log")
    op.execute("DROP TABLE sessions")
```

- [ ] **Step 5: Start Postgres and apply the migration**

Run: `docker compose up -d postgres`
Expected: `postgres` container reports `healthy` within ~10s (`docker compose ps`).

Run: `cd backend && DATABASE_URL="postgresql+asyncpg://agentdrops:agentdrops@localhost:5432/agentdrops" .venv/bin/alembic upgrade head`
Expected: `Running upgrade  -> 0001, create sessions and audit_log tables`.

If Docker isn't available in this environment, skip this step — Task 4/5's integration tests will auto-skip, and the migration will be applied the first time a real Postgres is available. Do not treat an unreachable Docker daemon as a task failure.

- [ ] **Step 6: Verify the schema**

Run: `docker compose exec postgres psql -U agentdrops -c '\dt'`
Expected: lists `sessions` and `audit_log`.

(Skip if Step 5 was skipped.)

- [ ] **Step 7: Commit**

```bash
git add backend/alembic.ini backend/src/agentdrops/db/migrations
git commit -m "feat: add sessions and audit_log Alembic migration"
```

---

### Task 4: Postgres-backed `SessionStore`

**Files:**
- Modify: `backend/src/agentdrops/repository/sessions.py` (currently the in-memory implementation, already renamed here from `api/sessions.py`)
- Create: `backend/tests/unit/repository/__init__.py`
- Create: `backend/tests/unit/repository/conftest.py`
- Create: `backend/tests/unit/repository/test_sessions.py`

**Interfaces:**
- Consumes: `agentdrops.db.pool.create_pool` (Task 2), `agentdrops.config.Settings`.
- Produces: `SessionStore(pool: asyncpg.Pool)` with `async def touch(thread_id: str, *, title: str) -> SessionRecord`, `async def set_status(thread_id: str, status: Status, *, report: str | None = None) -> None`, `async def add_source(thread_id: str, topic: str, summary: str) -> None`, `async def get(thread_id: str) -> SessionRecord | None`, `async def list_recent() -> list[SessionRecord]`. `SessionRecord` (dataclass: `thread_id: str`, `title: str`, `created_at: datetime`, `status: Status = "clarifying"`, `report: str | None = None`, `sources: list[dict[str, str]]`) and `Status = Literal["clarifying", "running", "done", "failed"]` keep their existing names — Tasks 6–9 import them unchanged.

- [ ] **Step 1: Write the shared `pool` fixture**

```python
# backend/tests/unit/repository/__init__.py
```

```python
# backend/tests/unit/repository/conftest.py
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
```

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/unit/repository/test_sessions.py
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
```

- [ ] **Step 3: Run tests to verify they fail (or skip if no Postgres)**

Run: `.venv/bin/pytest tests/unit/repository/test_sessions.py -v`
Expected: either `5 failed` (e.g. `AttributeError: 'SessionStore' object has no attribute...` or a `TypeError` — `touch`/`get` etc. are still sync, so `await`ing them raises `TypeError: object SessionRecord can't be used in 'await' expression`), or `5 skipped` if Postgres isn't reachable in this environment. Either outcome is fine at this step; if skipped, still proceed to Step 4 and rely on Step 6's real run once Postgres is available.

- [ ] **Step 4: Rewrite `repository/sessions.py`**

```python
# backend/src/agentdrops/repository/sessions.py
"""Postgres-backed session registry: title/status/report/sources per thread.

Backs the sidebar listing and the reopen-a-completed-run endpoints. Persisted in the `sessions`
table (`db/migrations/versions/0001_create_sessions_and_audit_log.py`), so state survives a
process restart — unlike the compiled graph's `InMemorySaver` checkpointer, which this change
does not touch.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

import asyncpg

Status = Literal["clarifying", "running", "done", "failed"]

_COLUMNS = "thread_id, title, status, report, sources, created_at"


@dataclass
class SessionRecord:
    """One research thread's session-level metadata, as opposed to the graph's own state."""

    thread_id: str
    title: str
    created_at: datetime
    status: Status = "clarifying"
    report: str | None = None
    sources: list[dict[str, str]] = field(default_factory=list)


def _row_to_record(row: asyncpg.Record) -> SessionRecord:
    return SessionRecord(
        thread_id=row["thread_id"],
        title=row["title"],
        created_at=row["created_at"],
        status=row["status"],
        report=row["report"],
        sources=row["sources"],
    )


class SessionStore:
    """Tracks one `SessionRecord` per thread_id in Postgres, via a shared connection pool."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def touch(self, thread_id: str, *, title: str) -> SessionRecord:
        """Create a session record the first time a thread is seen; a no-op afterward."""
        row = await self._pool.fetchrow(
            f"""
            INSERT INTO sessions (thread_id, title)
            VALUES ($1, $2)
            ON CONFLICT (thread_id) DO NOTHING
            RETURNING {_COLUMNS}
            """,
            thread_id,
            title,
        )
        if row is None:
            row = await self._pool.fetchrow(
                f"SELECT {_COLUMNS} FROM sessions WHERE thread_id = $1", thread_id
            )
        assert row is not None
        return _row_to_record(row)

    async def set_status(
        self, thread_id: str, status: Status, *, report: str | None = None
    ) -> None:
        await self._pool.execute(
            "UPDATE sessions SET status = $2, report = COALESCE($3, report), "
            "updated_at = now() WHERE thread_id = $1",
            thread_id,
            status,
            report,
        )

    async def add_source(self, thread_id: str, topic: str, summary: str) -> None:
        await self._pool.execute(
            "UPDATE sessions SET sources = sources || $2::jsonb, updated_at = now() "
            "WHERE thread_id = $1",
            thread_id,
            [{"topic": topic, "summary": summary}],
        )

    async def get(self, thread_id: str) -> SessionRecord | None:
        row = await self._pool.fetchrow(
            f"SELECT {_COLUMNS} FROM sessions WHERE thread_id = $1", thread_id
        )
        return _row_to_record(row) if row is not None else None

    async def list_recent(self) -> list[SessionRecord]:
        rows = await self._pool.fetch(f"SELECT {_COLUMNS} FROM sessions ORDER BY created_at DESC")
        return [_row_to_record(row) for row in rows]
```

- [ ] **Step 5: Run tests to verify they pass (or skip)**

Run: `.venv/bin/pytest tests/unit/repository/test_sessions.py -v`
Expected: `5 passed` if Postgres (with the `0001` migration applied) is reachable at `localhost:5432`; `5 skipped` otherwise. A skip here is acceptable — do not attempt to make the tests pass without real Postgres.

- [ ] **Step 6: Lint and type-check**

Run: `.venv/bin/ruff check src/agentdrops/repository tests/unit/repository && .venv/bin/mypy src/agentdrops/repository`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add backend/src/agentdrops/repository/sessions.py backend/tests/unit/repository
git commit -m "feat: back SessionStore with Postgres"
```

---

### Task 5: `AuditLog`

**Files:**
- Create: `backend/src/agentdrops/repository/audit.py`
- Create: `backend/tests/unit/repository/test_audit.py`

**Interfaces:**
- Consumes: `asyncpg.Pool` (Task 2), `SessionStore` (Task 4, for the FK in tests), the `pool` fixture (Task 4's `conftest.py`).
- Produces: `AuditLog(pool: asyncpg.Pool)` with `async def record(self, thread_id: str, *, operation: str, status: str, detail: dict[str, object] | None = None) -> None`, used by Task 7.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/repository/test_audit.py
"""Integration tests for `AuditLog` against a real Postgres — see conftest.py for the
auto-skip-if-unreachable `pool` fixture."""

import asyncpg

from agentdrops.repository.audit import AuditLog
from agentdrops.repository.sessions import SessionStore


async def test_record_inserts_one_row_per_call(pool: asyncpg.Pool) -> None:
    await SessionStore(pool).touch("t1", title="EV charging in the EU")
    audit = AuditLog(pool)

    await audit.record("t1", operation="chat", status="done", detail={"report_chars": 1200})

    rows = await pool.fetch(
        "SELECT operation, status, detail FROM audit_log WHERE thread_id = $1", "t1"
    )
    assert len(rows) == 1
    assert rows[0]["operation"] == "chat"
    assert rows[0]["status"] == "done"
    assert rows[0]["detail"] == {"report_chars": 1200}


async def test_record_defaults_detail_to_empty_object(pool: asyncpg.Pool) -> None:
    await SessionStore(pool).touch("t2", title="EV charging in the EU")
    audit = AuditLog(pool)

    await audit.record("t2", operation="chat_stream", status="clarify")

    row = await pool.fetchrow("SELECT detail FROM audit_log WHERE thread_id = $1", "t2")
    assert row is not None
    assert row["detail"] == {}
```

- [ ] **Step 2: Run tests to verify they fail (or skip)**

Run: `.venv/bin/pytest tests/unit/repository/test_audit.py -v`
Expected: `2 failed` with `ModuleNotFoundError: No module named 'agentdrops.repository.audit'`, or `2 skipped` if Postgres isn't reachable.

- [ ] **Step 3: Write the implementation**

```python
# backend/src/agentdrops/repository/audit.py
"""Postgres-backed audit trail: one row per completed `/v1/chat` or `/v1/chat/stream` call.

See `db/migrations/versions/0001_create_sessions_and_audit_log.py` for the `audit_log` schema.
"""

import asyncpg


class AuditLog:
    """Records one outcome row per chat turn, via the shared connection pool."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def record(
        self,
        thread_id: str,
        *,
        operation: str,
        status: str,
        detail: dict[str, object] | None = None,
    ) -> None:
        await self._pool.execute(
            "INSERT INTO audit_log (thread_id, operation, status, detail) "
            "VALUES ($1, $2, $3, $4::jsonb)",
            thread_id,
            operation,
            status,
            detail or {},
        )
```

- [ ] **Step 4: Run tests to verify they pass (or skip)**

Run: `.venv/bin/pytest tests/unit/repository/test_audit.py -v`
Expected: `2 passed` or `2 skipped`.

- [ ] **Step 5: Lint and type-check**

Run: `.venv/bin/ruff check src/agentdrops/repository/audit.py tests/unit/repository/test_audit.py && .venv/bin/mypy src/agentdrops/repository/audit.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/src/agentdrops/repository/audit.py backend/tests/unit/repository/test_audit.py
git commit -m "feat: add Postgres audit log"
```

---

### Task 6: Wire the pool into `agentdrops/main.py`

**Files:**
- Modify: `backend/src/agentdrops/main.py`

**Interfaces:**
- Consumes: `create_pool` (Task 2), `SessionStore` (Task 4), `AuditLog` (Task 5).
- Produces: `app.state.pool: asyncpg.Pool`, `app.state.sessions: SessionStore`, `app.state.audit: AuditLog` — consumed by Tasks 7–8. Names `create_pool`, `SessionStore`, `AuditLog` must be imported directly into `main.py`'s module namespace (not accessed via a qualified path) so Task 9's tests can `monkeypatch.setattr(main_module, "create_pool", ...)`, matching the existing pattern for `build_market_researcher`.

- [ ] **Step 1: Update imports and `lifespan`**

In `backend/src/agentdrops/main.py`, replace:

```python
from agentdrops.agents.graph import build_market_researcher
from agentdrops.api.v1 import router as v1_router
from agentdrops.config import get_settings
from agentdrops.observability.setup import configure_observability, instrument_fastapi
from agentdrops.repository.sessions import SessionStore
from agentdrops.types.error_codes import Error, ValidationError
from agentdrops.types.response import ErrorResponse, Response, SuccessResponse
```

with:

```python
from agentdrops.agents.graph import build_market_researcher
from agentdrops.api.v1 import router as v1_router
from agentdrops.config import get_settings
from agentdrops.db.pool import create_pool
from agentdrops.observability.setup import configure_observability, instrument_fastapi
from agentdrops.repository.audit import AuditLog
from agentdrops.repository.sessions import SessionStore
from agentdrops.types.error_codes import Error, ValidationError
from agentdrops.types.response import ErrorResponse, Response, SuccessResponse
```

Replace the `lifespan` function:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the shared httpx client, DB pool, compiled graph, and session/audit stores, once
    per process.

    Telemetry is configured *before* the httpx client and the graph are built: both the httpx
    and LangChain instrumentors patch at import/class level, so anything constructed ahead of
    them would never be traced.
    """
    settings = get_settings()
    providers = configure_observability(settings)
    try:
        pool = await create_pool(settings)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                app.state.graph = build_market_researcher(settings, client)
                app.state.pool = pool
                app.state.sessions = SessionStore(pool)
                app.state.audit = AuditLog(pool)
                yield
        finally:
            await pool.close()
    finally:
        providers.shutdown()
```

- [ ] **Step 2: Lint and type-check**

Run: `.venv/bin/ruff check src/agentdrops/main.py && .venv/bin/mypy src/agentdrops/main.py`
Expected: no errors. (This step alone will not run cleanly against `pytest` yet — Tasks 7–9 still call the old sync `SessionStore` API. That's expected; don't fix it here.)

- [ ] **Step 3: Commit**

```bash
git add backend/src/agentdrops/main.py
git commit -m "feat: wire Postgres pool, sessions, and audit log into app lifespan"
```

---

### Task 7: Await sessions + record audit in `api/v1/chat.py`

**Files:**
- Modify: `backend/src/agentdrops/api/v1/chat.py`

**Interfaces:**
- Consumes: `SessionStore` (now async, Task 4), `AuditLog.record` (Task 5), `request.app.state.audit` (Task 6).

- [ ] **Step 1: Fix the import block**

At the top of `backend/src/agentdrops/api/v1/chat.py`, replace:

```python
from agentdrops.api.sessions import SessionStore
from agentdrops.api.v1.schema import ChatRequest, ChatResponse
from agentdrops.observability.logging import bind_run_id
from agentdrops.observability.tracing import traced_span
from agentdrops.types.error_codes import BadGatewayError, fastAPIErrorResponseModels
from agentdrops.types.response import ErrorResponse, SuccessResponse
```

with (alphabetical — `repository.*` sorts after `observability.*`, before `types.*`):

```python
from agentdrops.api.v1.schema import ChatRequest, ChatResponse
from agentdrops.observability.logging import bind_run_id
from agentdrops.observability.tracing import traced_span
from agentdrops.repository.audit import AuditLog
from agentdrops.repository.sessions import SessionStore
from agentdrops.types.error_codes import BadGatewayError, fastAPIErrorResponseModels
from agentdrops.types.response import ErrorResponse, SuccessResponse
```

- [ ] **Step 2: Await every `sessions.*` call inside `_run_graph_turn`**

In `_run_graph_turn`, change:

```python
                if stream_type == "custom":
                    if chunk.get("type") == "source":
                        sessions.add_source(thread_id, chunk["topic"], chunk["summary"])
```

to:

```python
                if stream_type == "custom":
                    if chunk.get("type") == "source":
                        await sessions.add_source(thread_id, chunk["topic"], chunk["summary"])
```

Change:

```python
                    if node_name == "clarify_with_user" and node_output.get("needs_clarification"):
                        question = str(node_output["messages"][-1].content)
                        sessions.set_status(thread_id, "clarifying")
```

to:

```python
                    if node_name == "clarify_with_user" and node_output.get("needs_clarification"):
                        question = str(node_output["messages"][-1].content)
                        await sessions.set_status(thread_id, "clarifying")
```

Change:

```python
                    if node_name == "final_report_generation":
                        report = node_output["final_report"]
                        sessions.set_status(thread_id, "done", report=report)
```

to:

```python
                    if node_name == "final_report_generation":
                        report = node_output["final_report"]
                        await sessions.set_status(thread_id, "done", report=report)
```

Change:

```python
                    if node_name == "supervisor":
                        sessions.set_status(thread_id, "running")
```

to:

```python
                    if node_name == "supervisor":
                        await sessions.set_status(thread_id, "running")
```

- [ ] **Step 3: Await `sessions.touch` and add `audit.record` in `chat()`**

Replace the body of `chat()`:

```python
@router.post("/chat", response_model=SuccessResponse[ChatResponse], responses=_CHAT_ERROR_RESPONSES)
async def chat(request: Request, body: ChatRequest) -> SuccessResponse[ChatResponse]:
    """Advance one chat turn: clarify, research, and report, resuming state via `thread_id`."""
    thread_id = body.thread_id or str(uuid.uuid4())
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    sessions: SessionStore = request.app.state.sessions
    audit: AuditLog = request.app.state.audit
    await sessions.touch(thread_id, title=body.message[:TITLE_MAX_LENGTH])
    graph = request.app.state.graph
    inputs = {"messages": [HumanMessage(content=body.message)]}

    terminal: dict[str, Any] | None = None
    try:
        async for event in _run_graph_turn(graph, inputs, config, thread_id, sessions):
            terminal = event
    except Exception as exc:
        logger.exception("chat turn failed for thread_id=%s", thread_id)
        await sessions.set_status(thread_id, "failed")
        await audit.record(thread_id, operation="chat", status="failed", detail={"error": str(exc)})
        raise ErrorResponse(
            BadGatewayError(message="Research agent failed to complete this turn")
        ) from exc

    assert terminal is not None
    if terminal["type"] == "done":
        await audit.record(
            thread_id,
            operation="chat",
            status="done",
            detail={"report_chars": len(terminal["report"])},
        )
        return SuccessResponse(
            data=ChatResponse(
                thread_id=thread_id,
                response=terminal["report"],
                is_followup=False,
                report=terminal["report"],
            )
        )
    await audit.record(thread_id, operation="chat", status="clarify")
    return SuccessResponse(
        data=ChatResponse(thread_id=thread_id, response=terminal["response"], is_followup=True)
    )
```

- [ ] **Step 4: Await `sessions.touch` and add `audit.record` in `chat_stream()`**

Replace the body of `chat_stream()`:

```python
@router.post("/chat/stream")
async def chat_stream(request: Request, body: ChatRequest) -> StreamingResponse:
    """Advance one chat turn, streaming progress/source events as the graph runs, via SSE.

    Event shapes:
    - `{"type": "progress", "step": str, "detail"?: str}` — a top-level stage started, or (from
      inside the supervisor) one delegated research topic began.
    - `{"type": "source", "topic": str, "summary": str}` — one delegated topic finished.
    - `{"type": "clarify", "thread_id": str, "response": str}` — terminal: the agent needs more
      information before it can research; the turn ends here.
    - `{"type": "done", "thread_id": str, "report": str}` — terminal: the final report is ready.
    - `{"type": "error", "thread_id": str, "message": str}` — terminal: the run failed.
    """
    thread_id = body.thread_id or str(uuid.uuid4())
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    graph = request.app.state.graph
    sessions: SessionStore = request.app.state.sessions
    audit: AuditLog = request.app.state.audit
    await sessions.touch(thread_id, title=body.message[:TITLE_MAX_LENGTH])
    inputs = {"messages": [HumanMessage(content=body.message)]}

    async def events() -> AsyncIterator[str]:
        terminal: dict[str, Any] | None = None
        try:
            async for event in _run_graph_turn(graph, inputs, config, thread_id, sessions):
                terminal = event
                yield _sse(event)
        except Exception as exc:
            logger.exception("chat/stream turn failed for thread_id=%s", thread_id)
            await sessions.set_status(thread_id, "failed")
            await audit.record(
                thread_id, operation="chat_stream", status="failed", detail={"error": str(exc)}
            )
            yield _sse({"type": "error", "thread_id": thread_id, "message": str(exc)})
            return
        if terminal is not None and terminal["type"] == "done":
            await audit.record(
                thread_id,
                operation="chat_stream",
                status="done",
                detail={"report_chars": len(terminal["report"])},
            )
        else:
            await audit.record(thread_id, operation="chat_stream", status="clarify")

    return StreamingResponse(events(), media_type="text/event-stream")
```

- [ ] **Step 5: Lint and type-check**

Run: `.venv/bin/ruff check src/agentdrops/api/v1/chat.py && .venv/bin/mypy src/agentdrops/api/v1/chat.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/src/agentdrops/api/v1/chat.py
git commit -m "feat: await Postgres sessions and record audit log in chat routes"
```

---

### Task 8: Await sessions in `api/v1/sessions.py` and `api/v1/research.py`

Session-listing now lives in its own route module (`api/v1/sessions.py`), separate from
`api/v1/research.py`'s status/report routes — both still just read `request.app.state.sessions`.

**Files:**
- Modify: `backend/src/agentdrops/api/v1/sessions.py`
- Modify: `backend/src/agentdrops/api/v1/research.py`

**Interfaces:**
- Consumes: `SessionStore` (now async, Task 4).

- [ ] **Step 1: Await `sessions.list_recent()` in `api/v1/sessions.py`**

Change:

```python
async def list_sessions(request: Request) -> SuccessResponse[SessionsResponse]:
    """List every known research thread, most recently started first, for the sidebar."""
    sessions: SessionStore = request.app.state.sessions
    return SuccessResponse(
        data=SessionsResponse(
            sessions=[
                SessionSummary(
                    id=s.thread_id,
                    title=s.title,
                    created_at=s.created_at.isoformat(),
                    status=s.status,
                )
                for s in sessions.list_recent()
            ]
        )
    )
```

to:

```python
async def list_sessions(request: Request) -> SuccessResponse[SessionsResponse]:
    """List every known research thread, most recently started first, for the sidebar."""
    sessions: SessionStore = request.app.state.sessions
    recent = await sessions.list_recent()
    return SuccessResponse(
        data=SessionsResponse(
            sessions=[
                SessionSummary(
                    id=s.thread_id,
                    title=s.title,
                    created_at=s.created_at.isoformat(),
                    status=s.status,
                )
                for s in recent
            ]
        )
    )
```

- [ ] **Step 2: Await `sessions.get()` in `api/v1/research.py`'s `get_research_status`**

Change:

```python
    sessions: SessionStore = request.app.state.sessions
    session = sessions.get(thread_id)
    if session is not None and session.status == "failed":
```

to:

```python
    sessions: SessionStore = request.app.state.sessions
    session = await sessions.get(thread_id)
    if session is not None and session.status == "failed":
```

- [ ] **Step 3: Await `sessions.get()` in `api/v1/research.py`'s `get_research_report`**

Change:

```python
    sessions: SessionStore = request.app.state.sessions
    session = sessions.get(thread_id)
    if session is None or session.report is None:
```

to:

```python
    sessions: SessionStore = request.app.state.sessions
    session = await sessions.get(thread_id)
    if session is None or session.report is None:
```

- [ ] **Step 4: Lint and type-check**

Run: `.venv/bin/ruff check src/agentdrops/api/v1/sessions.py src/agentdrops/api/v1/research.py && .venv/bin/mypy src/agentdrops/api/v1/sessions.py src/agentdrops/api/v1/research.py`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add backend/src/agentdrops/api/v1/sessions.py backend/src/agentdrops/api/v1/research.py
git commit -m "feat: await Postgres sessions in session-listing and research routes"
```

---

### Task 9: Fake pool/sessions/audit in the test fixtures that build `TestClient(main_module.app)`

Two separate test modules each build their own `TestClient(main_module.app)`, which now runs the
real `lifespan` (Task 6) on every test — including `tests/unit/test_main.py`, which only exercises
`/health` and error-envelope shaping but still pays for app startup. Both need the pool/session/
audit fakes so none of them reach for a real Postgres.

**Files:**
- Modify: `backend/tests/unit/api/v1/conftest.py`
- Modify: `backend/tests/unit/test_main.py`

**Interfaces:**
- Consumes: names `create_pool`, `SessionStore`, `AuditLog` as imported into `agentdrops.main` (Task 6) — monkeypatched by name, same pattern as the existing `build_market_researcher` patch.
- Produces: `_FakePool`, `_fake_create_pool`, `_FakeSessionStore`, `_FakeAuditLog` in `tests/unit/api/v1/conftest.py`, reused (imported) from `tests/unit/test_main.py`. `client` / `failing_client` fixtures in `api/v1/conftest.py` and the `client` fixture in `test_main.py` all exercise the app against fakes, no real Postgres required. `tests/unit/api/v1/test_chat.py`, `test_research.py`, `test_sessions.py`, and `tests/unit/test_main.py`'s three tests are unchanged — they only talk to the app over HTTP.

- [ ] **Step 1: Add fake pool/session/audit classes and patch the fixtures**

In `backend/tests/unit/api/v1/conftest.py`, add `from datetime import UTC, datetime` to the existing `from collections.abc import ...` / `from typing import Any` stdlib import group (alphabetically between them), and add one new import for the local package:

```python
import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

import agentdrops.main as main_module
from agentdrops.repository.sessions import SessionRecord, Status
from tests.unit.agents.conftest import make_settings
```

Add the fakes (after `_FailingGraph`, before the `client` fixture):

```python
class _FakePool:
    async def close(self) -> None:
        return None


async def _fake_create_pool(_settings: object) -> _FakePool:
    return _FakePool()


class _FakeSessionStore:
    """In-memory stand-in for the Postgres-backed `SessionStore`, same async interface."""

    def __init__(self, _pool: object) -> None:
        self._sessions: dict[str, SessionRecord] = {}

    async def touch(self, thread_id: str, *, title: str) -> SessionRecord:
        return self._sessions.setdefault(
            thread_id,
            SessionRecord(thread_id=thread_id, title=title, created_at=datetime.now(UTC)),
        )

    async def set_status(
        self, thread_id: str, status: Status, *, report: str | None = None
    ) -> None:
        session = self._sessions.get(thread_id)
        if session is None:
            return
        session.status = status
        if report is not None:
            session.report = report

    async def add_source(self, thread_id: str, topic: str, summary: str) -> None:
        session = self._sessions.get(thread_id)
        if session is not None:
            session.sources.append({"topic": topic, "summary": summary})

    async def get(self, thread_id: str) -> SessionRecord | None:
        return self._sessions.get(thread_id)

    async def list_recent(self) -> list[SessionRecord]:
        return sorted(self._sessions.values(), key=lambda s: s.created_at, reverse=True)


class _FakeAuditLog:
    def __init__(self, _pool: object) -> None:
        self.records: list[dict[str, object]] = []

    async def record(
        self,
        thread_id: str,
        *,
        operation: str,
        status: str,
        detail: dict[str, object] | None = None,
    ) -> None:
        self.records.append(
            {"thread_id": thread_id, "operation": operation, "status": status, "detail": detail or {}}
        )
```

Update the `client` fixture:

```python
@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(main_module, "get_settings", lambda: make_settings())
    monkeypatch.setattr(
        main_module, "build_market_researcher", lambda settings, client: _FakeGraph()
    )
    monkeypatch.setattr(main_module, "create_pool", _fake_create_pool)
    monkeypatch.setattr(main_module, "SessionStore", _FakeSessionStore)
    monkeypatch.setattr(main_module, "AuditLog", _FakeAuditLog)
    with TestClient(main_module.app) as test_client:
        yield test_client
```

Update the `failing_client` fixture the same way:

```python
@pytest.fixture
def failing_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(main_module, "get_settings", lambda: make_settings())
    monkeypatch.setattr(
        main_module, "build_market_researcher", lambda settings, client: _FailingGraph()
    )
    monkeypatch.setattr(main_module, "create_pool", _fake_create_pool)
    monkeypatch.setattr(main_module, "SessionStore", _FakeSessionStore)
    monkeypatch.setattr(main_module, "AuditLog", _FakeAuditLog)
    with TestClient(main_module.app) as test_client:
        yield test_client
```

- [ ] **Step 2: Patch `tests/unit/test_main.py`'s `client` fixture the same way**

In `backend/tests/unit/test_main.py`, add an import (after the existing `from tests.unit.agents.conftest import make_settings`, alphabetically — `agents.conftest` sorts before `api.v1.conftest`):

```python
import agentdrops.main as main_module
from tests.unit.agents.conftest import make_settings
from tests.unit.api.v1.conftest import _FakeAuditLog, _FakeSessionStore, _fake_create_pool
```

Change the `client` fixture:

```python
@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(main_module, "get_settings", lambda: make_settings())
    monkeypatch.setattr(
        main_module, "build_market_researcher", lambda settings, client: _StubGraph()
    )
    with TestClient(main_module.app) as test_client:
        yield test_client
```

to:

```python
@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(main_module, "get_settings", lambda: make_settings())
    monkeypatch.setattr(
        main_module, "build_market_researcher", lambda settings, client: _StubGraph()
    )
    monkeypatch.setattr(main_module, "create_pool", _fake_create_pool)
    monkeypatch.setattr(main_module, "SessionStore", _FakeSessionStore)
    monkeypatch.setattr(main_module, "AuditLog", _FakeAuditLog)
    with TestClient(main_module.app) as test_client:
        yield test_client
```

- [ ] **Step 3: Run the full route and main test suites**

Run: `.venv/bin/pytest tests/unit/api/v1 tests/unit/test_main.py -v`
Expected: all tests in `test_chat.py`, `test_research.py`, `test_sessions.py`, and `test_main.py` pass unchanged (they only assert on HTTP responses).

- [ ] **Step 4: Run the entire backend test suite**

Run: `.venv/bin/pytest`
Expected: all tests pass; `tests/unit/repository/*` either pass (if Postgres is reachable) or skip.

- [ ] **Step 5: Lint and type-check the whole tree**

Run: `.venv/bin/ruff check . && .venv/bin/mypy src`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/unit/api/v1/conftest.py backend/tests/unit/test_main.py
git commit -m "test: fake Postgres pool, sessions, and audit log in app-level test fixtures"
```

---

### Task 10: Document the migration command

**Files:**
- Modify: `backend/README.md`

**Interfaces:** None — documentation only.

- [ ] **Step 1: Add a "Migrations" section**

In `backend/README.md`, after the "Infra (postgres, redis, minio)" section and before "## Run", add:

```markdown
## Migrations

```bash
alembic upgrade head
```

Creates the `sessions` and `audit_log` tables (see `src/agentdrops/db/migrations/`). Run once
after `docker compose up -d`, before starting the API — required in dev and in any deploy.
```

- [ ] **Step 2: Commit**

```bash
git add backend/README.md
git commit -m "docs: document the Alembic migration command"
```
