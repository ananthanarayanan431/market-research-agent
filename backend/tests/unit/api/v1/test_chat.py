from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.unit.api.v1.conftest import parse_sse


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
