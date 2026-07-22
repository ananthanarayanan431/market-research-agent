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


class _StateSnapshot:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values


class _FakeGraph:
    """Fake compiled graph: first turn per thread asks a clarification, second turn reports."""

    def __init__(self) -> None:
        self._turns: dict[str, int] = {}
        self._values: dict[str, dict[str, Any]] = {}

    async def astream(
        self, _inputs: dict, config: dict, stream_mode: list[str]
    ) -> AsyncIterator[tuple[str, dict]]:
        thread_id = config["configurable"]["thread_id"]
        turn = self._turns.get(thread_id, 0) + 1
        self._turns[thread_id] = turn
        state = self._values.setdefault(thread_id, {})
        if turn == 1:
            update = {
                "needs_clarification": True,
                "messages": [AIMessage(content="Which region should I focus on?")],
            }
            state.update(update)
            yield ("updates", {"clarify_with_user": update})
            return
        state.update({"needs_clarification": False})
        yield (
            "updates",
            {"clarify_with_user": {"needs_clarification": False, "messages": []}},
        )
        yield ("updates", {"write_research_brief": {}})
        yield ("custom", {"type": "progress", "step": "researching", "detail": "Researching: EU"})
        yield ("custom", {"type": "source", "topic": "EU", "summary": "EU findings"})
        yield ("updates", {"supervisor": {}})
        report = "# EV Charging Market Report"
        state.update({"final_report": report})
        yield ("updates", {"final_report_generation": {"final_report": report}})

    async def aget_state(self, config: dict) -> _StateSnapshot:
        thread_id = config["configurable"]["thread_id"]
        return _StateSnapshot(self._values.get(thread_id, {}))


class _FailingGraph:
    """Fake compiled graph: streams a couple of events, then blows up mid-run."""

    async def astream(
        self, _inputs: dict, config: dict, stream_mode: list[str]
    ) -> AsyncIterator[tuple[str, dict]]:
        yield ("updates", {"clarify_with_user": {"needs_clarification": False, "messages": []}})
        yield ("updates", {"write_research_brief": {}})
        raise RuntimeError("LLM provider unavailable")

    async def aget_state(self, config: dict) -> _StateSnapshot:
        return _StateSnapshot({})


class _FakeEngine:
    """App startup needs an engine object; these route tests never touch a real database."""

    async def dispose(self) -> None:
        return None


def _fake_create_engine(_settings: object) -> _FakeEngine:
    return _FakeEngine()


def _fake_create_session_factory(_engine: object) -> object:
    return object()


class _FakeSessionStore:
    """In-memory stand-in for the Postgres-backed `SessionStore`, same async interface."""

    def __init__(self, _session_factory: object) -> None:
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
    def __init__(self, _session_factory: object) -> None:
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
            {
                "thread_id": thread_id,
                "operation": operation,
                "status": status,
                "detail": detail or {},
            }
        )


def _patch_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "create_engine", _fake_create_engine)
    monkeypatch.setattr(main_module, "create_session_factory", _fake_create_session_factory)
    monkeypatch.setattr(main_module, "SessionStore", _FakeSessionStore)
    monkeypatch.setattr(main_module, "AuditLog", _FakeAuditLog)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(main_module, "get_settings", lambda: make_settings())
    monkeypatch.setattr(
        main_module, "build_market_researcher", lambda settings, client: _FakeGraph()
    )
    _patch_db(monkeypatch)
    with TestClient(main_module.app) as test_client:
        yield test_client


@pytest.fixture
def failing_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(main_module, "get_settings", lambda: make_settings())
    monkeypatch.setattr(
        main_module, "build_market_researcher", lambda settings, client: _FailingGraph()
    )
    _patch_db(monkeypatch)
    with TestClient(main_module.app) as test_client:
        yield test_client


def parse_sse(raw_text: str) -> list[dict]:
    return [json.loads(line[len("data: ") :]) for line in raw_text.splitlines() if line]
