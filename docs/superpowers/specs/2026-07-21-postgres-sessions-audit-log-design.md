# Postgres Sessions + Audit Log — Design Spec

Date: 2026-07-21

## Problem Statement

`Settings.database_url` (`backend/src/agentdrops/config.py`) has existed since the initial backend foundations but nothing in `src/` uses it. Session state (`repository/sessions.py::SessionStore`, formerly `api/sessions.py` — already renamed on disk ahead of this change, content unchanged) is a plain in-process `dict`, and there is no record of what operations the API performed — both die on process restart, and neither is shared across replicas. This spec wires `database_url` up to a real Postgres connection pool, replaces the in-memory `SessionStore` with a Postgres-backed one, and adds an audit log of completed chat turns.

Note: the API surface has since moved to versioned routing (`agentdrops/main.py` mounts `agentdrops/api/v1/` — `chat.py` and `research.py`). The now-superseded `api/main.py`/`api/schema.py` referenced in an earlier draft of this spec no longer exist. All route-level changes below target `api/v1/chat.py` and `api/v1/research.py`.

This is a standalone slice, independent of `2026-07-21-background-workers-redis-design.md` (which plans Redis, not Postgres, as the job-status source of truth, and Postgres only as LangGraph's checkpointer). That design remains a separate, later project; this one does not block or depend on it.

## Goals

- A shared `asyncpg` connection pool, built once in the FastAPI `lifespan` and closed on shutdown.
- Session state (`title`/`status`/`report`/`sources` per `thread_id`) persisted in Postgres, surviving process restarts.
- An audit log: one row per completed `/chat` or `/chat/stream` call, recording thread, operation, outcome, and relevant detail (report size or error).
- Schema managed by Alembic migrations, checked into the repo.

## Non-Goals

- Celery/Redis job execution (separate design doc, separate future change).
- LangGraph checkpointer backend swap (`InMemorySaver` stays as-is).
- Auditing every HTTP request or every graph node — only the turn-level outcome of `/chat` and `/chat/stream`.
- An ORM layer — the app queries Postgres with raw SQL via `asyncpg`; SQLAlchemy is used only inside Alembic's migration runner, never imported by app code.

## Architecture

```
db/
  __init__.py
  pool.py                          asyncpg.Pool lifecycle: create_pool(settings) / pool.close()
  migrations/
    env.py
    versions/0001_create_sessions_and_audit_log.py
repository/
  __init__.py                      (already exists on disk)
  sessions.py                      SessionStore — async, backed by the `sessions` table
  audit.py                         AuditLog — async, backed by the `audit_log` table
```

`db/` owns connection infrastructure only (the pool, migrations). `repository/` owns data access — classes that take the pool and issue SQL. This split is already underway on disk: `api/sessions.py` was renamed to `repository/sessions.py` (content still the old in-memory dict) with `main.py`, `api/v1/chat.py`, and `api/v1/research.py` already importing from the new path. This spec continues that split rather than reverting it.

`app.state.pool` is created once in `lifespan` (`agentdrops/main.py`), alongside the existing httpx client and compiled graph. `SessionStore` and `AuditLog` each hold a reference to that pool — no per-request connection setup, no other component reaches for the pool directly.

`repository/sessions.py`'s in-memory implementation is replaced in place (same file, same public method names, now `async def`) — not deleted and recreated.

## Schema

```sql
CREATE TABLE sessions (
    thread_id   TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'clarifying',
    report      TEXT,
    sources     JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE audit_log (
    id          BIGSERIAL PRIMARY KEY,
    thread_id   TEXT NOT NULL REFERENCES sessions(thread_id) ON DELETE CASCADE,
    operation   TEXT NOT NULL,               -- 'chat' | 'chat_stream'
    status      TEXT NOT NULL,               -- 'done' | 'clarify' | 'failed'
    detail      JSONB NOT NULL DEFAULT '{}'::jsonb,   -- report_chars, error message, etc.
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_log_thread_id ON audit_log (thread_id);
```

`thread_id` stays `TEXT` (it is already `str(uuid.uuid4())` everywhere in the codebase — `api/v1/chat.py`'s `chat`/`chat_stream` routes) rather than a native `UUID` column, to avoid a type-conversion layer at every call site.

`status` on both tables is a free-text column, not a Postgres `ENUM` — the existing `Status` values (`clarifying`/`running`/`done`/`failed`) are already a `Literal` type checked in Python (`repository/sessions.py`, `api/v1/schema.py`); adding a DB-level enum would duplicate that constraint for no behavioral gain and make future status values a migration instead of a code change.

## Connection Pool (`db/pool.py`)

```python
async def create_pool(settings: Settings) -> asyncpg.Pool:
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    return await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10)
```

`DATABASE_URL` (`.env.example`) uses the SQLAlchemy-style `postgresql+asyncpg://` scheme; asyncpg's own `create_pool` expects plain `postgresql://`, so the prefix is stripped before connecting.

## `repository/sessions.py`

Async, same method names as today's `SessionStore`:

- `touch(thread_id, *, title) -> SessionRecord` — `INSERT ... ON CONFLICT (thread_id) DO NOTHING RETURNING ...`, falling back to a `SELECT` if the row already existed.
- `set_status(thread_id, status, *, report=None) -> None` — `UPDATE sessions SET status=$2, report=COALESCE($3, report), updated_at=now() WHERE thread_id=$1`.
- `add_source(thread_id, topic, summary) -> None` — `UPDATE sessions SET sources = sources || $2::jsonb, updated_at=now() WHERE thread_id=$1`.
- `get(thread_id) -> SessionRecord | None`.
- `list_recent() -> list[SessionRecord]` — `ORDER BY created_at DESC`.

`SessionRecord` becomes a plain dataclass built from the returned `asyncpg.Record` (same fields as today's dataclass in `repository/sessions.py`).

## `repository/audit.py`

```python
class AuditLog:
    def __init__(self, pool: asyncpg.Pool) -> None: ...
    async def record(self, thread_id: str, *, operation: str, status: str, detail: dict | None = None) -> None: ...
```

One row per completed `/chat` or `/chat/stream` call — logged once, from the route handler itself (not inside `_run_graph_turn`'s generator), after the turn resolves either successfully or via exception. This avoids a double row on failure (the generator's `finally` block already tracks `outcome` for tracing; audit logging is a separate, single write per HTTP call).

`detail` carries `{"report_chars": len(report)}` on a `done` outcome, `{}` on `clarify`, and `{"error": str(exc)}` on `failed`.

## `agentdrops/main.py` and `api/v1/*` Changes

- `main.py`'s `lifespan`: build the pool via `db.pool.create_pool(settings)`, construct `SessionStore(pool)` and `AuditLog(pool)` onto `app.state`, close the pool in the `finally` block (alongside the existing `providers.shutdown()`).
- `api/v1/chat.py` and `api/v1/research.py`: every existing `sessions.touch` / `sessions.set_status` / `sessions.add_source` / `sessions.get` / `sessions.list_recent` call site becomes `await sessions....`; both already read `request.app.state.sessions`, so no new plumbing is needed to reach the store.
- `api/v1/chat.py`'s `chat()`: after the existing try/except around `_run_graph_turn`, add one `await audit.record(...)` call on the success path (status from `terminal["type"]`) and one in the `except` block (status `"failed"`). `audit` is read off `request.app.state.audit`, same pattern as `sessions`.
- `api/v1/chat.py`'s `chat_stream()`: same shape — one `await audit.record(...)` after the `events()` generator's loop completes normally, one in its `except` block.

No changes to `_run_graph_turn`'s signature beyond what it already takes (it doesn't need the `AuditLog` — audit writes happen at the call sites, not inside the shared generator).

## Dependencies & Migrations

- Runtime (new, added to `[project.dependencies]`): `asyncpg`.
- Migrations-only (new `db` extra, included in `dev`): `alembic`, `psycopg2-binary`. Alembic depends on SQLAlchemy core regardless of app usage; migration files use plain `op.execute("CREATE TABLE ...")` DDL, not ORM models, so no SQLAlchemy import ever appears in `src/agentdrops/`.
- `alembic.ini` lives at `backend/`, `script_location` pointing at `src/agentdrops/db/migrations`.
- New command (documented in the backend README/CLAUDE.md commands section): `alembic upgrade head`, run against `DATABASE_URL` before starting the API — required in dev (after `docker compose up -d`) and in any deploy.

## Error Handling

- Pool creation failure at startup (Postgres unreachable) fails `lifespan` the same way a missing required `.env` key already does today (`Settings` fails fast) — no silent degradation to in-memory state.
- A query failure inside `SessionStore`/`AuditLog` propagates as a normal exception; existing route-level `except Exception` blocks in `chat`/`chat_stream` already catch and translate to the `failed` status / `error` SSE event, so no new error-handling path is needed there.

## Testing

- `db/pool.py`'s DSN-stripping logic gets a plain unit test (pure function, no network).
- `SessionStore` and `AuditLog` issue raw SQL — there is no in-process SQL engine to fake them against (unlike `FakeChatModel` for LLM calls), so they get integration tests that connect to the real docker-compose Postgres (`docker compose up -d`) and are auto-skipped (`pytest.skip`) if the connection is refused. This mirrors the sibling background-workers spec's stance that real infra is exercised via `docker compose up -d`, not mocked.
- `tests/unit/api/v1/test_chat.py` and `test_research.py`'s existing route tests need their `SessionStore` fixture replaced with a fake `sessions`/`audit` pair (matching the new async method signatures) so those tests stay pure-unit, no DB required — same pattern as `FakeChatModel`.

## Rollout

- Additive: no existing endpoint contract changes (response shapes are unchanged; only the storage backing them moves from memory to Postgres).
- One-time discontinuity: any in-memory session data from before this change is lost on deploy (expected — the same caveat already called out for the graph's `InMemorySaver`).
