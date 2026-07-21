import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

import agentdrops.main as main_module
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


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(main_module, "get_settings", lambda: make_settings())
    monkeypatch.setattr(
        main_module, "build_market_researcher", lambda settings, client: _FakeGraph()
    )
    with TestClient(main_module.app) as test_client:
        yield test_client


@pytest.fixture
def failing_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(main_module, "get_settings", lambda: make_settings())
    monkeypatch.setattr(
        main_module, "build_market_researcher", lambda settings, client: _FailingGraph()
    )
    with TestClient(main_module.app) as test_client:
        yield test_client


def parse_sse(raw_text: str) -> list[dict]:
    return [json.loads(line[len("data: ") :]) for line in raw_text.splitlines() if line]
