# Background Workers + Redis Job State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move LangGraph execution out of the FastAPI request/response cycle and into Celery worker processes, with Redis as the shared job-status/pub-sub layer and Postgres as the LangGraph checkpointer, per `docs/superpowers/specs/2026-07-21-background-workers-redis-design.md`.

**Architecture:** FastAPI becomes thin — `/chat` and `/chat/stream` write a `queued` job record to Redis and enqueue a Celery task, never calling `graph.astream` themselves. A separate Celery worker process (started via `make worker`) builds the graph fresh per task, drives it with a Postgres-backed checkpointer, and publishes every event to a Redis pub/sub channel while updating a Redis job record that the API reads back for status/history. `/chat/stream` relays that pub/sub channel as SSE, so the wire format the frontend already parses is unchanged.

**Tech Stack:** Celery 5.x (broker+backend=Redis), `redis` (async client), `langgraph-checkpoint-postgres` + `psycopg[binary,pool]`, `fakeredis` (dev/test only).

## Global Constraints

- No network in unit tests: Celery/Redis/Postgres interactions are tested against `fakeredis.aioredis.FakeRedis` or in-process fakes, never a real broker/DB (per `backend/tests/unit/agents/conftest.py`'s existing "no network" convention).
- `pytest` config is `asyncio_mode = "auto"`, `pythonpath = ["src"]` — `async def test_*` functions need no `@pytest.mark.asyncio` decorator, but a test that must call `asyncio.run()` itself (bridging into Celery's sync task body) MUST be a plain `def test_*`, not `async def`, or it will hit `RuntimeError: asyncio.run() cannot be called from a running event loop`.
- `mypy src` runs in strict mode — every new function needs full type annotations.
- `ruff check .` lint rules: `E, F, I, UP, B, SIM, ASYNC` — imports sorted, no unused imports, async-specific checks (e.g. no blocking calls disguised as async).
- Existing conventions to follow, not restructure: src-layout under `backend/src/agentdrops/`, `tests/unit/` mirrors `src/`, one `Makefile` target per process today (`make run` for the API) — this plan adds `make worker` alongside it rather than introducing Docker/compose app services that don't exist in this repo today.
- `redis_url`/`database_url` are already required `Settings` fields (`backend/src/agentdrops/config.py:43-44`) — no new required settings are introduced.

---

### Task 1: Add background-job dependencies

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/.env.example`
- Modify: `backend/tests/unit/agents/conftest.py:14` (fix `database_url` format)

**Interfaces:**
- Produces: `celery`, `redis` (async client at `redis.asyncio.Redis`), `langgraph-checkpoint-postgres` (`langgraph.checkpoint.postgres.aio.AsyncPostgresSaver`), `psycopg[binary,pool]` as runtime deps; `fakeredis` as a dev/test dep — all subsequent tasks import these.

`langgraph-checkpoint-postgres`'s `AsyncPostgresSaver` uses `psycopg` (v3) connection strings (`postgresql://user:pass@host:port/db`), **not** SQLAlchemy's `postgresql+asyncpg://` dialect form. `database_url` is declared in `Settings` today but unused anywhere in `src/` — this task is what starts using it, so this is the point to fix its format before anything depends on the wrong one.

- [ ] **Step 1: Add the new dependencies to `pyproject.toml`**

Edit `backend/pyproject.toml`'s `dependencies` list (after the `openinference-instrumentation-langchain` line):

```toml
    "openinference-instrumentation-langchain>=0.1.29",
    "celery>=5.4",
    "redis>=5.0",
    "langgraph-checkpoint-postgres>=3.0",
    "psycopg[binary,pool]>=3.1",
]
```

And add `fakeredis` to the `dev` extra:

```toml
dev = [
    "agentdrops[providers]",
    "pytest>=8.2",
    "pytest-asyncio>=0.23",
    "respx>=0.21",
    "fakeredis>=2.20",
    "ruff>=0.5",
    "mypy>=1.10",
]
```

Celery ships incomplete/no inline type stubs, so `mypy src --strict` will fail on `import celery` once Task 5 adds real code importing it, unless it's added to the existing `ignore_missing_imports` override list. Add it now while `pyproject.toml` is already open — in `[[tool.mypy.overrides]]`, change:

```toml
[[tool.mypy.overrides]]
module = [
    "langchain.*",
    "langchain_core.*",
    "langchain_openai.*",
    "langchain_anthropic.*",
    "langchain_google_genai.*",
    "langgraph.*",
]
ignore_missing_imports = true
```

to:

```toml
[[tool.mypy.overrides]]
module = [
    "langchain.*",
    "langchain_core.*",
    "langchain_openai.*",
    "langchain_anthropic.*",
    "langchain_google_genai.*",
    "langgraph.*",
    "celery.*",
]
ignore_missing_imports = true
```

(`langgraph-checkpoint-postgres` is imported as `langgraph.checkpoint.postgres.*`, already covered by the existing `langgraph.*` glob; `redis` ships its own inline types (`py.typed`) since v4.2, so it needs no override.)

- [ ] **Step 2: Fix `DATABASE_URL`'s format in `.env.example`**

In `backend/.env.example`, change:

```
DATABASE_URL=postgresql+asyncpg://agentdrops:agentdrops@localhost:5432/agentdrops
```

to:

```
# Plain psycopg conninfo (no +asyncpg dialect suffix) — langgraph-checkpoint-postgres uses
# psycopg directly, not SQLAlchemy.
DATABASE_URL=postgresql://agentdrops:agentdrops@localhost:5432/agentdrops
```

- [ ] **Step 3: Fix the matching test fixture default**

In `backend/tests/unit/agents/conftest.py:14`, change:

```python
        "database_url": "postgresql+asyncpg://u:p@localhost:5432/agentdrops",
```

to:

```python
        "database_url": "postgresql://u:p@localhost:5432/agentdrops",
```

- [ ] **Step 4: Install and verify the imports**

Run: `cd backend && source .venv/bin/activate && pip install -e ".[dev]"`
Expected: installs successfully, no dependency conflicts.

Run:
```bash
python -c "import celery, redis, fakeredis; from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver; print('ok')"
```
Expected: prints `ok`.

- [ ] **Step 5: Run the existing suite to confirm nothing broke**

Run: `pytest`
Expected: PASS (same pass count as before this task — this step only touches config/deps).

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/.env.example backend/tests/unit/agents/conftest.py
git commit -m "chore(backend): add celery/redis/postgres-checkpoint deps for background workers"
```

---

### Task 2: Make the LangGraph checkpointer injectable

**Files:**
- Modify: `backend/src/agentdrops/agents/graph.py`
- Test: `backend/tests/unit/agents/test_graph.py` (new file)

**Interfaces:**
- Consumes: nothing new.
- Produces: `build_market_researcher(settings: Settings, client: httpx.AsyncClient, checkpointer: BaseCheckpointSaver[Any]) -> CompiledStateGraph[Any, Any, Any, Any]` — the `checkpointer` param is new; every caller (Task 7's worker bootstrap, this task's test) must now pass one explicitly. `InMemorySaver` is no longer constructed inside this function.

Today `build_market_researcher` hardcodes `graph.compile(checkpointer=InMemorySaver())` (`graph.py:80`), which is exactly what makes graph state process-bound. The worker (Task 7) needs to pass a Postgres-backed checkpointer instead; tests need to keep passing a plain `InMemorySaver()` so they don't need a real Postgres connection.

- [ ] **Step 1: Write the failing test**

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

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/agents/test_graph.py -v`
Expected: FAIL — `build_market_researcher() takes 2 positional arguments but 3 were given`.

- [ ] **Step 3: Add the `checkpointer` parameter**

In `backend/src/agentdrops/agents/graph.py`:

Remove the import at line 6:
```python
from langgraph.checkpoint.memory import InMemorySaver
```

Add instead:
```python
from langgraph.checkpoint.base import BaseCheckpointSaver
```

Change the function signature (line 22-24) from:
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

Change the last line (line 80) from:
```python
    return graph.compile(checkpointer=InMemorySaver())
```
to:
```python
    return graph.compile(checkpointer=checkpointer)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/agents/test_graph.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/agentdrops/agents/graph.py backend/tests/unit/agents/test_graph.py
git commit -m "feat(backend): make build_market_researcher's checkpointer injectable"
```

---

### Task 3: Redis-backed `JobStore`

**Files:**
- Create: `backend/src/agentdrops/jobs/__init__.py` (empty)
- Create: `backend/src/agentdrops/jobs/store.py`
- Test: `backend/tests/unit/jobs/__init__.py` (empty)
- Test: `backend/tests/unit/jobs/test_store.py`

**Interfaces:**
- Consumes: `redis.asyncio.Redis` (or `fakeredis.aioredis.FakeRedis`, same interface) instance, constructed by the caller.
- Produces:
  - `JobStatus = Literal["queued", "running", "clarifying", "done", "failed"]`
  - `class JobRecord(TypedDict)`: `thread_id: str`, `title: str`, `created_at: str`, `status: JobStatus`, `report: str | None`, `sources: list[dict[str, str]]`, `error: str | None`, `clarify_question: str | None`
  - `class JobStore`: `__init__(self, redis: Redis) -> None`; `async def touch(self, thread_id: str, *, title: str) -> JobRecord`; `async def set_status(self, thread_id: str, status: JobStatus, *, report: str | None = None, error: str | None = None, clarify_question: str | None = None) -> None`; `async def add_source(self, thread_id: str, topic: str, summary: str) -> None`; `async def get(self, thread_id: str) -> JobRecord | None`; `async def list_recent(self) -> list[JobRecord]`

This replaces `api/sessions.py`'s in-memory `SessionStore` (deleted in Task 8) as the single source of truth for job status, consolidating today's split between the in-memory `SessionStore` (only tracked `failed`) and the LangGraph checkpoint (tracked everything else). Each job is stored as one JSON-serialized Redis string at `job:{thread_id}` (simpler and safer for a nested `sources` list than Redis's native `HASH` type, which only holds flat string fields) plus a Redis sorted set `jobs:index` (`thread_id` scored by `created_at` epoch) so `list_recent` doesn't need `KEYS`/`SCAN`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/jobs/__init__.py` (empty file).

Create `backend/tests/unit/jobs/test_store.py`:

```python
from fakeredis.aioredis import FakeRedis

from agentdrops.jobs.store import JobStore


async def _store() -> JobStore:
    redis = FakeRedis(decode_responses=True)
    return JobStore(redis)


async def test_touch_creates_a_queued_record() -> None:
    jobs = await _store()

    record = await jobs.touch("t1", title="Research the EV market")

    assert record["status"] == "queued"
    assert record["title"] == "Research the EV market"
    assert record["report"] is None
    assert record["sources"] == []
    assert (await jobs.get("t1")) == record


async def test_touch_is_a_noop_on_the_second_call() -> None:
    jobs = await _store()
    first = await jobs.touch("t1", title="Research the EV market")

    second = await jobs.touch("t1", title="A different title")

    assert second == first


async def test_set_status_updates_report_and_error() -> None:
    jobs = await _store()
    await jobs.touch("t1", title="Research the EV market")

    await jobs.set_status("t1", "done", report="# Report")

    record = await jobs.get("t1")
    assert record is not None
    assert record["status"] == "done"
    assert record["report"] == "# Report"


async def test_set_status_on_unknown_thread_is_a_noop() -> None:
    jobs = await _store()

    await jobs.set_status("does-not-exist", "failed", error="boom")

    assert (await jobs.get("does-not-exist")) is None


async def test_add_source_appends() -> None:
    jobs = await _store()
    await jobs.touch("t1", title="Research the EV market")

    await jobs.add_source("t1", "EU", "EU findings")
    await jobs.add_source("t1", "US", "US findings")

    record = await jobs.get("t1")
    assert record is not None
    assert record["sources"] == [
        {"topic": "EU", "summary": "EU findings"},
        {"topic": "US", "summary": "US findings"},
    ]


async def test_get_unknown_thread_returns_none() -> None:
    jobs = await _store()

    assert (await jobs.get("does-not-exist")) is None


async def test_list_recent_returns_newest_first() -> None:
    jobs = await _store()
    await jobs.touch("older", title="Research the fintech market")
    await jobs.touch("newer", title="Research the EV market")

    records = await jobs.list_recent()

    assert [r["thread_id"] for r in records] == ["newer", "older"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/jobs/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdrops.jobs'`.

- [ ] **Step 3: Implement `JobStore`**

Create `backend/src/agentdrops/jobs/__init__.py` (empty).

Create `backend/src/agentdrops/jobs/store.py`:

```python
"""Redis-backed job status: the single source of truth for a thread's status/report/sources.

Replaces the old in-memory `SessionStore` + LangGraph-checkpoint hybrid read — every status
transition a worker makes lands here, and the API reads only from here, never from a checkpoint.
"""

import json
from datetime import UTC, datetime
from typing import Literal, TypedDict, cast

from redis.asyncio import Redis

JobStatus = Literal["queued", "running", "clarifying", "done", "failed"]

_INDEX_KEY = "jobs:index"


class JobRecord(TypedDict):
    thread_id: str
    title: str
    created_at: str
    status: JobStatus
    report: str | None
    sources: list[dict[str, str]]
    error: str | None
    clarify_question: str | None


def _key(thread_id: str) -> str:
    return f"job:{thread_id}"


class JobStore:
    """Tracks one `JobRecord` per thread_id, keyed by first sight of that thread."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def touch(self, thread_id: str, *, title: str) -> JobRecord:
        """Create a job record the first time a thread is seen; a no-op afterward."""
        existing = await self.get(thread_id)
        if existing is not None:
            return existing
        created_at = datetime.now(UTC)
        record: JobRecord = {
            "thread_id": thread_id,
            "title": title,
            "created_at": created_at.isoformat(),
            "status": "queued",
            "report": None,
            "sources": [],
            "error": None,
            "clarify_question": None,
        }
        await self._write(thread_id, record)
        await self._redis.zadd(_INDEX_KEY, {thread_id: created_at.timestamp()})
        return record

    async def set_status(
        self,
        thread_id: str,
        status: JobStatus,
        *,
        report: str | None = None,
        error: str | None = None,
        clarify_question: str | None = None,
    ) -> None:
        record = await self.get(thread_id)
        if record is None:
            return
        record["status"] = status
        if report is not None:
            record["report"] = report
        if error is not None:
            record["error"] = error
        if clarify_question is not None:
            record["clarify_question"] = clarify_question
        await self._write(thread_id, record)

    async def add_source(self, thread_id: str, topic: str, summary: str) -> None:
        record = await self.get(thread_id)
        if record is None:
            return
        record["sources"].append({"topic": topic, "summary": summary})
        await self._write(thread_id, record)

    async def get(self, thread_id: str) -> JobRecord | None:
        raw = await self._redis.get(_key(thread_id))
        if raw is None:
            return None
        return cast(JobRecord, json.loads(raw))

    async def list_recent(self) -> list[JobRecord]:
        thread_ids = await self._redis.zrevrange(_INDEX_KEY, 0, -1)
        records = []
        for thread_id in thread_ids:
            record = await self.get(thread_id)
            if record is not None:
                records.append(record)
        return records

    async def _write(self, thread_id: str, record: JobRecord) -> None:
        await self._redis.set(_key(thread_id), json.dumps(record))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/jobs/test_store.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/src/agentdrops/jobs backend/tests/unit/jobs
git commit -m "feat(backend): add Redis-backed JobStore"
```

---

### Task 4: Redis pub/sub event helpers

**Files:**
- Create: `backend/src/agentdrops/jobs/events.py`
- Test: `backend/tests/unit/jobs/test_events.py`

**Interfaces:**
- Consumes: `redis.asyncio.Redis` instance.
- Produces: `async def publish_event(redis: Redis, thread_id: str, event: dict[str, Any]) -> None`; `def subscribe_events(redis: Redis, thread_id: str) -> AsyncIterator[dict[str, Any]]` (async generator).

Channel naming: `events:{thread_id}`. This is the pub/sub side of the design — `worker/runner.py` (Task 6) publishes, `api/main.py` (Task 8) subscribes.

- [ ] **Step 1: Write the failing test**

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
git add backend/src/agentdrops/jobs/events.py backend/tests/unit/jobs/test_events.py
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

`celery_app` is constructed with no broker/backend at import time deliberately: `Celery(...)`'s constructor itself needs no settings, so importing this module never requires a populated `.env`, matching `get_settings()`'s own lazy-construction pattern used throughout the rest of the codebase. `configure_celery` is called explicitly once at real process startup (API lifespan in Task 8, worker entrypoint in Task 7) — never at import time.

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
- Consumes: a compiled graph exposing `async def astream(self, inputs: dict, config: dict, stream_mode: list[str]) -> AsyncIterator[tuple[str, dict]]` (structurally, same shape `_FakeGraph`/`_FailingGraph` in the old `tests/unit/api/test_main.py` already used); `JobStore` (Task 3); `publish_event` (Task 4).
- Produces: `async def run_turn(graph: Any, inputs: dict[str, Any], config: dict[str, Any], thread_id: str, jobs: JobStore, redis: Redis) -> None` — Task 7's Celery task is the only caller.

This is today's `_run_graph_turn` (`api/main.py:133-184`) adapted to update `JobStore` + publish to Redis instead of mutating a `SessionStore` and yielding to an HTTP SSE generator — it also now sets `status="running"` immediately (rather than only when the `supervisor` node is reached), since "running" should cover the whole span from the worker picking up the task, matching the design spec's data flow.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/worker/test_runner.py`:

```python
import json
from collections.abc import AsyncIterator
from typing import Any

from fakeredis.aioredis import FakeRedis
from langchain_core.messages import AIMessage

from agentdrops.jobs.store import JobStore
from agentdrops.worker.runner import run_turn


class _FakeGraph:
    """Same two fixed turns as the old `tests/unit/api/test_main.py::_FakeGraph`: first turn
    asks a clarification, second turn streams progress/source events then reports."""

    def __init__(self) -> None:
        self._turn = 0

    async def astream(
        self, _inputs: dict, _config: dict, _stream_mode: list[str]
    ) -> AsyncIterator[tuple[str, dict]]:
        self._turn += 1
        if self._turn == 1:
            yield (
                "updates",
                {
                    "clarify_with_user": {
                        "needs_clarification": True,
                        "messages": [AIMessage(content="Which region should I focus on?")],
                    }
                },
            )
            return
        yield ("updates", {"clarify_with_user": {"needs_clarification": False, "messages": []}})
        yield ("updates", {"write_research_brief": {}})
        yield ("custom", {"type": "progress", "step": "researching", "detail": "Researching: EU"})
        yield ("custom", {"type": "source", "topic": "EU", "summary": "EU findings"})
        yield ("updates", {"supervisor": {}})
        yield (
            "updates",
            {"final_report_generation": {"final_report": "# EV Charging Market Report"}},
        )


class _FailingGraph:
    async def astream(
        self, _inputs: dict, _config: dict, _stream_mode: list[str]
    ) -> AsyncIterator[tuple[str, dict]]:
        yield ("updates", {"clarify_with_user": {"needs_clarification": False, "messages": []}})
        raise RuntimeError("LLM provider unavailable")


async def _published(redis: FakeRedis, thread_id: str) -> list[dict[str, Any]]:
    raw = await redis.lrange(f"_test_published:{thread_id}", 0, -1)
    return [json.loads(r) for r in raw]


class _RecordingRedis(FakeRedis):
    """Records every `publish` call to a list key, so the test can assert on emitted events
    without standing up a second pub/sub subscriber (that's already covered by
    `tests/unit/jobs/test_events.py`) — this test is about `run_turn`'s own logic."""

    async def publish(self, channel: str, message: str) -> int:  # type: ignore[override]
        await self.rpush(f"_test_published:{channel.removeprefix('events:')}", message)
        return 1


async def test_run_turn_first_call_sets_clarifying_and_publishes_clarify_event() -> None:
    redis = _RecordingRedis(decode_responses=True)
    jobs = JobStore(redis)
    await jobs.touch("t1", title="Research the EV charging market")

    await run_turn(_FakeGraph(), {}, {}, "t1", jobs, redis)

    record = await jobs.get("t1")
    assert record is not None
    assert record["status"] == "clarifying"
    assert record["clarify_question"] == "Which region should I focus on?"
    published = await _published(redis, "t1")
    assert published == [
        {"type": "clarify", "thread_id": "t1", "response": "Which region should I focus on?"}
    ]


async def test_run_turn_second_call_persists_sources_and_publishes_done() -> None:
    redis = _RecordingRedis(decode_responses=True)
    jobs = JobStore(redis)
    await jobs.touch("t1", title="Research the EV charging market")
    graph = _FakeGraph()
    graph._turn = 1  # pretend the clarify turn already happened

    await run_turn(graph, {}, {}, "t1", jobs, redis)

    record = await jobs.get("t1")
    assert record is not None
    assert record["status"] == "done"
    assert record["report"] == "# EV Charging Market Report"
    assert record["sources"] == [{"topic": "EU", "summary": "EU findings"}]
    published = await _published(redis, "t1")
    assert {"type": "source", "topic": "EU", "summary": "EU findings"} in published
    assert published[-1] == {
        "type": "done",
        "thread_id": "t1",
        "report": "# EV Charging Market Report",
    }


async def test_run_turn_marks_failed_and_publishes_error_on_exception() -> None:
    redis = _RecordingRedis(decode_responses=True)
    jobs = JobStore(redis)
    await jobs.touch("t1", title="Research the EV charging market")

    await run_turn(_FailingGraph(), {}, {}, "t1", jobs, redis)

    record = await jobs.get("t1")
    assert record is not None
    assert record["status"] == "failed"
    assert record["error"] == "LLM provider unavailable"
    published = await _published(redis, "t1")
    assert published[-1] == {
        "type": "error",
        "thread_id": "t1",
        "message": "LLM provider unavailable",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/worker/test_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdrops.worker.runner'`.

- [ ] **Step 3: Implement `run_turn`**

Create `backend/src/agentdrops/worker/runner.py`:

```python
"""Drives one graph turn to completion inside a Celery worker, updating Redis job status and
publishing every event to Redis pub/sub — the worker-process counterpart of the old
`api/main.py::_run_graph_turn`, which drove the graph in the HTTP request/response cycle instead.
"""

import logging
from typing import Any

from redis.asyncio import Redis

from agentdrops.jobs.events import publish_event
from agentdrops.jobs.store import JobStore
from agentdrops.observability.logging import bind_run_id
from agentdrops.observability.tracing import traced_span

logger = logging.getLogger(__name__)

NODE_LABELS: dict[str, str] = {
    "clarify_with_user": "Reviewing your request",
    "write_research_brief": "Planning research approach",
    "supervisor": "Coordinating research",
    "final_report_generation": "Synthesizing findings",
}


async def run_turn(
    graph: Any,
    inputs: dict[str, Any],
    config: dict[str, Any],
    thread_id: str,
    jobs: JobStore,
    redis: Redis,
) -> None:
    with bind_run_id(thread_id), traced_span("research.turn", thread_id=thread_id) as span:
        outcome = "incomplete"
        try:
            await jobs.set_status(thread_id, "running")
            async for stream_type, chunk in graph.astream(
                inputs, config=config, stream_mode=["updates", "custom"]
            ):
                if stream_type == "custom":
                    if chunk.get("type") == "source":
                        await jobs.add_source(thread_id, chunk["topic"], chunk["summary"])
                        span.add_event("research.source", {"topic": chunk["topic"]})
                    await publish_event(redis, thread_id, chunk)
                    continue
                for node_name, node_output in chunk.items():
                    if node_name == "clarify_with_user" and node_output.get("needs_clarification"):
                        question = str(node_output["messages"][-1].content)
                        await jobs.set_status(thread_id, "clarifying", clarify_question=question)
                        outcome = "clarify"
                        await publish_event(
                            redis,
                            thread_id,
                            {"type": "clarify", "thread_id": thread_id, "response": question},
                        )
                        return
                    if node_name == "final_report_generation":
                        report = node_output["final_report"]
                        await jobs.set_status(thread_id, "done", report=report)
                        outcome = "done"
                        span.set_attribute("research.report_chars", len(report))
                        await publish_event(
                            redis,
                            thread_id,
                            {"type": "done", "thread_id": thread_id, "report": report},
                        )
                        return
                    label = NODE_LABELS.get(node_name)
                    if label:
                        span.add_event("research.stage", {"stage": label})
                        await publish_event(
                            redis, thread_id, {"type": "progress", "step": label}
                        )
        except Exception as exc:
            logger.exception("worker turn failed for thread_id=%s", thread_id)
            await jobs.set_status(thread_id, "failed", error=str(exc))
            await publish_event(
                redis, thread_id, {"type": "error", "thread_id": thread_id, "message": str(exc)}
            )
        finally:
            span.set_attribute("research.outcome", outcome)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/worker/test_runner.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/src/agentdrops/worker/runner.py backend/tests/unit/worker/test_runner.py
git commit -m "feat(backend): add worker turn runner (Redis job status + pub/sub)"
```

---

### Task 7: Celery task entrypoint

**Files:**
- Create: `backend/src/agentdrops/worker/tasks.py`
- Create: `backend/src/agentdrops/worker/app.py`
- Test: `backend/tests/unit/worker/test_tasks.py`

**Interfaces:**
- Consumes: `run_turn` (Task 6), `build_market_researcher` (Task 2), `celery_app` (Task 5).
- Produces: `run_turn_task` (a `@celery_app.task`, callable directly in tests as `run_turn_task(thread_id, message)`, or via `.delay(thread_id, message)` in production); `celery_app` re-exported from `worker/app.py` as the module the `celery` CLI points `-A` at.

`_checkpointer` is a small seam specifically so tests never need a real Postgres connection: it's monkeypatched to yield a plain `InMemorySaver()` in tests, and calls the real `AsyncPostgresSaver.from_conn_string(...)` in production.

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
        yield (
            "updates",
            {"final_report_generation": {"final_report": "# Report"}},
        )


@pytest.fixture(autouse=True)
def patch_worker_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks_module, "get_settings", lambda: make_settings())
    monkeypatch.setattr(
        tasks_module,
        "build_market_researcher",
        lambda settings, client, checkpointer: _FakeGraph(),
    )

    @asynccontextmanager
    async def fake_checkpointer(_settings: Settings) -> AsyncIterator[BaseCheckpointSaver[Any]]:
        yield InMemorySaver()

    monkeypatch.setattr(tasks_module, "_checkpointer", fake_checkpointer)
    monkeypatch.setattr(
        tasks_module.Redis, "from_url", staticmethod(lambda *_a, **_k: FakeRedis(decode_responses=True))
    )


def test_run_turn_task_drives_a_turn_to_completion() -> None:
    """A plain (non-async) test: `run_turn_task` calls `asyncio.run()` internally, which raises
    if called from within pytest-asyncio's own event loop, so this must not be `async def`."""
    tasks_module.run_turn_task("t1", "Research the EV charging market")

    # No exception means `_execute` ran end to end; the job's terminal state is covered by
    # `tests/unit/worker/test_runner.py` already, so this test only proves the wiring works.
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/worker/test_tasks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdrops.worker.tasks'`.

- [ ] **Step 3: Implement the task**

Create `backend/src/agentdrops/worker/tasks.py`:

```python
"""Celery task entrypoint: bridges Celery's synchronous task execution into the async
graph/runner/Redis stack. This is the only place `asyncio.run` appears, since everything it
calls into (the graph, JobStore, pub/sub) is async."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from redis.asyncio import Redis

from agentdrops.agents.graph import build_market_researcher
from agentdrops.config import Settings, get_settings
from agentdrops.jobs.store import JobStore
from agentdrops.worker.celery_app import celery_app
from agentdrops.worker.runner import run_turn


@asynccontextmanager
async def _checkpointer(settings: Settings) -> AsyncIterator[BaseCheckpointSaver[Any]]:
    async with AsyncPostgresSaver.from_conn_string(settings.database_url) as saver:
        await saver.setup()
        yield saver


async def _execute(thread_id: str, message: str, settings: Settings) -> None:
    redis: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        jobs = JobStore(redis)
        async with (
            httpx.AsyncClient(timeout=30.0) as client,
            _checkpointer(settings) as checkpointer,
        ):
            graph = build_market_researcher(settings, client, checkpointer)
            config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
            inputs = {"messages": [HumanMessage(content=message)]}
            await run_turn(graph, inputs, config, thread_id, jobs, redis)
    finally:
        await redis.aclose()


@celery_app.task(name="agentdrops.run_turn")
def run_turn_task(thread_id: str, message: str) -> None:
    asyncio.run(_execute(thread_id, message, get_settings()))
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

### Task 8: Rewrite the API layer for the async contract

**Files:**
- Modify: `backend/src/agentdrops/api/schema.py`
- Modify: `backend/src/agentdrops/api/main.py`
- Delete: `backend/src/agentdrops/api/sessions.py`
- Modify: `backend/tests/unit/api/test_main.py` (full rewrite)

**Interfaces:**
- Consumes: `JobStore`, `subscribe_events`/`publish_event` (Tasks 3-4), `run_turn_task` (Task 7), `configure_celery` (Task 5).
- Produces: `ChatQueuedResponse` (new schema) — nothing downstream in this plan consumes it besides the route itself; the frontend never called synchronous `/chat` (confirmed: `frontend/src/lib/api.ts` only calls `/chat/stream`), so this is a pure backend-internal contract change.

This is the task that actually flips the switch: `/chat` and `/chat/stream` stop calling `graph.astream` and start enqueuing `run_turn_task`; `/research/{id}` and `/research/sessions` stop reading the LangGraph checkpoint and read only `JobStore`.

- [ ] **Step 1: Update `api/schema.py`**

Replace the full contents of `backend/src/agentdrops/api/schema.py`:

```python
"""Request/response contracts for the chat and research HTTP endpoints."""

from typing import Literal

from pydantic import BaseModel

ResearchStatusValue = Literal["queued", "clarifying", "running", "done", "failed"]


class ChatRequest(BaseModel):
    """One chat turn: an optional existing thread to resume, plus the user's message."""

    thread_id: str | None = None
    message: str


class ChatQueuedResponse(BaseModel):
    """Acknowledgement that one chat turn was enqueued; poll /research/{thread_id} or use
    /chat/stream to observe it. Replaces the old `ChatResponse`, which returned the turn's full
    result inline — no longer possible once the turn runs in a background worker."""

    thread_id: str
    status: Literal["queued"] = "queued"


class ResearchStatusResponse(BaseModel):
    """Current state of one research thread, read from its Redis job record."""

    thread_id: str
    status: ResearchStatusValue
    report: str | None = None


class ReportResponse(BaseModel):
    """A completed thread's report, for reopening the drawer without re-running research."""

    thread_id: str
    report: str
    sources: list[dict[str, str]]


class SessionSummary(BaseModel):
    """One row in the recent-sessions sidebar."""

    id: str
    title: str
    created_at: str
    status: ResearchStatusValue


class SessionsResponse(BaseModel):
    sessions: list[SessionSummary]
```

(`ChatResponse` and `research_brief` are dropped — nothing populates `research_brief` once the API no longer reads the LangGraph checkpoint, and `ChatResponse` had exactly one caller, the old synchronous `/chat` body, which no longer exists.)

- [ ] **Step 2: Delete `api/sessions.py`**

Run: `git rm backend/src/agentdrops/api/sessions.py`

- [ ] **Step 3: Rewrite `api/main.py`**

Replace the full contents of `backend/src/agentdrops/api/main.py`:

```python
"""FastAPI app exposing the market-research agent over /chat and /chat/stream.

Both endpoints enqueue a Celery task (`agentdrops.worker.tasks.run_turn_task`) and return
immediately — this process never calls `graph.astream` itself. Job status/report/sources live in
Redis (`agentdrops.jobs.store.JobStore`), written by the worker as it runs; `/chat/stream` relays
the worker's published events (`agentdrops.jobs.events`) as SSE, in the same wire format clients
already parse.
"""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from redis.asyncio import Redis

from agentdrops.api.schema import (
    ChatQueuedResponse,
    ChatRequest,
    ReportResponse,
    ResearchStatusResponse,
    SessionsResponse,
    SessionSummary,
)
from agentdrops.config import get_settings
from agentdrops.jobs.events import subscribe_events
from agentdrops.jobs.store import JobRecord, JobStore
from agentdrops.observability.setup import configure_observability, instrument_fastapi
from agentdrops.types.error_codes import Error, NotFoundError, fastAPIErrorResponseModels
from agentdrops.types.response import ErrorResponse, Response, SuccessResponse
from agentdrops.worker.celery_app import configure_celery
from agentdrops.worker.tasks import run_turn_task

logger = logging.getLogger(__name__)

TITLE_MAX_LENGTH = 80

_TERMINAL_STATUSES = {"done", "clarifying", "failed"}
_TERMINAL_EVENT_TYPES = {"clarify", "done", "error"}


def _sse(payload: dict[str, Any]) -> str:
    """Format one SSE event as a `data:` line, per the text/event-stream framing."""
    return f"data: {json.dumps(payload)}\n\n"


def _terminal_event_from_job(thread_id: str, job: JobRecord) -> dict[str, Any]:
    """Reconstruct the terminal SSE event from a job record already settled by the time
    `/chat/stream` subscribes — the race window between enqueueing and subscribing."""
    if job["status"] == "done":
        return {"type": "done", "thread_id": thread_id, "report": job["report"]}
    if job["status"] == "clarifying":
        return {
            "type": "clarify",
            "thread_id": thread_id,
            "response": job["clarify_question"] or "",
        }
    return {"type": "error", "thread_id": thread_id, "message": job["error"] or "Research failed"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    providers = configure_observability(settings)
    configure_celery(settings)
    redis: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        app.state.redis = redis
        app.state.jobs = JobStore(redis)
        yield
    finally:
        await redis.aclose()
        providers.shutdown()


app = FastAPI(title="Agentdrops Market Research Agent", lifespan=lifespan)
instrument_fastapi(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _error_content(error: Error) -> dict[str, Any]:
    return Response[Error](success=False, data=error).model_dump()


@app.exception_handler(ErrorResponse)
async def handle_error_response(_request: Request, exc: ErrorResponse) -> JSONResponse:
    return JSONResponse(status_code=exc.error.code, content=_error_content(exc.error))


@app.exception_handler(HTTPException)
async def handle_http_exception(_request: Request, exc: HTTPException) -> JSONResponse:
    error = Error(code=exc.status_code, description=str(exc.detail))
    return JSONResponse(status_code=exc.status_code, content=_error_content(error))


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    error = Error(
        code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        description="Validation Error",
        message=str(exc.errors()),
    )
    return JSONResponse(status_code=error.code, content=_error_content(error))


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error while processing %s %s", request.method, request.url.path)
    error = Error(code=500, description="Internal Server Error")
    return JSONResponse(status_code=error.code, content=_error_content(error))


@app.get("/health", response_model=SuccessResponse[dict[str, str]])
async def health() -> SuccessResponse[dict[str, str]]:
    return SuccessResponse(data={"status": "ok"})


@app.post("/chat", response_model=SuccessResponse[ChatQueuedResponse])
async def chat(request: ChatRequest) -> SuccessResponse[ChatQueuedResponse]:
    """Enqueue one chat turn for background execution; poll /research/{thread_id} for the
    result, or use /chat/stream instead to observe it live."""
    thread_id = request.thread_id or str(uuid.uuid4())
    jobs: JobStore = app.state.jobs
    await jobs.touch(thread_id, title=request.message[:TITLE_MAX_LENGTH])
    run_turn_task.delay(thread_id, request.message)
    return SuccessResponse(data=ChatQueuedResponse(thread_id=thread_id))


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
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
    thread_id = request.thread_id or str(uuid.uuid4())
    jobs: JobStore = app.state.jobs
    redis: Redis = app.state.redis
    await jobs.touch(thread_id, title=request.message[:TITLE_MAX_LENGTH])
    run_turn_task.delay(thread_id, request.message)

    async def events() -> AsyncIterator[str]:
        # The task may have already finished by the time we get here (enqueue-then-subscribe
        # race) — check the job record first rather than subscribing blind and hanging forever.
        job = await jobs.get(thread_id)
        if job is not None and job["status"] in _TERMINAL_STATUSES:
            yield _sse(_terminal_event_from_job(thread_id, job))
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


@app.get("/research/sessions", response_model=SuccessResponse[SessionsResponse])
async def list_sessions() -> SuccessResponse[SessionsResponse]:
    """List every known research thread, most recently started first, for the sidebar."""
    jobs: JobStore = app.state.jobs
    records = await jobs.list_recent()
    return SuccessResponse(
        data=SessionsResponse(
            sessions=[
                SessionSummary(
                    id=r["thread_id"],
                    title=r["title"],
                    created_at=r["created_at"],
                    status=r["status"],
                )
                for r in records
            ]
        )
    )


@app.get(
    "/research/{thread_id}",
    response_model=SuccessResponse[ResearchStatusResponse],
    responses={status.HTTP_404_NOT_FOUND: fastAPIErrorResponseModels[status.HTTP_404_NOT_FOUND]},
)
async def get_research_status(thread_id: str) -> SuccessResponse[ResearchStatusResponse]:
    """Read one thread's current status straight off its Redis job record."""
    jobs: JobStore = app.state.jobs
    job = await jobs.get(thread_id)
    if job is None:
        raise ErrorResponse(NotFoundError(message="Unknown thread_id"))
    return SuccessResponse(
        data=ResearchStatusResponse(thread_id=thread_id, status=job["status"], report=job["report"])
    )


@app.get(
    "/research/{thread_id}/report",
    response_model=SuccessResponse[ReportResponse],
    responses={status.HTTP_404_NOT_FOUND: fastAPIErrorResponseModels[status.HTTP_404_NOT_FOUND]},
)
async def get_research_report(thread_id: str) -> SuccessResponse[ReportResponse]:
    """Fetch a completed thread's report and sources, so the drawer can reopen without a rerun."""
    jobs: JobStore = app.state.jobs
    job = await jobs.get(thread_id)
    if job is None or job["report"] is None:
        raise ErrorResponse(NotFoundError(message="Report not available for this thread_id"))
    return SuccessResponse(
        data=ReportResponse(thread_id=thread_id, report=job["report"], sources=job["sources"])
    )
```

- [ ] **Step 4: Rewrite `tests/unit/api/test_main.py`**

Replace the full contents of `backend/tests/unit/api/test_main.py`:

```python
import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fakeredis import FakeServer
from fakeredis.aioredis import FakeRedis
from fastapi.testclient import TestClient

import agentdrops.api.main as main_module
from agentdrops.jobs.store import JobStore
from tests.unit.agents.conftest import make_settings


class _FakeDelay:
    """Stand-in for Celery's `.delay(...)`: records calls instead of touching a real broker.
    A worker publishing events is simulated separately per-test via `publish_event`/`JobStore`
    against the same `FakeServer`, exactly like a real worker would from its own process."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, thread_id: str, message: str) -> None:
        self.calls.append((thread_id, message))


@pytest.fixture
def shared_server() -> FakeServer:
    return FakeServer()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, shared_server: FakeServer) -> Iterator[TestClient]:
    monkeypatch.setattr(main_module, "get_settings", lambda: make_settings())
    monkeypatch.setattr(main_module, "configure_celery", lambda settings: None)
    monkeypatch.setattr(
        main_module.Redis,
        "from_url",
        staticmethod(lambda *_a, **_k: FakeRedis(server=shared_server, decode_responses=True)),
    )
    fake_delay = _FakeDelay()
    monkeypatch.setattr(main_module.run_turn_task, "delay", fake_delay)
    with TestClient(main_module.app) as test_client:
        test_client.fake_delay = fake_delay  # type: ignore[attr-defined]
        test_client.worker_redis = FakeRedis(  # type: ignore[attr-defined]
            server=shared_server, decode_responses=True
        )
        yield test_client


def _parse_sse(raw_text: str) -> list[dict[str, Any]]:
    return [json.loads(line[len("data: ") :]) for line in raw_text.splitlines() if line]


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_enqueues_and_returns_queued_immediately(client: TestClient) -> None:
    response = client.post("/chat", json={"message": "Research the EV charging market"})

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["status"] == "queued"
    thread_id = body["thread_id"]
    assert client.fake_delay.calls == [(thread_id, "Research the EV charging market")]  # type: ignore[attr-defined]

    status_response = client.get(f"/research/{thread_id}")
    assert status_response.json()["data"]["status"] == "queued"


# NOTE: the "worker publishes while /chat/stream is subscribed" path is covered by
# `tests/unit/jobs/test_events.py` (pub/sub round-trip) and the `_terminal_event_from_job` tests
# below (the race where the worker finishes first) — a live concurrent-timing test through
# TestClient's synchronous streaming API would be flaky by construction, so it's intentionally
# not written here.


def test_chat_stream_reconstructs_terminal_event_if_already_done(client: TestClient) -> None:
    """The enqueue-then-subscribe race: by the time /chat/stream subscribes, the task has
    already finished (e.g. a fast clarify-only turn). It must not hang waiting on pub/sub."""
    jobs = JobStore(client.worker_redis)  # type: ignore[attr-defined]

    async def _seed() -> str:
        record = await jobs.touch("t-done", title="Research the EV charging market")
        await jobs.set_status("t-done", "done", report="# EV Charging Market Report")
        return record["thread_id"]

    asyncio.run(_seed())

    response = client.post(
        "/chat/stream", json={"thread_id": "t-done", "message": "Focus on the EU"}
    )

    events = _parse_sse(response.text)
    assert events == [{"type": "done", "thread_id": "t-done", "report": "# EV Charging Market Report"}]


def test_chat_stream_reconstructs_clarify_event_if_already_clarifying(
    client: TestClient,
) -> None:
    jobs = JobStore(client.worker_redis)  # type: ignore[attr-defined]

    async def _seed() -> None:
        await jobs.touch("t-clarify", title="Research the EV charging market")
        await jobs.set_status(
            "t-clarify", "clarifying", clarify_question="Which region should I focus on?"
        )

    asyncio.run(_seed())

    response = client.post(
        "/chat/stream", json={"thread_id": "t-clarify", "message": "Research the EV market"}
    )

    events = _parse_sse(response.text)
    assert events == [
        {
            "type": "clarify",
            "thread_id": "t-clarify",
            "response": "Which region should I focus on?",
        }
    ]


def test_chat_stream_reconstructs_error_event_if_already_failed(client: TestClient) -> None:
    jobs = JobStore(client.worker_redis)  # type: ignore[attr-defined]

    async def _seed() -> None:
        await jobs.touch("t-failed", title="Research the EV charging market")
        await jobs.set_status("t-failed", "failed", error="LLM provider unavailable")

    asyncio.run(_seed())

    response = client.post(
        "/chat/stream", json={"thread_id": "t-failed", "message": "Research the EV market"}
    )

    events = _parse_sse(response.text)
    assert events == [
        {"type": "error", "thread_id": "t-failed", "message": "LLM provider unavailable"}
    ]


def test_list_sessions_returns_known_threads_newest_first(client: TestClient) -> None:
    client.post("/chat", json={"message": "Research the EV charging market"})
    client.post("/chat", json={"message": "Research the fintech market"})

    response = client.get("/research/sessions")

    assert response.status_code == 200
    titles = [s["title"] for s in response.json()["data"]["sessions"]]
    assert titles == ["Research the fintech market", "Research the EV charging market"]
    assert all(s["status"] == "queued" for s in response.json()["data"]["sessions"])


def test_get_research_status_unknown_thread_returns_404(client: TestClient) -> None:
    response = client.get("/research/does-not-exist")

    assert response.status_code == 404


def test_get_research_report_before_done_returns_404(client: TestClient) -> None:
    first = client.post("/chat", json={"message": "Research the EV charging market"})
    thread_id = first.json()["data"]["thread_id"]

    response = client.get(f"/research/{thread_id}/report")

    assert response.status_code == 404


def test_get_research_report_after_done_returns_report_and_sources(client: TestClient) -> None:
    jobs = JobStore(client.worker_redis)  # type: ignore[attr-defined]

    async def _seed() -> str:
        record = await jobs.touch("t-report", title="Research the EV charging market")
        await jobs.add_source("t-report", "EU", "EU findings")
        await jobs.set_status("t-report", "done", report="# EV Charging Market Report")
        return record["thread_id"]

    thread_id = asyncio.run(_seed())

    response = client.get(f"/research/{thread_id}/report")

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["report"] == "# EV Charging Market Report"
    assert body["sources"] == [{"topic": "EU", "summary": "EU findings"}]


def test_chat_stream_emits_error_event_if_subscription_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dropped Redis connection mid-subscribe must surface as an `error` SSE event, not hang
    the response open with nothing ever arriving."""

    async def _broken_subscribe(_redis: Any, _thread_id: str) -> AsyncIterator[dict[str, Any]]:
        raise ConnectionError("connection to Redis lost")
        yield {}  # pragma: no cover — makes this an async generator; never reached

    monkeypatch.setattr(main_module, "subscribe_events", _broken_subscribe)

    response = client.post(
        "/chat/stream", json={"message": "Research the EV charging market"}
    )

    events = _parse_sse(response.text)
    assert events == [
        {
            "type": "error",
            "thread_id": events[0]["thread_id"],
            "message": "connection to Redis lost",
        }
    ]
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/unit/api/test_main.py -v`
Expected: PASS (10 tests).

- [ ] **Step 6: Run the full suite, lint, and typecheck**

Run: `pytest && ruff check . && mypy src`
Expected: all three PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/agentdrops/api/schema.py backend/src/agentdrops/api/main.py backend/tests/unit/api/test_main.py
git rm backend/src/agentdrops/api/sessions.py
git commit -m "feat(backend): make /chat and /chat/stream enqueue Celery tasks instead of driving the graph inline"
```

---

### Task 9: Worker process entrypoint (`make worker`)

**Files:**
- Modify: `backend/Makefile`

**Interfaces:**
- Consumes: `agentdrops.worker.app:celery_app` (Task 7).
- Produces: `make worker` target, following the same shape as the existing `make run` target.

This repo runs the API by invoking `uvicorn` directly via `make run` — there's no Dockerfile or app-level `docker-compose.yml` service (compose only runs infra: postgres/redis/minio). A worker gets the same treatment: a Makefile target, not new container infrastructure the rest of the repo doesn't have yet.

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

And register it in the `.PHONY` line (already listing `run dev stop ...`):

```makefile
.PHONY: help venv install env infra-up infra-down infra-restart infra-ps infra-logs infra-reset \
        run dev worker stop test test-file lint lint-fix format typecheck check clean doctor
```

- [ ] **Step 2: Verify the target resolves correctly (dry run, no real .env needed for this check)**

Run: `cd backend && make -n worker`
Expected: prints the `celery -A agentdrops.worker.app worker --loglevel=info` command line (not run, since `-n` is dry-run) with no Makefile syntax errors.

- [ ] **Step 3: Commit**

```bash
git add backend/Makefile
git commit -m "chore(backend): add make worker target for the Celery worker process"
```

---

### Task 10: Mirror the API contract change in the frontend

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/api.ts:60-61` (docstring only)
- Modify: `frontend/src/app/page.tsx:135-137`

**Interfaces:**
- Consumes: `ResearchStatusResponse`'s new `status` values (`"queued"` added) and dropped `research_brief` field (Task 8).
- Produces: `ResearchStatusValue` gains `"queued"`; `ResearchStatus` type drops `research_brief`; `selectSession`'s live-status check treats `"queued"` as a still-in-flight status, same as `"clarifying"`/`"running"`.

Per `CLAUDE.md`: "SSE event shapes are documented on `chat_stream` and mirrored in `frontend/src/lib/types.ts` — change both together." `research_brief` is declared in `ResearchStatus` (`types.ts:36`) but never read anywhere in `page.tsx`/`api.ts` (confirmed via grep) — safe to delete outright rather than leave a field that's now permanently `null`.

- [ ] **Step 1: Update `types.ts`**

In `frontend/src/lib/types.ts`, change:

```typescript
export type ResearchStatusValue = "clarifying" | "running" | "done" | "failed";
```

to:

```typescript
export type ResearchStatusValue = "queued" | "clarifying" | "running" | "done" | "failed";
```

And change:

```typescript
export type ResearchStatus = {
  thread_id: string;
  status: ResearchStatusValue;
  research_brief: string | null;
  report: string | null;
};
```

to:

```typescript
export type ResearchStatus = {
  thread_id: string;
  status: ResearchStatusValue;
  report: string | null;
};
```

- [ ] **Step 2: Update `api.ts`'s stale docstring**

In `frontend/src/lib/api.ts:60`, change:

```typescript
/** Read one thread's current status straight off the graph's checkpoint. */
```

to:

```typescript
/** Read one thread's current status straight off its Redis job record. */
```

- [ ] **Step 3: Treat `"queued"` as still-in-flight in `selectSession`**

In `frontend/src/app/page.tsx:135-137`, change:

```typescript
      setPhase(status.status === "clarifying" ? "clarifying" : "running");
      if (status.status === "clarifying" || status.status === "running") {
        pollUntilSettled(session.id, token);
      }
```

to:

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

(`pollUntilSettled` itself, at `page.tsx:79-94`, already keeps polling by default for anything other than `"done"`/`"failed"` — only `selectSession`'s initial branch needed the new value added.)

- [ ] **Step 4: Typecheck and lint the frontend**

Run: `cd frontend && npm run lint`
Expected: PASS, no unused-import or type errors.

Run: `npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/lib/api.ts frontend/src/app/page.tsx
git commit -m "fix(frontend): mirror the queued status and dropped research_brief field"
```

---

## Manual Verification (not automated — requires real Postgres/Redis)

After all tasks land, the unit-test suite proves the wiring is correct in isolation, but the following needs a human running `docker compose up -d` plus both processes:

1. `make env` (if `.env` doesn't exist yet), fill in real API keys.
2. `make infra-up` (postgres/redis/minio).
3. Terminal A: `make run` (FastAPI on :8001).
4. Terminal B: `make worker` (Celery worker).
5. From the frontend (`npm run dev`), submit a research topic and confirm: progress steps stream live, a clarifying question round-trips correctly, the final report renders, and reopening a session from the sidebar mid-run resumes via polling.
6. Restart the worker process mid-run (kill `make worker`, restart it) and confirm a *new* turn on the same thread still works — this is the check that Postgres checkpoint state actually survived a worker-process restart, which `InMemorySaver` never could.
