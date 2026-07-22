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
