# Background Workers + Redis Job State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move LangGraph execution out of the FastAPI request/response cycle and into Celery worker processes, per `docs/superpowers/specs/2026-07-21-background-workers-redis-design.md` — reconciled against the Postgres-backed `SessionStore`/`AuditLog`/`ChatService` layer that landed after that spec was written (commits `fce3b75..bc05961`).

**Architecture:** `api/v1/chat.py`'s routes touch the session (Postgres, via the existing `SessionStore`) and enqueue a Celery task, then return/stream immediately — they no longer call `ChatService.run_turn` themselves. A Celery worker builds its own `ChatService` (same class the routes used to call directly) per task, using a Postgres-backed LangGraph checkpointer instead of `InMemorySaver`, and relays every event `run_turn` yields onto a Redis pub/sub channel. `/chat/stream` subscribes to that channel and forwards it as SSE — same wire format the frontend already parses. Session status/report/sources/audit trail continue to live in Postgres (already real, tested infrastructure); Redis's role is narrowed to the Celery broker/backend and the pub/sub relay — there is no separate Redis job-status store.

**Tech Stack:** Celery 5.x (broker+backend=Redis), `redis` (async client), `langgraph-checkpoint-postgres` + `psycopg[binary,pool]`, `fakeredis` (dev/test only).

## Global Constraints

