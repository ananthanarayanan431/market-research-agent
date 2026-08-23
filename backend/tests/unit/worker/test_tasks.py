import asyncio
import json
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
        self, _inputs: dict, config: dict, stream_mode: list[str]
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
        lambda settings, client, checkpointer, session_factory=None, *, use_context_hub=False: (
            _FakeGraph()
        ),
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


def test_run_turn_task_passes_use_context_hub_to_build_market_researcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    def fake_build(settings, client, checkpointer, session_factory=None, *, use_context_hub=False):
        captured["use_context_hub"] = use_context_hub
        captured["session_factory"] = session_factory
        return _FakeGraph()

    monkeypatch.setattr(tasks_module, "build_market_researcher", fake_build)

    tasks_module.run_turn_task("t1", "Research the EV charging market", "chat_stream", True)

    assert captured["use_context_hub"] is True
    assert captured["session_factory"] is not None


class _RecordingSessionStore:
    def __init__(self) -> None:
        self.statuses: list[tuple[str, str, object]] = []

    async def set_status(self, thread_id: str, status: str, **kwargs: object) -> None:
        self.statuses.append((thread_id, status, kwargs.get("error")))


class _RecordingAuditLog:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    async def record(self, thread_id: str, **kwargs: object) -> None:
        self.records.append({"thread_id": thread_id, **kwargs})


class _RecordingRedis(FakeRedis):
    """Records every `publish` call to a list key, mirroring `test_runner.py`'s helper, so this
    test can assert on the emitted event without a second pub/sub subscriber."""

    async def publish(self, channel: str, message: str) -> int:  # type: ignore[override]
        await self.rpush(f"_test_published:{channel.removeprefix('events:')}", message)
        return 1


def test_run_turn_task_records_failure_when_resource_setup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure while constructing dependencies (here: the Postgres checkpointer) — before
    `run_turn` is ever entered — must still mark the session failed and publish an `error` event,
    not propagate out of `asyncio.run` and leave the session/stream hanging forever."""
    sessions = _RecordingSessionStore()
    audit = _RecordingAuditLog()
    redis = _RecordingRedis(decode_responses=True)
    monkeypatch.setattr(tasks_module, "SessionStore", lambda session_factory: sessions)
    monkeypatch.setattr(tasks_module, "AuditLog", lambda session_factory: audit)
    monkeypatch.setattr(tasks_module.Redis, "from_url", staticmethod(lambda *_a, **_k: redis))

    @asynccontextmanager
    async def failing_checkpointer(_settings: Settings) -> AsyncIterator[BaseCheckpointSaver[Any]]:
        raise RuntimeError("Postgres unreachable")
        yield InMemorySaver()  # pragma: no cover — makes this an async generator; never reached

    monkeypatch.setattr(tasks_module, "checkpointer", failing_checkpointer)

    tasks_module.run_turn_task("t1", "Research the EV charging market", "chat_stream")

    assert sessions.statuses == [("t1", "failed", "Postgres unreachable")]
    assert audit.records == [
        {
            "thread_id": "t1",
            "operation": "chat_stream",
            "status": "failed",
            "detail": {"error": "Postgres unreachable"},
        }
    ]

    async def _published() -> list[dict[str, Any]]:
        raw = await redis.lrange("_test_published:t1", 0, -1)
        return [json.loads(r) for r in raw]

    published = asyncio.run(_published())
    assert published == [
        {"type": "error", "thread_id": "t1", "message": tasks_module.TURN_FAILED_MESSAGE}
    ]


class _FakeContextHubStore:
    def __init__(self) -> None:
        self.ready_ids: list[str] = []
        self.failed: list[tuple[str, str]] = []
        self.inserted: list[tuple[str, list[str], list[list[float]]]] = []
        self._document = None

    def set_document(self, document) -> None:
        self._document = document

    async def get_document(self, document_id: str):
        return self._document

    async def insert_chunks(self, document_id, chunks, embeddings) -> None:
        self.inserted.append((document_id, chunks, embeddings))

    async def mark_ready(self, document_id: str) -> None:
        self.ready_ids.append(document_id)

    async def mark_failed(self, document_id: str, error: str) -> None:
        self.failed.append((document_id, error))


class _FakeContextHubStorage:
    def __init__(self, data: bytes = b"hello world") -> None:
        self._data = data

    async def get(self, key: str) -> bytes:
        return self._data


def test_ingest_contexthub_document_task_extracts_chunks_and_embeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    from agentdrops.repository.contexthub import ContextHubDocumentRecord

    fake_store = _FakeContextHubStore()
    fake_store.set_document(
        ContextHubDocumentRecord(
            id="doc-1", title="a.txt", source_type="file", source_name="a.txt",
            content_type="txt", status="processing", created_at=datetime.now(UTC),
            minio_key="doc-1/a.txt",
        )
    )
    monkeypatch.setattr(tasks_module, "get_settings", lambda: make_settings())
    monkeypatch.setattr(tasks_module, "create_engine", lambda settings: _FakeEngine())
    monkeypatch.setattr(tasks_module, "create_session_factory", lambda engine: object())
    monkeypatch.setattr(tasks_module, "ContextHubStore", lambda session_factory: fake_store)
    monkeypatch.setattr(
        tasks_module, "ContextHubStorage", lambda settings: _FakeContextHubStorage()
    )

    class _FakeEmbedder:
        def __init__(self, **_kwargs) -> None:
            pass

        async def embed(self, texts: list[str]) -> list[list[float]]:
            return [[0.1] * 1536 for _ in texts]

    monkeypatch.setattr(tasks_module, "EmbeddingClient", _FakeEmbedder)

    tasks_module.ingest_contexthub_document_task("doc-1")

    assert fake_store.ready_ids == ["doc-1"]
    assert fake_store.inserted[0][0] == "doc-1"
    assert fake_store.inserted[0][1] == ["hello world"]


def test_ingest_contexthub_document_task_marks_failed_on_extraction_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    from agentdrops.repository.contexthub import ContextHubDocumentRecord

    fake_store = _FakeContextHubStore()
    fake_store.set_document(
        ContextHubDocumentRecord(
            id="doc-2", title="a.exe", source_type="file", source_name="a.exe",
            content_type="exe", status="processing", created_at=datetime.now(UTC),
            minio_key="doc-2/a.exe",
        )
    )
    monkeypatch.setattr(tasks_module, "get_settings", lambda: make_settings())
    monkeypatch.setattr(tasks_module, "create_engine", lambda settings: _FakeEngine())
    monkeypatch.setattr(tasks_module, "create_session_factory", lambda engine: object())
    monkeypatch.setattr(tasks_module, "ContextHubStore", lambda session_factory: fake_store)
    monkeypatch.setattr(
        tasks_module, "ContextHubStorage", lambda settings: _FakeContextHubStorage()
    )

    tasks_module.ingest_contexthub_document_task("doc-2")

    assert fake_store.ready_ids == []
    assert fake_store.failed[0][0] == "doc-2"
    assert "unsupported content_type" in fake_store.failed[0][1]
