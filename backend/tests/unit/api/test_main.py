from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

import agentdrops.api.main as main_module
from tests.unit.agents.conftest import make_settings


class _FakeGraph:
    """Fake compiled graph: first turn per thread asks a clarification, second turn reports."""

    def __init__(self) -> None:
        self._turns: dict[str, int] = {}

    async def ainvoke(self, _inputs: dict, config: dict) -> dict:
        thread_id = config["configurable"]["thread_id"]
        turn = self._turns.get(thread_id, 0) + 1
        self._turns[thread_id] = turn
        if turn == 1:
            return {"messages": [AIMessage(content="Which region should I focus on?")]}
        return {
            "messages": [AIMessage(content="Report attached.")],
            "final_report": "# EV Charging Market Report",
        }


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
    assert body["thread_id"] != thread_id
