import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

import agentdrops.api.main as main_module
from tests.unit.agents.conftest import make_settings


class _StateSnapshot:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values


class _FakeGraph:
    """Fake compiled graph: first turn per thread asks a clarification, second turn reports."""

    def __init__(self) -> None:
        self._turns: dict[str, int] = {}
        self._values: dict[str, dict[str, Any]] = {}

    async def ainvoke(self, _inputs: dict, config: dict) -> dict:
        thread_id = config["configurable"]["thread_id"]
        turn = self._turns.get(thread_id, 0) + 1
        self._turns[thread_id] = turn
        if turn == 1:
            result = {
                "messages": [AIMessage(content="Which region should I focus on?")],
                "needs_clarification": True,
            }
        else:
            result = {
                "messages": [AIMessage(content="Report attached.")],
                "needs_clarification": False,
                "final_report": "# EV Charging Market Report",
            }
        self._values.setdefault(thread_id, {}).update(result)
        return result

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


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(main_module, "get_settings", lambda: make_settings())
    monkeypatch.setattr(
        main_module, "build_market_researcher", lambda settings, client: _FakeGraph()
    )
    with TestClient(main_module.app) as test_client:
        yield test_client


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_first_turn_asks_for_clarification(client: TestClient) -> None:
    response = client.post("/chat", json={"message": "Research the EV charging market"})

    assert response.status_code == 200
    body = response.json()
    assert body["is_followup"] is True
    assert body["response"] == "Which region should I focus on?"
    assert body["report"] is None


def test_chat_follow_up_returns_final_report(client: TestClient) -> None:
    first = client.post("/chat", json={"message": "Research the EV charging market"})
    thread_id = first.json()["thread_id"]

    second = client.post("/chat", json={"thread_id": thread_id, "message": "Focus on the EU"})

    body = second.json()
    assert body["is_followup"] is False
    assert body["report"] == "# EV Charging Market Report"
    assert body["thread_id"] == thread_id


def _parse_sse(raw_text: str) -> list[dict]:
    return [json.loads(line[len("data: ") :]) for line in raw_text.splitlines() if line]


def test_chat_stream_first_turn_emits_clarify_event(client: TestClient) -> None:
    response = client.post(
        "/chat/stream", json={"message": "Research the EV charging market"}
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert events == [
        {
            "type": "clarify",
            "thread_id": events[0]["thread_id"],
            "response": "Which region should I focus on?",
        }
    ]


def test_chat_stream_second_turn_emits_progress_source_and_done(client: TestClient) -> None:
    first = client.post("/chat/stream", json={"message": "Research the EV charging market"})
    thread_id = _parse_sse(first.text)[0]["thread_id"]

    second = client.post(
        "/chat/stream", json={"thread_id": thread_id, "message": "Focus on the EU"}
    )

    events = _parse_sse(second.text)
    assert {"type": "progress", "step": "Planning research approach"} in events
    assert {"type": "progress", "step": "Coordinating research"} in events
    assert {
        "type": "progress",
        "step": "researching",
        "detail": "Researching: EU",
    } in events
    assert {"type": "source", "topic": "EU", "summary": "EU findings"} in events
    assert events[-1] == {
        "type": "done",
        "thread_id": thread_id,
        "report": "# EV Charging Market Report",
    }


def test_list_sessions_returns_known_threads_newest_first(client: TestClient) -> None:
    client.post("/chat", json={"message": "Research the EV charging market"})
    client.post("/chat", json={"message": "Research the fintech market"})

    response = client.get("/research/sessions")

    assert response.status_code == 200
    titles = [s["title"] for s in response.json()["sessions"]]
    assert titles == ["Research the fintech market", "Research the EV charging market"]
    assert all(s["status"] == "clarifying" for s in response.json()["sessions"])


def test_get_research_status_unknown_thread_returns_404(client: TestClient) -> None:
    response = client.get("/research/does-not-exist")

    assert response.status_code == 404


def test_get_research_status_reflects_clarifying_then_done(client: TestClient) -> None:
    first = client.post("/chat", json={"message": "Research the EV charging market"})
    thread_id = first.json()["thread_id"]

    clarifying = client.get(f"/research/{thread_id}")
    assert clarifying.json()["status"] == "clarifying"
    assert clarifying.json()["report"] is None

    client.post("/chat", json={"thread_id": thread_id, "message": "Focus on the EU"})
    done = client.get(f"/research/{thread_id}")
    assert done.json()["status"] == "done"
    assert done.json()["report"] == "# EV Charging Market Report"


def test_get_research_report_before_done_returns_404(client: TestClient) -> None:
    first = client.post("/chat/stream", json={"message": "Research the EV charging market"})
    thread_id = _parse_sse(first.text)[0]["thread_id"]

    response = client.get(f"/research/{thread_id}/report")

    assert response.status_code == 404


def test_get_research_report_after_done_returns_report_and_sources(client: TestClient) -> None:
    first = client.post("/chat/stream", json={"message": "Research the EV charging market"})
    thread_id = _parse_sse(first.text)[0]["thread_id"]
    client.post("/chat/stream", json={"thread_id": thread_id, "message": "Focus on the EU"})

    response = client.get(f"/research/{thread_id}/report")

    assert response.status_code == 200
    body = response.json()
    assert body["report"] == "# EV Charging Market Report"
    assert body["sources"] == [{"topic": "EU", "summary": "EU findings"}]
