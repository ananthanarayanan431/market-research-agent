import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

import agentdrops.service.chat_queue_service as chat_queue_service_module
from agentdrops.jobs.events import publish_event
from tests.unit.api.v1.conftest import parse_sse
from tests.unit.api.v1.conftest import run_turn as _run_turn


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

    @asynccontextmanager
    async def _broken_open_subscription(_redis: Any, _thread_id: str) -> AsyncIterator[Any]:
        raise ConnectionError("connection to Redis lost")
        yield  # pragma: no cover — makes this an async generator; never reached

    monkeypatch.setattr(chat_queue_service_module, "open_subscription", _broken_open_subscription)

    response = client.post("/v1/chat/stream", json={"message": "Research the EV charging market"})

    events = parse_sse(response.text)
    assert events == [
        {
            "type": "error",
            "thread_id": events[0]["thread_id"],
            "message": chat_queue_service_module._STREAM_ENQUEUE_ERROR_MESSAGE,
        }
    ]


async def test_chat_stream_emits_error_event_if_enqueue_fails_after_subscribing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Enqueueing can fail (e.g. a DB error in `touch`/`set_status`, or a broker error from
    `.delay()`) after the subscription is already open — the `async with` around
    `open_subscription` must still let that exception propagate out to the router's own
    error handling, not swallow it during cleanup."""

    async def _broken_enqueue(_thread_id: str, _message: str, *, operation: str) -> None:
        raise RuntimeError("enqueue failed")

    queue = client.app.state.chat_queue_service
    monkeypatch.setattr(queue, "enqueue", _broken_enqueue)

    response = client.post("/v1/chat/stream", json={"message": "Research the EV charging market"})

    events = parse_sse(response.text)
    assert events == [
        {
            "type": "error",
            "thread_id": events[0]["thread_id"],
            "message": chat_queue_service_module._STREAM_ENQUEUE_ERROR_MESSAGE,
        }
    ]


async def test_chat_returns_502_even_if_mark_failed_itself_raises(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`mark_failed` is itself a database write and can fail independently of the enqueue error
    it's trying to record — that must not prevent the client from still getting its 502, which
    is the whole point of the except block in `chat`."""

    async def _broken_enqueue(_thread_id: str, _message: str, *, operation: str) -> None:
        raise RuntimeError("enqueue failed")

    async def _broken_mark_failed(_thread_id: str, _error: str) -> None:
        raise RuntimeError("mark_failed failed too")

    queue = client.app.state.chat_queue_service
    monkeypatch.setattr(queue, "enqueue", _broken_enqueue)
    monkeypatch.setattr(queue, "mark_failed", _broken_mark_failed)

    response = client.post("/v1/chat", json={"message": "Research the EV charging market"})

    assert response.status_code == 502


async def test_chat_stream_still_emits_error_event_even_if_mark_failed_itself_raises(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same concern as above, for the streaming route: if `mark_failed` raises while handling an
    enqueue failure, the client must still get an `error` SSE event, not a silently truncated
    stream."""

    async def _broken_enqueue(_thread_id: str, _message: str, *, operation: str) -> None:
        raise RuntimeError("enqueue failed")

    async def _broken_mark_failed(_thread_id: str, _error: str) -> None:
        raise RuntimeError("mark_failed failed too")

    queue = client.app.state.chat_queue_service
    monkeypatch.setattr(queue, "enqueue", _broken_enqueue)
    monkeypatch.setattr(queue, "mark_failed", _broken_mark_failed)

    response = client.post("/v1/chat/stream", json={"message": "Research the EV charging market"})

    events = parse_sse(response.text)
    assert events == [
        {
            "type": "error",
            "thread_id": events[0]["thread_id"],
            "message": chat_queue_service_module._STREAM_ENQUEUE_ERROR_MESSAGE,
        }
    ]


async def test_run_turn_records_audit_row_for_clarify(client: TestClient) -> None:
    """Restores audit-log coverage for the clarify path, deleted when execution moved off the
    request/response cycle — `ChatService.run_turn` (now only called by the Celery worker via
    `worker/runner.py`) is still the one place that writes this audit row."""
    thread_id = str(uuid.uuid4())
    await _run_turn(client, thread_id, "Research the EV charging market", operation="chat")

    audit = client.app.state.audit.records
    assert len(audit) == 1
    assert audit[0] == {
        "thread_id": thread_id,
        "operation": "chat",
        "status": "clarify",
        "detail": {},
    }


async def test_run_turn_clarify_event_includes_suggestions(client: TestClient) -> None:
    thread_id = str(uuid.uuid4())
    events = []
    service = client.app.state.chat_service
    async for event in service.run_turn(
        thread_id, "Research the EV charging market", operation="chat"
    ):
        events.append(event)

    clarify_events = [e for e in events if e["type"] == "clarify"]
    assert len(clarify_events) == 1
    assert clarify_events[0]["suggestions"] == ["North America", "Global", "EU only"]


async def test_run_turn_records_audit_row_for_done(client: TestClient) -> None:
    thread_id = str(uuid.uuid4())
    await _run_turn(client, thread_id, "Research the EV charging market", operation="chat_stream")
    await _run_turn(client, thread_id, "Focus on the EU", operation="chat_stream")

    audit = client.app.state.audit.records
    assert len(audit) == 2
    assert audit[1] == {
        "thread_id": thread_id,
        "operation": "chat_stream",
        "status": "done",
        "detail": {"report_chars": len("# EV Charging Market Report")},
    }