- No network in unit tests: Celery/Redis interactions are tested against `fakeredis.aioredis.FakeRedis` or in-process fakes; Postgres-touching code (migrations, `SessionStore`) follows the existing convention in `backend/tests/unit/repository/` — real Postgres via `docker compose up -d`, auto-skipped (`pytest.skip`) if unreachable.
- `pytest` config is `asyncio_mode = "auto"`, `pythonpath = ["src"]` — `async def test_*` functions need no `@pytest.mark.asyncio` decorator, but a test that must call `asyncio.run()` itself (bridging into Celery's sync task body) MUST be a plain `def test_*`, not `async def`, or it will hit `RuntimeError: asyncio.run() cannot be called from a running event loop`.
- `mypy src` runs in strict mode — every new function needs full type annotations.
- `ruff check .` lint rules: `E, F, I, UP, B, SIM, ASYNC` — imports sorted, no unused imports.
- **Do not change `DATABASE_URL`'s format.** `db/engine.py:20-21` passes `settings.database_url` straight to SQLAlchemy's `create_async_engine`, which requires the `postgresql+asyncpg://` dialect prefix already in `.env.example`/`tests/unit/agents/conftest.py`. `langgraph-checkpoint-postgres`'s `AsyncPostgresSaver` needs the plain `postgresql://` form instead — strip the prefix locally, in the new checkpointer-construction code (Task 3), never in `Settings`/`.env.example`.
- Follow the existing layering: routes (`api/v1/`) call services (`service/`), services call repositories (`repository/`), repositories call the DB via `db/engine.py`'s session factory. The worker is a new caller of the same `service`/`repository` layer, not a parallel implementation of it.
- `psycopg2-binary` (already a dev dependency, for Alembic's sync migration runner) is a different package from `psycopg` (v3, needed by `langgraph-checkpoint-postgres`) — both are needed, they don't conflict.

---

### Task 1: Add background-job dependencies

**Files:**
- Modify: `backend/pyproject.toml`

**Interfaces:**
- Produces: `celery`, `redis` (async client at `redis.asyncio.Redis`), `langgraph-checkpoint-postgres` (`langgraph.checkpoint.postgres.aio.AsyncPostgresSaver`), `psycopg[binary,pool]` as runtime deps; `fakeredis` as a dev/test dep.

- [ ] **Step 1: Add the new dependencies**

In `backend/pyproject.toml`, add to `dependencies` (after `"sqlalchemy[asyncio]>=2.0",`):

```toml
    "sqlalchemy[asyncio]>=2.0",
    "celery>=5.4",
    "redis>=5.0",
    "langgraph-checkpoint-postgres>=3.0",
    "psycopg[binary,pool]>=3.1",
```

Add `fakeredis` to `dev`:

```toml
dev = [
    "agentdrops[providers,db]",
    "pytest>=8.2",
    "pytest-asyncio>=0.23",
    "respx>=0.21",
    "fakeredis>=2.20",
    "ruff>=0.5",
    "mypy>=1.10",
]
```

- [ ] **Step 2: Add the mypy override for `celery`**

Change:

```toml
[[tool.mypy.overrides]]
module = ["asyncpg.*", "alembic.*"]
ignore_missing_imports = true
```

to:

```toml
[[tool.mypy.overrides]]
module = ["asyncpg.*", "alembic.*", "celery.*"]
ignore_missing_imports = true
```

(`langgraph-checkpoint-postgres` is imported as `langgraph.checkpoint.postgres.*`, already covered by the existing `langgraph.*` override; `redis` ships its own inline types since v4.2, so it needs none.)

- [ ] **Step 3: Install and verify**

Run: `cd backend && source .venv/bin/activate && pip install -e ".[dev]"`
Expected: installs successfully.

Run: `python -c "import celery, redis, fakeredis; from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver; print('ok')"`
Expected: prints `ok`.

Run: `pytest`
Expected: PASS (same pass/skip count as before this task).

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml
git commit -m "chore(backend): add celery/redis/postgres-checkpoint deps for background workers"
```

---

### Task 2: Add `queued` status and `clarify_question`/`error` fields to sessions

**Files:**
- Create: `backend/src/agentdrops/db/migrations/versions/0002_add_queued_status_and_session_detail_fields.py`
- Modify: `backend/src/agentdrops/db/models/sessions.py`
- Modify: `backend/src/agentdrops/repository/sessions.py`
- Modify: `backend/src/agentdrops/service/chat_service.py`
- Modify: `backend/src/agentdrops/service/research_service.py`
- Modify: `backend/src/agentdrops/api/v1/schema.py`
- Modify: `backend/tests/unit/repository/test_sessions.py`
- Modify: `backend/tests/unit/api/v1/conftest.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `Status = Literal["queued", "clarifying", "running", "done", "failed"]` (was 4 values, now 5, default `"queued"`); `SessionRecord` gains `clarify_question: str | None = None` and `error: str | None = None`; `SessionStore.set_status(thread_id, status, *, report=None, clarify_question=None, error=None) -> None`; `ResearchService.get_status` returns `"queued"` directly from the session (like it already does for `"failed"`) instead of falling through to an empty checkpoint read and 404ing.

Two real gaps exist today that the async model would otherwise expose:
1. There's no "queued" status — a fresh `touch()` defaults to `"clarifying"` (`db/models/sessions.py:17-19`), which is misleading before any graph node has run, and becomes actively wrong once enqueueing and execution are two different processes with a real gap between them.
2. Nothing durable records *what* a clarify question asked or *why* a turn failed — only the audit log's `detail` JSONB has the error text (`chat_service.py:102-104`), and nothing has the clarify question text at all. `/chat/stream`'s race-condition reconstruction (Task 8) needs both to rebuild a terminal SSE event after the fact.

- [ ] **Step 1: Write the failing repository test**

Add to `backend/tests/unit/repository/test_sessions.py` (these are the existing Postgres-integration tests — auto-skipped if Postgres isn't reachable, per `conftest.py`'s `session_factory` fixture):

```python
async def test_touch_defaults_to_queued(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SessionStore(session_factory)
    session = await store.touch("t-queued", title="EV charging in the EU")

    assert session.status == "queued"


async def test_set_status_stores_clarify_question_and_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SessionStore(session_factory)
    await store.touch("t4", title="EV charging in the EU")

    await store.set_status("t4", "clarifying", clarify_question="Which region?")
    clarifying = await store.get("t4")
    assert clarifying is not None
    assert clarifying.clarify_question == "Which region?"

    await store.set_status("t4", "failed", error="LLM provider unavailable")
    failed = await store.get("t4")
    assert failed is not None
    assert failed.error == "LLM provider unavailable"
```

Update the existing `test_touch_creates_a_session_once` test — it currently asserts `first.status == "clarifying"` (line 19); change that assertion to `first.status == "queued"`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/repository/test_sessions.py -v`
Expected (if Postgres is reachable via `docker compose up -d`): FAIL — `touch()` still defaults to `"clarifying"`, and `set_status()` doesn't accept `clarify_question`/`error` kwargs (`TypeError`). If Postgres isn't reachable, these are skipped — run `docker compose up -d` from `backend/` first.

- [ ] **Step 3: Write the migration**

Create `backend/src/agentdrops/db/migrations/versions/0002_add_queued_status_and_session_detail_fields.py`:

```python
"""add queued status default and clarify_question/error columns

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("sessions", "status", server_default=sa.text("'queued'"))
    op.add_column("sessions", sa.Column("clarify_question", sa.Text(), nullable=True))
    op.add_column("sessions", sa.Column("error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "error")
    op.drop_column("sessions", "clarify_question")
    op.alter_column("sessions", "status", server_default=sa.text("'clarifying'"))
```

Run: `cd backend && alembic upgrade head` (requires `docker compose up -d` first).
Expected: migration applies with no errors.

- [ ] **Step 4: Update the ORM model**

In `backend/src/agentdrops/db/models/sessions.py`, change:

```python
    status: Mapped[str] = mapped_column(
        sa.Text(), nullable=False, server_default=sa.text("'clarifying'")
    )
    report: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
```

to:

```python
    status: Mapped[str] = mapped_column(
        sa.Text(), nullable=False, server_default=sa.text("'queued'")
    )
    report: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    clarify_question: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    error: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
```

- [ ] **Step 5: Update `repository/sessions.py`**

Change the `Status` literal (line 22):

```python
Status = Literal["clarifying", "running", "done", "failed"]
```

to:

```python
Status = Literal["queued", "clarifying", "running", "done", "failed"]
```

Change `SessionRecord` (lines 25-34):

```python
@dataclass
class SessionRecord:
    """One research thread's session-level metadata, as opposed to the graph's own state."""

    thread_id: str
    title: str
    created_at: datetime
    status: Status = "clarifying"
    report: str | None = None
    sources: list[dict[str, str]] = field(default_factory=list)
```

to:

```python
@dataclass
class SessionRecord:
    """One research thread's session-level metadata, as opposed to the graph's own state."""

    thread_id: str
    title: str
    created_at: datetime
    status: Status = "queued"
    report: str | None = None
    sources: list[dict[str, str]] = field(default_factory=list)
    clarify_question: str | None = None
    error: str | None = None
```

Change `_to_record` (lines 37-45):

```python
def _to_record(row: SessionTable) -> SessionRecord:
    return SessionRecord(
        thread_id=row.thread_id,
        title=row.title,
        created_at=row.created_at,
        status=type_cast(Status, row.status),
        report=row.report,
        sources=row.sources,
    )
```

to:

```python
def _to_record(row: SessionTable) -> SessionRecord:
    return SessionRecord(
        thread_id=row.thread_id,
        title=row.title,
        created_at=row.created_at,
        status=type_cast(Status, row.status),
        report=row.report,
        sources=row.sources,
        clarify_question=row.clarify_question,
        error=row.error,
    )
```

Change `set_status` (lines 70-80):

```python
    async def set_status(
        self, thread_id: str, status: Status, *, report: str | None = None
    ) -> None:
        async with self._session_factory() as session:
            values: dict[str, object] = {"status": status, "updated_at": func.now()}
            if report is not None:
                values["report"] = report
            await session.execute(
                update(SessionTable).where(SessionTable.thread_id == thread_id).values(**values)
            )
            await session.commit()
```

to:

```python
    async def set_status(
        self,
        thread_id: str,
        status: Status,
        *,
        report: str | None = None,
        clarify_question: str | None = None,
        error: str | None = None,
    ) -> None:
        async with self._session_factory() as session:
            values: dict[str, object] = {"status": status, "updated_at": func.now()}
            if report is not None:
                values["report"] = report
            if clarify_question is not None:
                values["clarify_question"] = clarify_question
            if error is not None:
                values["error"] = error
            await session.execute(
                update(SessionTable).where(SessionTable.thread_id == thread_id).values(**values)
            )
            await session.commit()
```

- [ ] **Step 6: Run the repository tests to verify they pass**

Run: `pytest tests/unit/repository/test_sessions.py -v`
Expected: PASS.

- [ ] **Step 7: Wire the new fields through `ChatService`**

In `backend/src/agentdrops/service/chat_service.py`, change the clarify branch (lines 61-75):

```python
                        if node_name == "clarify_with_user" and node_output.get(
                            "needs_clarification"
                        ):
                            question = str(node_output["messages"][-1].content)
                            await self._sessions.set_status(thread_id, "clarifying")
                            outcome = "clarify"
```

to:

```python
                        if node_name == "clarify_with_user" and node_output.get(
                            "needs_clarification"
                        ):
                            question = str(node_output["messages"][-1].content)
                            await self._sessions.set_status(
                                thread_id, "clarifying", clarify_question=question
                            )
                            outcome = "clarify"
```

Change `record_failure` (lines 98-104):

```python
    async def record_failure(self, thread_id: str, *, operation: str, error: str) -> None:
        """Record a failed turn: session status plus an audit entry, shared by both endpoints'
        except blocks so the failure side effects can't diverge."""
        await self._sessions.set_status(thread_id, "failed")
        await self._audit.record(
            thread_id, operation=operation, status="failed", detail={"error": error}
        )
```

to:

```python
    async def record_failure(self, thread_id: str, *, operation: str, error: str) -> None:
        """Record a failed turn: session status plus an audit entry, shared by both endpoints'
        except blocks so the failure side effects can't diverge."""
        await self._sessions.set_status(thread_id, "failed", error=error)
        await self._audit.record(
            thread_id, operation=operation, status="failed", detail={"error": error}
        )
```

(The audit log's own `detail={"error": error}` write is unchanged — existing tests asserting on it, e.g. `tests/unit/api/v1/test_chat.py::test_chat_returns_502_and_marks_session_failed_on_graph_error`, still pass.)

- [ ] **Step 8: Fix `ResearchService.get_status` to short-circuit on `queued` (like it already does for `failed`)**

In `backend/src/agentdrops/service/research_service.py`, change:

```python
        session = await self._sessions.get(thread_id)
        if session is not None and session.status == "failed":
            return ResearchStatusResponse(
                thread_id=thread_id, status="failed", research_brief=None, report=None
            )
```

to:

```python
        session = await self._sessions.get(thread_id)
        if session is not None and session.status in ("failed", "queued"):
            return ResearchStatusResponse(
                thread_id=thread_id, status=session.status, research_brief=None, report=None
            )
```

Without this, `GET /research/{thread_id}` for a freshly enqueued (not yet started) turn falls through to `self._graph.aget_state(config)`, finds an empty checkpoint, and returns `None` (404) — even though the session row already correctly shows `"queued"`. This is what makes `"queued"` observable through the status endpoint the frontend actually polls, not just the sidebar list.

- [ ] **Step 9: Update `api/v1/schema.py`'s status literals**

Change (two occurrences — `ResearchStatusResponse.status` and `SessionSummary.status`):

```python
    status: Literal["clarifying", "running", "done", "failed"]
```

to:

```python
    status: Literal["queued", "clarifying", "running", "done", "failed"]
```

- [ ] **Step 10: Update `tests/unit/api/v1/conftest.py`'s fake `SessionStore`/`SessionRecord` default**

The `_FakeSessionStore.touch` (lines 95-99) constructs a bare `SessionRecord(...)`, which will now default to `status="queued"` automatically once Step 5 lands (no edit needed there) — but its `set_status` (lines 101-109) needs the same new kwargs the real one has:

```python
    async def set_status(
        self, thread_id: str, status: Status, *, report: str | None = None
    ) -> None:
        session = self._sessions.get(thread_id)
        if session is None:
            return
        session.status = status
        if report is not None:
            session.report = report
```

to:

```python
    async def set_status(
        self,
        thread_id: str,
        status: Status,
        *,
        report: str | None = None,
        clarify_question: str | None = None,
        error: str | None = None,
    ) -> None:
        session = self._sessions.get(thread_id)
        if session is None:
            return
        session.status = status
        if report is not None:
            session.report = report
        if clarify_question is not None:
            session.clarify_question = clarify_question
        if error is not None:
            session.error = error
```

- [ ] **Step 11: Run the full backend suite**

Run: `pytest`
Expected: PASS (the existing `tests/unit/api/v1/test_chat.py` suite still passes unchanged — it never asserted `status == "clarifying"` as an initial default, only after a turn actually runs).

- [ ] **Step 12: Commit**

```bash
git add backend/src/agentdrops/db/migrations/versions/0002_add_queued_status_and_session_detail_fields.py \
        backend/src/agentdrops/db/models/sessions.py \
        backend/src/agentdrops/repository/sessions.py \
        backend/src/agentdrops/service/chat_service.py \
        backend/src/agentdrops/service/research_service.py \
        backend/src/agentdrops/api/v1/schema.py \
        backend/tests/unit/repository/test_sessions.py \
        backend/tests/unit/api/v1/conftest.py
git commit -m "feat(backend): add queued session status and clarify_question/error detail fields"
```

---

### Task 3: Injectable, Postgres-backed LangGraph checkpointer

**Files:**
- Create: `backend/src/agentdrops/agents/checkpointer.py`
- Modify: `backend/src/agentdrops/agents/graph.py`
- Modify: `backend/src/agentdrops/main.py`
- Modify: `backend/tests/unit/api/v1/conftest.py`
- Test: `backend/tests/unit/agents/test_graph.py` (new file)
- Test: `backend/tests/unit/agents/test_checkpointer.py` (new file)

**Interfaces:**
- Produces: `build_market_researcher(settings: Settings, client: httpx.AsyncClient, checkpointer: BaseCheckpointSaver[Any]) -> CompiledStateGraph[Any, Any, Any, Any]` (checkpointer now injected, `InMemorySaver` no longer hardcoded); `def strip_asyncpg_dialect(database_url: str) -> str` (pure function, `"postgresql+asyncpg://..."` → `"postgresql://..."`); `def checkpointer(settings: Settings) -> AbstractAsyncContextManager[BaseCheckpointSaver[Any]]` — an async context manager both `agentdrops/main.py`'s lifespan (Task 3) and the worker bootstrap (Task 7) use, so the DSN-stripping logic exists in exactly one place.

This is what makes graph state visible across processes: today's `InMemorySaver` means the API's own `graph.aget_state(config)` call (`research_service.py:27`) only ever sees state written by `graph.astream()` calls made *in that same process* — which is fine today (the API calls both), but breaks the moment `astream()` moves to a worker process (Task 6-7). Both the API and the worker need a checkpointer backed by the same Postgres database.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/agents/test_checkpointer.py`:

```python
from agentdrops.agents.checkpointer import strip_asyncpg_dialect


def test_strip_asyncpg_dialect_removes_the_sqlalchemy_prefix() -> None:
    assert (
        strip_asyncpg_dialect("postgresql+asyncpg://u:p@localhost:5432/agentdrops")
        == "postgresql://u:p@localhost:5432/agentdrops"
    )


def test_strip_asyncpg_dialect_is_a_noop_if_already_plain() -> None:
    assert (
        strip_asyncpg_dialect("postgresql://u:p@localhost:5432/agentdrops")
        == "postgresql://u:p@localhost:5432/agentdrops"
    )
```

Create `backend/tests/unit/agents/test_graph.py`:

```python
import httpx
from langgraph.checkpoint.memory import InMemorySaver

from agentdrops.agents.graph import build_market_researcher
from tests.unit.agents.conftest import make_settings


async def test_build_market_researcher_compiles_with_the_given_checkpointer() -> None:
    checkpointer = InMemorySaver()
    async with httpx.AsyncClient() as client:
        graph = build_market_researcher(make_settings(), client, checkpointer)

    assert graph.checkpointer is checkpointer
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/agents/test_checkpointer.py tests/unit/agents/test_graph.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdrops.agents.checkpointer'`, then (once that's created) `build_market_researcher() takes 2 positional arguments but 3 were given`.

- [ ] **Step 3: Implement `strip_asyncpg_dialect` and the `checkpointer` context manager**

Create `backend/src/agentdrops/agents/checkpointer.py`:

```python
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
```

- [ ] **Step 4: Add the `checkpointer` parameter to `build_market_researcher`**

In `backend/src/agentdrops/agents/graph.py`:

Remove line 6:
```python
from langgraph.checkpoint.memory import InMemorySaver
```

Add instead:
```python
from langgraph.checkpoint.base import BaseCheckpointSaver
```

Change the signature (lines 22-24):
```python
def build_market_researcher(
    settings: Settings, client: httpx.AsyncClient
) -> CompiledStateGraph[Any, Any, Any, Any]:
```
to:
```python
def build_market_researcher(
    settings: Settings, client: httpx.AsyncClient, checkpointer: BaseCheckpointSaver[Any]
) -> CompiledStateGraph[Any, Any, Any, Any]:
```

Change the last line (line 80):
```python
    return graph.compile(checkpointer=InMemorySaver())
```
to:
```python
    return graph.compile(checkpointer=checkpointer)
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `pytest tests/unit/agents/test_checkpointer.py tests/unit/agents/test_graph.py -v`
Expected: PASS.

- [ ] **Step 6: Update `agentdrops/main.py`'s lifespan to build and hold open a real checkpointer**

Change the imports (add):
```python
from agentdrops.agents.checkpointer import checkpointer
```

Change the lifespan body (lines 42-57):

```python
    try:
        engine = create_engine(settings)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                session_factory = create_session_factory(engine)
                graph = build_market_researcher(settings, client)
                sessions = SessionStore(session_factory)
                audit = AuditLog(session_factory)
                app.state.engine = engine
                app.state.audit = audit
                app.state.chat_service = ChatService(graph, sessions, audit)
                app.state.research_service = ResearchService(graph, sessions)
                app.state.sessions_service = SessionsService(sessions)
                yield
        finally:
            await engine.dispose()
    finally:
        providers.shutdown()
```

to:

```python
    try:
        engine = create_engine(settings)
        try:
            async with (
                httpx.AsyncClient(timeout=30.0) as client,
                checkpointer(settings) as saver,
            ):
                session_factory = create_session_factory(engine)
                graph = build_market_researcher(settings, client, saver)
                sessions = SessionStore(session_factory)
                audit = AuditLog(session_factory)
                app.state.engine = engine
                app.state.sessions = sessions
                app.state.audit = audit
                app.state.chat_service = ChatService(graph, sessions, audit)
                app.state.research_service = ResearchService(graph, sessions)
                app.state.sessions_service = SessionsService(sessions)
                yield
        finally:
            await engine.dispose()
    finally:
        providers.shutdown()
```

(`app.state.sessions` is newly exposed — Task 8's routes need direct `SessionStore` access to touch a session before enqueueing, the same way `ChatService.run_turn` already does as its first line.)

- [ ] **Step 7: Update `tests/unit/api/v1/conftest.py`'s `client`/`failing_client` fixtures for the 3-arg `build_market_researcher`**

Change (lines 155-157 and 166-168, both fixtures):
```python
    monkeypatch.setattr(
        main_module, "build_market_researcher", lambda settings, client: _FakeGraph()
    )
```
to:
```python
    monkeypatch.setattr(
        main_module,
        "build_market_researcher",
        lambda settings, client, checkpointer: _FakeGraph(),
    )
```

Also add a fake `checkpointer` context manager and patch it in, since `main.py`'s lifespan now calls it. Add to `conftest.py` (near `_FakeEngine`):

```python
from contextlib import asynccontextmanager


class _FakeCheckpointer:
    pass


@asynccontextmanager
async def _fake_checkpointer(_settings: object) -> AsyncIterator[_FakeCheckpointer]:
    yield _FakeCheckpointer()
```

And in `_patch_db` (or both fixtures directly), add:
```python
    monkeypatch.setattr(main_module, "checkpointer", _fake_checkpointer)
```

- [ ] **Step 8: Run the full backend suite**

Run: `pytest && mypy src`
Expected: both PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/src/agentdrops/agents/checkpointer.py \
        backend/src/agentdrops/agents/graph.py \
        backend/src/agentdrops/main.py \
        backend/tests/unit/agents/test_checkpointer.py \
        backend/tests/unit/agents/test_graph.py \
        backend/tests/unit/api/v1/conftest.py
git commit -m "feat(backend): make the LangGraph checkpointer injectable, backed by Postgres"
```

---

### Task 4: Redis pub/sub event helpers

**Files:**
- Create: `backend/src/agentdrops/jobs/__init__.py` (empty)
- Create: `backend/src/agentdrops/jobs/events.py`
- Test: `backend/tests/unit/jobs/__init__.py` (empty)
- Test: `backend/tests/unit/jobs/test_events.py`

**Interfaces:**
- Consumes: `redis.asyncio.Redis` instance.
- Produces: `async def publish_event(redis: Redis, thread_id: str, event: dict[str, Any]) -> None`; `def subscribe_events(redis: Redis, thread_id: str) -> AsyncIterator[dict[str, Any]]` (async generator).

Channel naming: `events:{thread_id}`. The worker (Task 6) publishes, `api/v1/chat.py` (Task 8) subscribes. This is the only new Redis-touching module in this plan — session/report/audit state stays entirely in Postgres (Task 2), so `jobs/` holds nothing but the live-event transport.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/jobs/__init__.py` (empty file).

Create `backend/tests/unit/jobs/test_events.py`:

```python
import asyncio

import pytest
from fakeredis import FakeServer
from fakeredis.aioredis import FakeRedis

from agentdrops.jobs.events import publish_event, subscribe_events


@pytest.fixture
def shared_server() -> FakeServer:
    """`subscribe_events` and `publish_event` run against separate Redis client instances in
    prod (API vs. worker process) — sharing one FakeServer reproduces that across two fake
    clients, since a single FakeRedis instance's pubsub never sees another instance's publish."""
    return FakeServer()


async def test_subscribe_receives_a_published_event(shared_server: FakeServer) -> None:
    publisher = FakeRedis(server=shared_server, decode_responses=True)
    subscriber = FakeRedis(server=shared_server, decode_responses=True)

    events = subscribe_events(subscriber, "t1")
    first_event = asyncio.ensure_future(events.__anext__())
    await asyncio.sleep(0.05)  # let the subscribe() call land before publishing
    await publish_event(publisher, "t1", {"type": "progress", "step": "Planning"})

    assert await first_event == {"type": "progress", "step": "Planning"}


async def test_subscribe_only_receives_its_own_thread_id(shared_server: FakeServer) -> None:
    publisher = FakeRedis(server=shared_server, decode_responses=True)
    subscriber = FakeRedis(server=shared_server, decode_responses=True)

    events = subscribe_events(subscriber, "t1")
    first_event = asyncio.ensure_future(events.__anext__())
    await asyncio.sleep(0.05)
    await publish_event(publisher, "other-thread", {"type": "progress", "step": "Ignored"})
    await publish_event(publisher, "t1", {"type": "progress", "step": "Mine"})

    assert await first_event == {"type": "progress", "step": "Mine"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/jobs/test_events.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdrops.jobs.events'`.

- [ ] **Step 3: Implement the pub/sub helpers**

Create `backend/src/agentdrops/jobs/__init__.py` (empty).

Create `backend/src/agentdrops/jobs/events.py`:

```python
"""Redis pub/sub transport for live turn events: the worker publishes, `/chat/stream` relays."""

import json
from collections.abc import AsyncIterator
from typing import Any

from redis.asyncio import Redis

_CHANNEL_PREFIX = "events:"


def _channel(thread_id: str) -> str:
    return f"{_CHANNEL_PREFIX}{thread_id}"


async def publish_event(redis: Redis, thread_id: str, event: dict[str, Any]) -> None:
    await redis.publish(_channel(thread_id), json.dumps(event))


async def subscribe_events(redis: Redis, thread_id: str) -> AsyncIterator[dict[str, Any]]:
    """Yield every event published on `thread_id`'s channel until the caller stops iterating."""
    pubsub = redis.pubsub()
    await pubsub.subscribe(_channel(thread_id))
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            yield json.loads(message["data"])
    finally:
        await pubsub.unsubscribe(_channel(thread_id))
        await pubsub.aclose()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/jobs/test_events.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/src/agentdrops/jobs backend/tests/unit/jobs
git commit -m "feat(backend): add Redis pub/sub helpers for live turn events"
```

---

### Task 5: Celery app

**Files:**
- Create: `backend/src/agentdrops/worker/__init__.py` (empty)
- Create: `backend/src/agentdrops/worker/celery_app.py`
- Test: `backend/tests/unit/worker/__init__.py` (empty)
- Test: `backend/tests/unit/worker/test_celery_app.py`

**Interfaces:**
- Consumes: `agentdrops.config.Settings`.
- Produces: `celery_app: Celery` (module-level, unconfigured broker/backend at import time); `def configure_celery(settings: Settings) -> None`.

`celery_app` is constructed with no broker/backend at import time deliberately: `Celery(...)`'s constructor needs no settings, so importing this module never requires a populated `.env`, matching `get_settings()`'s own lazy-construction pattern. `configure_celery` is called explicitly once at real process startup (API lifespan in Task 8, worker entrypoint in Task 7) — never at import time.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/worker/__init__.py` (empty file).

Create `backend/tests/unit/worker/test_celery_app.py`:

```python
from agentdrops.worker.celery_app import celery_app, configure_celery
from tests.unit.agents.conftest import make_settings


def test_configure_celery_sets_broker_and_backend_from_settings() -> None:
    settings = make_settings(redis_url="redis://example-host:6379/2")

    configure_celery(settings)

    assert celery_app.conf.broker_url == "redis://example-host:6379/2"
    assert celery_app.conf.result_backend == "redis://example-host:6379/2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/worker/test_celery_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdrops.worker'`.

- [ ] **Step 3: Implement the Celery app**

Create `backend/src/agentdrops/worker/__init__.py` (empty).

Create `backend/src/agentdrops/worker/celery_app.py`:

```python
"""Shared Celery application. Broker/backend are configured explicitly at process startup
(API lifespan, worker entrypoint) rather than at import time, so importing this module never
requires a populated environment — the same lazy-construction shape as `config.get_settings()`.
"""

from celery import Celery

from agentdrops.config import Settings

celery_app = Celery("agentdrops")


def configure_celery(settings: Settings) -> None:
    celery_app.conf.broker_url = settings.redis_url
    celery_app.conf.result_backend = settings.redis_url
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/worker/test_celery_app.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/agentdrops/worker/__init__.py backend/src/agentdrops/worker/celery_app.py backend/tests/unit/worker
git commit -m "feat(backend): add Celery app with lazily-configured Redis broker/backend"
```

---

### Task 6: Worker turn runner

**Files:**
- Create: `backend/src/agentdrops/worker/runner.py`
- Test: `backend/tests/unit/worker/test_runner.py`

**Interfaces:**
- Consumes: `ChatService` (existing, `service/chat_service.py`) constructed by the caller; `publish_event` (Task 4).
- Produces: `async def run_turn(chat_service: ChatService, thread_id: str, message: str, *, operation: str, redis: Redis) -> None` — Task 7's Celery task is the only caller.

Unlike the original design (which reimplemented the `astream` loop against a new Redis `JobStore`), this reuses `ChatService.run_turn`/`record_failure` verbatim — the exact class `api/v1/chat.py`'s routes called directly before this change. The only new behavior is publishing each yielded event to Redis instead of it being drained by an HTTP response generator.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/worker/test_runner.py`:

```python
import json
from collections.abc import AsyncIterator
from typing import Any

from fakeredis.aioredis import FakeRedis

from agentdrops.service.chat_service import ChatService
from agentdrops.worker.runner import run_turn


class _FakeSessions:
    def __init__(self) -> None:
        self.statuses: list[tuple[str, str]] = []

    async def touch(self, thread_id: str, *, title: str) -> None:
        return None

    async def set_status(self, thread_id: str, status: str, **_kwargs: object) -> None:
        self.statuses.append((thread_id, status))

    async def add_source(self, thread_id: str, topic: str, summary: str) -> None:
        return None


class _FakeAudit:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    async def record(self, thread_id: str, **kwargs: object) -> None:
        self.records.append({"thread_id": thread_id, **kwargs})


class _FakeGraph:
    """Streams a clarify turn immediately — enough to exercise the publish path without
    re-testing `ChatService.run_turn`'s own node-mapping logic (already covered by
    `tests/unit/api/v1/test_chat.py`)."""

    async def astream(
        self, _inputs: dict, _config: dict, _stream_mode: list[str]
    ) -> AsyncIterator[tuple[str, dict]]:
        yield (
            "updates",
            {
                "clarify_with_user": {
                    "needs_clarification": True,
                    "messages": [_Message("Which region should I focus on?")],
                }
            },
        )


class _Message:
    def __init__(self, content: str) -> None:
        self.content = content


class _FailingGraph:
    async def astream(
        self, _inputs: dict, _config: dict, _stream_mode: list[str]
    ) -> AsyncIterator[tuple[str, dict]]:
        raise RuntimeError("LLM provider unavailable")
        yield ("updates", {})  # pragma: no cover — makes this an async generator


async def _published(redis: FakeRedis, thread_id: str) -> list[dict[str, Any]]:
    raw = await redis.lrange(f"_test_published:{thread_id}", 0, -1)
    return [json.loads(r) for r in raw]


class _RecordingRedis(FakeRedis):
    """Records every `publish` call to a list key, so the test can assert on emitted events
    without a second pub/sub subscriber (already covered by `tests/unit/jobs/test_events.py`)."""

    async def publish(self, channel: str, message: str) -> int:  # type: ignore[override]
        await self.rpush(f"_test_published:{channel.removeprefix('events:')}", message)
        return 1


async def test_run_turn_publishes_every_event_from_chat_service() -> None:
    redis = _RecordingRedis(decode_responses=True)
    sessions = _FakeSessions()
    audit = _FakeAudit()
    chat_service = ChatService(_FakeGraph(), sessions, audit)  # type: ignore[arg-type]

    await run_turn(chat_service, "t1", "Research the EV market", operation="chat_stream", redis=redis)

    published = await _published(redis, "t1")
    assert published == [
        {"type": "clarify", "thread_id": "t1", "response": "Which region should I focus on?"}
    ]
    assert sessions.statuses == [("t1", "clarifying")]


async def test_run_turn_records_failure_and_publishes_error_on_exception() -> None:
    redis = _RecordingRedis(decode_responses=True)
    sessions = _FakeSessions()
    audit = _FakeAudit()
    chat_service = ChatService(_FailingGraph(), sessions, audit)  # type: ignore[arg-type]

    await run_turn(chat_service, "t1", "Research the EV market", operation="chat", redis=redis)

    published = await _published(redis, "t1")
    assert published == [
        {"type": "error", "thread_id": "t1", "message": "LLM provider unavailable"}
    ]
    assert sessions.statuses == [("t1", "failed")]
    assert audit.records == [
        {
            "thread_id": "t1",
            "operation": "chat",
            "status": "failed",
            "detail": {"error": "LLM provider unavailable"},
        }
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/worker/test_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdrops.worker.runner'`.

- [ ] **Step 3: Implement `run_turn`**

Create `backend/src/agentdrops/worker/runner.py`:

```python
"""Drives one chat turn inside a Celery worker via `ChatService`, relaying every event to Redis
pub/sub — the worker-process counterpart of `api/v1/chat.py`'s routes, which used to drive
`ChatService.run_turn` directly before execution moved off the request/response cycle.
"""

import logging

from redis.asyncio import Redis

from agentdrops.jobs.events import publish_event
from agentdrops.service.chat_service import ChatService

logger = logging.getLogger(__name__)


async def run_turn(
    chat_service: ChatService, thread_id: str, message: str, *, operation: str, redis: Redis
) -> None:
    try:
        async for event in chat_service.run_turn(thread_id, message, operation=operation):
            await publish_event(redis, thread_id, event)
    except Exception as exc:
        logger.exception("worker turn failed for thread_id=%s", thread_id)
        await chat_service.record_failure(thread_id, operation=operation, error=str(exc))
        await publish_event(
            redis, thread_id, {"type": "error", "thread_id": thread_id, "message": str(exc)}
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/worker/test_runner.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/src/agentdrops/worker/runner.py backend/tests/unit/worker/test_runner.py
git commit -m "feat(backend): add worker turn runner that relays ChatService events to Redis"
```

---

### Task 7: Celery task entrypoint

**Files:**
- Create: `backend/src/agentdrops/worker/tasks.py`
- Create: `backend/src/agentdrops/worker/app.py`
- Test: `backend/tests/unit/worker/test_tasks.py`

**Interfaces:**
- Consumes: `run_turn` (Task 6), `checkpointer` (Task 3), `build_market_researcher` (Task 3), `create_engine`/`create_session_factory` (`db/engine.py`, existing), `SessionStore`/`AuditLog` (`repository/`, existing), `ChatService` (`service/chat_service.py`, existing), `celery_app` (Task 5).
- Produces: `run_turn_task` (a `@celery_app.task`, callable directly in tests as `run_turn_task(thread_id, message, operation)`, or via `.delay(thread_id, message, operation)` in production); `celery_app` re-exported from `worker/app.py` as the module the `celery` CLI points `-A` at.

Every dependency the task needs (`create_engine`, `SessionStore`, `AuditLog`, `ChatService`, `build_market_researcher`, `checkpointer`) already exists and is already tested in isolation — this task is pure wiring, constructing one of each per task invocation (mirroring how `agentdrops/main.py`'s lifespan constructs one of each per process) and tearing them down after.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/worker/test_tasks.py`:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fakeredis.aioredis import FakeRedis
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

import agentdrops.worker.tasks as tasks_module
from agentdrops.config import Settings
from tests.unit.agents.conftest import make_settings


class _FakeGraph:
    async def astream(
        self, _inputs: dict, _config: dict, _stream_mode: list[str]
    ) -> AsyncIterator[tuple[str, dict]]:
        yield ("updates", {"final_report_generation": {"final_report": "# Report"}})


class _FakeEngine:
    async def dispose(self) -> None:
        return None


class _FakeSessionStore:
    async def touch(self, thread_id: str, *, title: str) -> None:
        return None

    async def set_status(self, thread_id: str, status: str, **_kwargs: object) -> None:
        return None

    async def add_source(self, thread_id: str, topic: str, summary: str) -> None:
        return None


class _FakeAuditLog:
    async def record(self, thread_id: str, **kwargs: object) -> None:
        return None


@pytest.fixture(autouse=True)
def patch_worker_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks_module, "get_settings", lambda: make_settings())
    monkeypatch.setattr(tasks_module, "create_engine", lambda settings: _FakeEngine())
    monkeypatch.setattr(tasks_module, "create_session_factory", lambda engine: object())
    monkeypatch.setattr(tasks_module, "SessionStore", lambda session_factory: _FakeSessionStore())
    monkeypatch.setattr(tasks_module, "AuditLog", lambda session_factory: _FakeAuditLog())
    monkeypatch.setattr(
        tasks_module,
        "build_market_researcher",
        lambda settings, client, checkpointer: _FakeGraph(),
    )

    @asynccontextmanager
    async def fake_checkpointer(_settings: Settings) -> AsyncIterator[BaseCheckpointSaver[Any]]:
        yield InMemorySaver()

    monkeypatch.setattr(tasks_module, "checkpointer", fake_checkpointer)
    monkeypatch.setattr(
        tasks_module.Redis,
        "from_url",
        staticmethod(lambda *_a, **_k: FakeRedis(decode_responses=True)),
    )


def test_run_turn_task_drives_a_turn_to_completion() -> None:
    """A plain (non-async) test: `run_turn_task` calls `asyncio.run()` internally, which raises
    if called from within pytest-asyncio's own event loop, so this must not be `async def`."""
    tasks_module.run_turn_task("t1", "Research the EV charging market", "chat_stream")

    # No exception means `_execute` ran end to end; `ChatService`'s own event mapping and
    # `run_turn`'s publish behavior are already covered by `tests/unit/worker/test_runner.py`
    # and `tests/unit/api/v1/test_chat.py` — this test only proves the wiring works.
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/worker/test_tasks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdrops.worker.tasks'`.

- [ ] **Step 3: Implement the task**

Create `backend/src/agentdrops/worker/tasks.py`:

```python
"""Celery task entrypoint: bridges Celery's synchronous task execution into the async
graph/service/Redis stack. This is the only place `asyncio.run` appears, since everything it
calls into (the graph, repositories, services, pub/sub) is async."""

import asyncio
from typing import Any

import httpx
from redis.asyncio import Redis

from agentdrops.agents.checkpointer import checkpointer
from agentdrops.agents.graph import build_market_researcher
from agentdrops.config import Settings, get_settings
from agentdrops.db.engine import create_engine, create_session_factory
from agentdrops.repository.audit import AuditLog
from agentdrops.repository.sessions import SessionStore
from agentdrops.service.chat_service import ChatService
from agentdrops.worker.celery_app import celery_app
from agentdrops.worker.runner import run_turn


async def _execute(thread_id: str, message: str, operation: str, settings: Settings) -> None:
    redis: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        engine = create_engine(settings)
        try:
            async with (
                httpx.AsyncClient(timeout=30.0) as client,
                checkpointer(settings) as saver,
            ):
                session_factory = create_session_factory(engine)
                graph = build_market_researcher(settings, client, saver)
                sessions = SessionStore(session_factory)
                audit = AuditLog(session_factory)
                chat_service = ChatService(graph, sessions, audit)
                await run_turn(chat_service, thread_id, message, operation=operation, redis=redis)
        finally:
            await engine.dispose()
    finally:
        await redis.aclose()


@celery_app.task(name="agentdrops.run_turn")
def run_turn_task(thread_id: str, message: str, operation: str) -> None:
    asyncio.run(_execute(thread_id, message, operation, get_settings()))
```

Create `backend/src/agentdrops/worker/app.py` (the module the `celery` CLI points at — see Task 9):

```python
"""Worker process entrypoint: `celery -A agentdrops.worker.app worker` imports this module.

Configuring the Celery app and importing the task module (to register it) both need to happen
here rather than in `celery_app.py`, so that module can stay import-safe without a populated
environment (see its docstring) while this one — only ever run by the `celery` CLI in a real
worker process — is where settings are actually required.
"""

from agentdrops.config import get_settings
from agentdrops.worker.celery_app import celery_app, configure_celery
from agentdrops.worker.tasks import run_turn_task  # noqa: F401  (registers the task)

configure_celery(get_settings())

__all__ = ["celery_app"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/worker/test_tasks.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite and typecheck**

Run: `pytest && mypy src`
Expected: both PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/agentdrops/worker/tasks.py backend/src/agentdrops/worker/app.py backend/tests/unit/worker/test_tasks.py
git commit -m "feat(backend): add Celery task entrypoint and worker process bootstrap"
```

---

### Task 8: Make `/chat` and `/chat/stream` enqueue instead of running inline

**Files:**
- Modify: `backend/src/agentdrops/api/v1/schema.py`
- Modify: `backend/src/agentdrops/api/v1/chat.py`
- Modify: `backend/tests/unit/api/v1/conftest.py`
- Modify: `backend/tests/unit/api/v1/test_chat.py`

**Interfaces:**
- Consumes: `app.state.sessions` (`SessionStore`, exposed in Task 3), a new `app.state.redis` (this task), `run_turn_task` (Task 7), `subscribe_events` (Task 4).
- Produces: `ChatQueuedResponse` (new schema, replaces `ChatResponse` as `/chat`'s response body).

This is the task that flips the switch: `/chat` and `/chat/stream` stop calling `ChatService.run_turn` and start enqueuing `run_turn_task`. `/research/{thread_id}` and `/research/sessions` need no changes here — Task 2 already made them correctly reflect `"queued"`/`"failed"` from the session row, and `"running"`/`"clarifying"`/`"done"` from the now-shared Postgres checkpointer (Task 3).

- [ ] **Step 1: Update `api/v1/schema.py`**

Replace `ChatResponse` (used only by `/chat`, which no longer returns a full result inline):

```python
class ChatResponse(BaseModel):
    """One chat turn's result: which thread it belongs to, the reply, and the report once ready."""

    thread_id: str
    response: str
    is_followup: bool
    report: str | None = None
```

with:

```python
class ChatQueuedResponse(BaseModel):
    """Acknowledgement that one chat turn was enqueued; poll GET /research/{thread_id} or use
    /chat/stream to observe it. Replaces `ChatResponse`, which returned the turn's full result
    inline — no longer possible once the turn runs in a background worker."""

    thread_id: str
    status: Literal["queued"] = "queued"
```

- [ ] **Step 2: Add `app.state.redis` and expose the Celery task/config in `agentdrops/main.py`**

Add imports:
```python
from redis.asyncio import Redis
from agentdrops.worker.celery_app import configure_celery
```

In the lifespan (inside the same `try` block that now builds `checkpointer`/`graph`/`sessions`), add, right after `configure_observability`:

```python
    configure_celery(settings)
```

And construct/close a Redis client alongside the engine:

```python
    try:
        engine = create_engine(settings)
        redis: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            async with (
                httpx.AsyncClient(timeout=30.0) as client,
                checkpointer(settings) as saver,
            ):
                session_factory = create_session_factory(engine)
                graph = build_market_researcher(settings, client, saver)
                sessions = SessionStore(session_factory)
                audit = AuditLog(session_factory)
                app.state.engine = engine
                app.state.redis = redis
                app.state.sessions = sessions
                app.state.audit = audit
                app.state.chat_service = ChatService(graph, sessions, audit)
                app.state.research_service = ResearchService(graph, sessions)
                app.state.sessions_service = SessionsService(sessions)
                yield
        finally:
            await redis.aclose()
            await engine.dispose()
    finally:
        providers.shutdown()
```

- [ ] **Step 3: Rewrite `api/v1/chat.py`**

Replace the full contents of `backend/src/agentdrops/api/v1/chat.py`:

```python
"""Chat endpoints: enqueue one research turn, either acknowledged immediately or observed live
via SSE. Execution itself happens in a Celery worker (`agentdrops.worker.tasks.run_turn_task`) —
see `agentdrops/worker/runner.py` for the worker-side counterpart of what this module used to do
directly through `ChatService.run_turn`.
"""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis

from agentdrops.api.v1.schema import ChatQueuedResponse, ChatRequest
from agentdrops.config.constants import CHAT_TITLE_MAX_LENGTH
from agentdrops.jobs.events import subscribe_events
from agentdrops.repository.sessions import SessionRecord, SessionStore
from agentdrops.types.response import SuccessResponse
from agentdrops.worker.tasks import run_turn_task

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

_TERMINAL_STATUSES = {"done", "clarifying", "failed"}
_TERMINAL_EVENT_TYPES = {"clarify", "done", "error"}


def _sse(payload: dict[str, Any]) -> str:
    """Format one SSE event as a `data:` line, per the text/event-stream framing."""
    return f"data: {json.dumps(payload)}\n\n"


def _terminal_event_from_session(thread_id: str, session: SessionRecord) -> dict[str, Any] | None:
    """Reconstruct the terminal SSE event from a session record already settled by the time
    `/chat/stream` subscribes — the race window between enqueueing and subscribing."""
    if session.status == "done":
        return {"type": "done", "thread_id": thread_id, "report": session.report}
    if session.status == "clarifying":
        return {
            "type": "clarify",
            "thread_id": thread_id,
            "response": session.clarify_question or "",
        }
    if session.status == "failed":
        return {"type": "error", "thread_id": thread_id, "message": session.error or "Research failed"}
    return None


@router.post(
    "/chat",
    response_model=SuccessResponse[ChatQueuedResponse],
    status_code=status.HTTP_200_OK,
    summary="Enqueue a chat turn",
)
async def chat(request: Request, body: ChatRequest) -> SuccessResponse[ChatQueuedResponse]:
    """Enqueue one chat turn for background execution; poll GET /research/{thread_id} for the
    result, or use /chat/stream instead to observe it live."""
    thread_id = body.thread_id or str(uuid.uuid4())
    sessions: SessionStore = request.app.state.sessions
    await sessions.touch(thread_id, title=body.message[:CHAT_TITLE_MAX_LENGTH])
    run_turn_task.delay(thread_id, body.message, "chat")
    return SuccessResponse(data=ChatQueuedResponse(thread_id=thread_id))


@router.post(
    "/chat/stream",
    status_code=status.HTTP_200_OK,
    summary="Advance a chat turn, streamed via SSE",
)
async def chat_stream(request: Request, body: ChatRequest) -> StreamingResponse:
    """Enqueue one chat turn, then stream its progress/source events as the worker runs it, via
    SSE — event shapes unchanged from before this turn ran in a background worker:

    - `{"type": "progress", "step": str, "detail"?: str}` — a top-level stage started, or (from
      inside the supervisor) one delegated research topic began.
    - `{"type": "source", "topic": str, "summary": str}` — one delegated topic finished.
    - `{"type": "clarify", "thread_id": str, "response": str}` — terminal: the agent needs more
      information before it can research; the turn ends here.
    - `{"type": "done", "thread_id": str, "report": str}` — terminal: the final report is ready.
    - `{"type": "error", "thread_id": str, "message": str}` — terminal: the run failed.
    """
    thread_id = body.thread_id or str(uuid.uuid4())
    sessions: SessionStore = request.app.state.sessions
    redis: Redis = request.app.state.redis
    await sessions.touch(thread_id, title=body.message[:CHAT_TITLE_MAX_LENGTH])
    run_turn_task.delay(thread_id, body.message, "chat_stream")

    async def events() -> AsyncIterator[str]:
        # The task may have already finished by the time we get here (enqueue-then-subscribe
        # race) — check the session record first rather than subscribing blind and hanging.
        session = await sessions.get(thread_id)
        if session is not None and session.status in _TERMINAL_STATUSES:
            terminal = _terminal_event_from_session(thread_id, session)
            if terminal is not None:
                yield _sse(terminal)
                return
        try:
            async for event in subscribe_events(redis, thread_id):
                yield _sse(event)
                if event.get("type") in _TERMINAL_EVENT_TYPES:
                    return
        except Exception as exc:
            # e.g. the Redis connection drops mid-stream — surface it to the client instead of
            # letting the SSE response hang open with no further events ever arriving.
            logger.exception("chat/stream subscription failed for thread_id=%s", thread_id)
            yield _sse({"type": "error", "thread_id": thread_id, "message": str(exc)})

    return StreamingResponse(events(), media_type="text/event-stream")
```

- [ ] **Step 4: Update `tests/unit/api/v1/conftest.py`'s `client`/`failing_client` fixtures**

The fixtures currently patch `main_module.build_market_researcher` and the DB layer (Task 3 already added the `checkpointer` patch). Now also patch `run_turn_task.delay` and the `Redis.from_url` construction so `/chat`/`/chat/stream` never touch a real broker, and share one `FakeRedis`/`FakeServer` so a test can simulate "the worker" publishing events the same way `tests/unit/worker/test_runner.py` does directly.

Add imports:
```python
from fakeredis import FakeServer
from fakeredis.aioredis import FakeRedis
```

Add near the top of the fixture section:
```python
class _FakeDelay:
    """Stand-in for Celery's `.delay(...)`: records calls instead of touching a real broker."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, thread_id: str, message: str, operation: str) -> None:
        self.calls.append((thread_id, message, operation))
```

Change the `client` fixture (and mirror the same additions in `failing_client`):

```python
@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(main_module, "get_settings", lambda: make_settings())
    monkeypatch.setattr(main_module, "configure_celery", lambda settings: None)
    monkeypatch.setattr(
        main_module, "build_market_researcher", lambda settings, client, checkpointer: _FakeGraph()
    )
    _patch_db(monkeypatch)
    shared_server = FakeServer()
    monkeypatch.setattr(
        main_module.Redis,
        "from_url",
        staticmethod(lambda *_a, **_k: FakeRedis(server=shared_server, decode_responses=True)),
    )
    fake_delay = _FakeDelay()
    monkeypatch.setattr(main_module.run_turn_task, "delay", fake_delay)
    with TestClient(main_module.app) as test_client:
        test_client.fake_delay = fake_delay  # type: ignore[attr-defined]
        yield test_client
```

(`main_module.run_turn_task` — `run_turn_task` is imported into `api/v1/chat.py`, not `main.py`; monkeypatch it via `agentdrops.api.v1.chat.run_turn_task` instead. Import `agentdrops.api.v1.chat as chat_module` at the top of `conftest.py` and patch `chat_module.run_turn_task.delay` there. Likewise `Redis` is used both in `main.py` — for `app.state.redis` — and in `api/v1/chat.py` only as a type annotation, so patching `main_module.Redis.from_url` is sufficient since it's the same class object regardless of which module imported it.)

- [ ] **Step 5: Update `tests/unit/api/v1/test_chat.py`**

The existing tests assert on the *old*, synchronous behavior (full report/clarify text returned immediately from `/chat`, and `/chat/stream`'s SSE body containing the whole turn's events in one response). Both assumptions are now wrong: `/chat` returns `{"status": "queued"}` immediately, and `/chat/stream`'s events only arrive if something (the "worker", simulated in tests) publishes them or the session is already terminal.

Replace `test_chat_first_turn_asks_for_clarification` and `test_chat_follow_up_returns_final_report`:

```python
def test_chat_enqueues_and_returns_queued_immediately(client: TestClient) -> None:
    response = client.post("/v1/chat", json={"message": "Research the EV charging market"})

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["status"] == "queued"
    thread_id = body["thread_id"]
    assert client.fake_delay.calls == [  # type: ignore[attr-defined]
        (thread_id, "Research the EV charging market", "chat")
    ]

    status_response = client.get(f"/v1/research/{thread_id}")
    assert status_response.json()["data"]["status"] == "queued"
```

Replace `test_chat_stream_first_turn_emits_clarify_event` and `test_chat_stream_second_turn_emits_progress_source_and_done` — these depended on the fake graph actually running inline, which no longer happens. Use the session-record race-reconstruction path instead (already covered end-to-end by `run_turn`'s own tests in `tests/unit/worker/test_runner.py`; these tests are about the *endpoint's* race handling, not `ChatService`'s node-mapping):

```python
async def test_chat_stream_reconstructs_clarify_event_if_already_clarifying(
    client: TestClient,
) -> None:
    sessions = client.app.state.sessions
    await sessions.touch("t-clarify", title="Research the EV charging market")
    await sessions.set_status(
        "t-clarify", "clarifying", clarify_question="Which region should I focus on?"
    )

    response = client.post(
        "/v1/chat/stream", json={"thread_id": "t-clarify", "message": "Research the EV market"}
    )

    events = parse_sse(response.text)
    assert events == [
        {
            "type": "clarify",
            "thread_id": "t-clarify",
            "response": "Which region should I focus on?",
        }
    ]


async def test_chat_stream_reconstructs_done_event_if_already_done(client: TestClient) -> None:
    sessions = client.app.state.sessions
    await sessions.touch("t-done", title="Research the EV charging market")
    await sessions.set_status("t-done", "done", report="# EV Charging Market Report")

    response = client.post(
        "/v1/chat/stream", json={"thread_id": "t-done", "message": "Focus on the EU"}
    )

    events = parse_sse(response.text)
    assert events == [
        {"type": "done", "thread_id": "t-done", "report": "# EV Charging Market Report"}
    ]


async def test_chat_stream_reconstructs_error_event_if_already_failed(client: TestClient) -> None:
    sessions = client.app.state.sessions
    await sessions.touch("t-failed", title="Research the EV charging market")
    await sessions.set_status("t-failed", "failed", error="LLM provider unavailable")

    response = client.post(
        "/v1/chat/stream", json={"thread_id": "t-failed", "message": "Research the EV market"}
    )

    events = parse_sse(response.text)
    assert events == [
        {"type": "error", "thread_id": "t-failed", "message": "LLM provider unavailable"}
    ]
```

Replace `test_chat_persists_sources_same_as_chat_stream` (it drove the graph inline via two `/chat` calls — no longer possible) with a direct assertion against the fake session store, since sources are now only ever written by the worker (already covered by `tests/unit/worker/test_runner.py`) — drop this test; note in the commit message that its coverage moved to the worker test.

Replace `test_chat_returns_502_and_marks_session_failed_on_graph_error` and `test_chat_stream_emits_error_event_and_marks_session_failed` — `/chat`/`/chat/stream` no longer call `ChatService.run_turn` directly, so they can't fail from a graph error anymore (that happens in the worker, covered by `tests/unit/worker/test_runner.py::test_run_turn_records_failure_and_publishes_error_on_exception`). Replace both with the new subscription-failure test:

```python
async def test_chat_stream_emits_error_event_if_subscription_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dropped Redis connection mid-subscribe must surface as an `error` SSE event, not hang
    the response open with nothing ever arriving."""
    import agentdrops.api.v1.chat as chat_module

    async def _broken_subscribe(_redis: Any, _thread_id: str) -> AsyncIterator[dict[str, Any]]:
        raise ConnectionError("connection to Redis lost")
        yield {}  # pragma: no cover — makes this an async generator; never reached

    monkeypatch.setattr(chat_module, "subscribe_events", _broken_subscribe)

    response = client.post(
        "/v1/chat/stream", json={"message": "Research the EV charging market"}
    )

    events = parse_sse(response.text)
    assert events == [
        {
            "type": "error",
            "thread_id": events[0]["thread_id"],
            "message": "connection to Redis lost",
        }
    ]
```

Add the necessary imports at the top of `test_chat.py`:
```python
from collections.abc import AsyncIterator
from typing import Any

import pytest
```

Remove the `failing_client` fixture's usages from this file entirely (no test needs it anymore — the fixture itself can stay in `conftest.py` unused for now, or be removed if nothing else references it; check `test_research.py`/`test_sessions.py` before deleting it).

- [ ] **Step 6: Run the tests**

Run: `pytest tests/unit/api/v1/test_chat.py -v`
Expected: PASS.

- [ ] **Step 7: Run the full suite, lint, and typecheck**

Run: `pytest && ruff check . && mypy src`
Expected: all three PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/src/agentdrops/api/v1/schema.py \
        backend/src/agentdrops/api/v1/chat.py \
        backend/src/agentdrops/main.py \
        backend/tests/unit/api/v1/conftest.py \
        backend/tests/unit/api/v1/test_chat.py
git commit -m "feat(backend): make /chat and /chat/stream enqueue Celery tasks instead of running inline"
```

---

### Task 9: Worker process entrypoint (`make worker`)

**Files:**
- Modify: `backend/Makefile`

**Interfaces:**
- Consumes: `agentdrops.worker.app:celery_app` (Task 7).
- Produces: `make worker` target, following the same shape as the existing `make run` target.

This repo runs the API by invoking `uvicorn` directly via `make run` — there's no Dockerfile or app-level `docker-compose.yml` service (compose only runs infra: postgres/redis/minio). A worker gets the same treatment: a Makefile target, not new container infrastructure.

- [ ] **Step 1: Add the `worker` target**

In `backend/Makefile`, add a new target right after `run:` (before `dev:`):

```makefile
worker: infra-up ## Start a Celery worker processing background research turns
	@$(call banner,Starting Agentdrops worker)
	@$(call log_info,python=$$($(PYTHON) --version 2>&1) git=$$(git rev-parse --short HEAD 2>/dev/null || echo n/a))
	@if [ ! -f .env ]; then \
		$(call log_warn,.env not found — run \`make env\` first (Settings will fail fast without it)); \
	fi
	@$(VENV)/bin/celery -A agentdrops.worker.app worker --loglevel=info \
		|| ($(call log_err,worker exited non-zero); exit 1)
```

Update the `.PHONY` line:

```makefile
.PHONY: help venv install env infra-up infra-down infra-restart infra-ps infra-logs infra-reset \
        run dev worker stop test test-file lint lint-fix format typecheck check clean doctor
```

- [ ] **Step 2: Verify the target resolves correctly**

Run: `cd backend && make -n worker`
Expected: prints the `celery -A agentdrops.worker.app worker --loglevel=info` command line (dry-run, not executed) with no Makefile syntax errors.

- [ ] **Step 3: Commit**

```bash
git add backend/Makefile
git commit -m "chore(backend): add make worker target for the Celery worker process"
```

---

### Task 10: Mirror the `queued` status in the frontend

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/app/page.tsx`

**Interfaces:**
- Consumes: `ResearchStatusResponse`/`SessionSummary`'s widened `status` (Task 2 added `"queued"`).
- Produces: `ResearchStatusValue` gains `"queued"`; `selectSession`'s live-status check treats `"queued"` as still in-flight, same as `"clarifying"`/`"running"`.

`research_brief` stays in the schema and in `frontend/src/lib/types.ts` — unlike the original (pre-reconciliation) draft of this plan, `ResearchService.get_status` still reads it from the LangGraph checkpoint (`research_service.py:42`), and that checkpoint is now Postgres-backed and shared across processes (Task 3), so it keeps working unchanged.

- [ ] **Step 1: Update `types.ts`**

Change:

```typescript
export type ResearchStatusValue = "clarifying" | "running" | "done" | "failed";
```

to:

```typescript
export type ResearchStatusValue = "queued" | "clarifying" | "running" | "done" | "failed";
```

- [ ] **Step 2: Treat `"queued"` as still-in-flight in `selectSession`**

In `frontend/src/app/page.tsx`, find the block in `selectSession` that reads:

```typescript
      setPhase(status.status === "clarifying" ? "clarifying" : "running");
      if (status.status === "clarifying" || status.status === "running") {
        pollUntilSettled(session.id, token);
      }
```

Change to:

```typescript
      setPhase(status.status === "clarifying" ? "clarifying" : "running");
      if (
        status.status === "clarifying" ||
        status.status === "running" ||
        status.status === "queued"
      ) {
        pollUntilSettled(session.id, token);
      }
```

(`pollUntilSettled` itself already keeps polling by default for anything other than `"done"`/`"failed"` — only `selectSession`'s initial branch needed the new value added.)

- [ ] **Step 3: Typecheck and lint the frontend**

Run: `cd frontend && npm run lint`
Expected: PASS.

Run: `npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/app/page.tsx
git commit -m "fix(frontend): treat queued sessions as still in-flight when reopened"
```

---

## Manual Verification (not automated — requires real Postgres/Redis)

After all tasks land, the unit-test suite proves the wiring is correct in isolation, but the following needs a human running `docker compose up -d`, `alembic upgrade head`, and both processes:

1. `make env` (if `.env` doesn't exist yet), fill in real API keys.
2. `make infra-up` (postgres/redis/minio).
3. `cd backend && alembic upgrade head` (applies migration `0002`).
4. Terminal A: `make run` (FastAPI on :8001).
5. Terminal B: `make worker` (Celery worker).
6. From the frontend (`npm run dev`), submit a research topic and confirm: the sidebar shows "queued" briefly, progress steps stream live once the worker picks it up, a clarifying question round-trips correctly, the final report renders, and reopening a session from the sidebar mid-run resumes via polling.
7. Restart the worker process mid-run (kill `make worker`, restart it) and confirm a *new* turn on the same thread still works — this is the check that the Postgres checkpoint actually survived a worker-process restart, which `InMemorySaver` never could.
