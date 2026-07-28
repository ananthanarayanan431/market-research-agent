import asyncio
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from agentdrops.jobs.events import publish_event
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


async def test_chat_resets_a_stale_session_status_to_queued_on_a_new_turn(
    client: TestClient,
) -> None:
    """Regression test: a follow-up turn on a thread left `clarifying` by a previous turn must
    not stay `clarifying` forever — enqueue() must reset it to `queued` before the worker picks
    up the new turn."""
    sessions = client.app.state.sessions
    await sessions.touch("t-reset", title="Research the EV charging market")
    await sessions.set_status(
        "t-reset", "clarifying", clarify_question="Which region should I focus on?"
    )

    response = client.post("/v1/chat", json={"thread_id": "t-reset", "message": "Focus on the EU"})

    assert response.status_code == 200
    session = await sessions.get("t-reset")
    assert session is not None
    assert session.status == "queued"


async def test_chat_stream_receives_events_a_worker_publishes_after_subscribing(
    client: TestClient,
) -> None:
    """Proves the subscribe-before-enqueue ordering: a message published shortly after the
    request is issued must still be delivered, because the API is already subscribed by the
    time anything could publish."""
    thread_id = "t-live"
    redis = client.app.state.redis
    transport = httpx.ASGITransport(app=client.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        request_task = asyncio.ensure_future(
            async_client.post(
                "/v1/chat/stream",
                json={"thread_id": thread_id, "message": "Research the EV charging market"},
            )
        )
        await asyncio.sleep(0.05)  # let /chat/stream subscribe before the "worker" publishes
        await publish_event(redis, thread_id, {"type": "progress", "step": "Planning"})
        await publish_event(
            redis, thread_id, {"type": "done", "thread_id": thread_id, "report": "# New Report"}
        )
        response = await request_task

    events = parse_sse(response.text)
    assert events == [
        {"type": "progress", "step": "Planning"},
        {"type": "done", "thread_id": thread_id, "report": "# New Report"},
    ]


async def test_chat_stream_follow_up_turn_streams_live_events_not_stale_status(
    client: TestClient,
) -> None:
    """Regression test for the Critical bug: a follow-up turn on a thread already `clarifying`
    from a PREVIOUS turn must not replay that stale event — it must reset to `queued` (Fix 1)
    and stream the new turn's own live events instead (Fix 4)."""
    thread_id = "t-followup"
    sessions = client.app.state.sessions
    await sessions.touch(thread_id, title="Research the EV charging market")
    await sessions.set_status(
        thread_id, "clarifying", clarify_question="Which region should I focus on? (stale)"
    )
    redis = client.app.state.redis
    transport = httpx.ASGITransport(app=client.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        request_task = asyncio.ensure_future(
            async_client.post(
                "/v1/chat/stream", json={"thread_id": thread_id, "message": "Focus on the EU"}
            )
        )
        await asyncio.sleep(0.05)
        await publish_event(
            redis, thread_id, {"type": "done", "thread_id": thread_id, "report": "# New Report"}
        )
        response = await request_task

    events = parse_sse(response.text)
    assert events == [{"type": "done", "thread_id": thread_id, "report": "# New Report"}]


async def test_chat_stream_emits_error_event_if_subscription_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dropped Redis connection mid-subscribe must surface as an `error` SSE event, not hang
    the response open with nothing ever arriving."""
    import agentdrops.api.v1.chat as chat_module

    async def _broken_open_subscription(_redis: Any, _thread_id: str) -> Any:
        raise ConnectionError("connection to Redis lost")

    monkeypatch.setattr(chat_module, "open_subscription", _broken_open_subscription)

    response = client.post("/v1/chat/stream", json={"message": "Research the EV charging market"})

    events = parse_sse(response.text)
    assert events == [
        {
            "type": "error",
            "thread_id": events[0]["thread_id"],
            "message": "connection to Redis lost",
        }
    ]
