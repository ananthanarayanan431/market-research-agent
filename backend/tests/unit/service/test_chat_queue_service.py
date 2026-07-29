from datetime import UTC, datetime

import pytest

import agentdrops.service.chat_queue_service as chat_queue_service_module
from agentdrops.repository.sessions import SessionRecord
from agentdrops.service.chat_queue_service import ChatQueueService


class _FakeSessionStore:
    """Records every call so tests can assert both that a call happened and its order."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
        self._session = SessionRecord(
            thread_id="t1", title="Research the EV charging market", created_at=datetime.now(UTC)
        )

    async def touch(self, thread_id: str, *, title: str) -> SessionRecord:
        self.calls.append(("touch", (thread_id,), {"title": title}))
        return self._session

    async def set_status(self, thread_id: str, status: str, **kwargs: object) -> None:
        self.calls.append(("set_status", (thread_id, status), kwargs))

    async def get(self, thread_id: str) -> SessionRecord | None:
        self.calls.append(("get", (thread_id,), {}))
        return self._session


class _FakeDelay:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, thread_id: str, message: str, operation: str) -> None:
        self.calls.append((thread_id, message, operation))


async def test_enqueue_touches_and_resets_status_to_queued_before_dispatching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = _FakeSessionStore()
    fake_delay = _FakeDelay()
    monkeypatch.setattr(chat_queue_service_module.run_turn_task, "delay", fake_delay)
    service = ChatQueueService(sessions, object())  # type: ignore[arg-type]

    await service.enqueue("t1", "Research the EV charging market", operation="chat")

    assert sessions.calls == [
        ("touch", ("t1",), {"title": "Research the EV charging market"}),
        ("set_status", ("t1", "queued"), {}),
    ]
    assert fake_delay.calls == [("t1", "Research the EV charging market", "chat")]


async def test_enqueue_dispatches_run_turn_task_with_expected_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = _FakeSessionStore()
    fake_delay = _FakeDelay()
    monkeypatch.setattr(chat_queue_service_module.run_turn_task, "delay", fake_delay)
    service = ChatQueueService(sessions, object())  # type: ignore[arg-type]

    await service.enqueue("t2", "Focus on the EU", operation="chat_stream")

    assert fake_delay.calls == [("t2", "Focus on the EU", "chat_stream")]


async def test_mark_failed_sets_status_failed_with_error() -> None:
    sessions = _FakeSessionStore()
    service = ChatQueueService(sessions, object())  # type: ignore[arg-type]

    await service.mark_failed("t1", "boom")

    assert sessions.calls == [
        ("get", ("t1",), {}),
        ("set_status", ("t1", "failed"), {"error": "boom"}),
    ]


async def test_mark_failed_does_not_clobber_a_session_the_worker_already_settled() -> None:
    sessions = _FakeSessionStore()
    sessions._session.status = "done"
    service = ChatQueueService(sessions, object())  # type: ignore[arg-type]

    await service.mark_failed("t1", "boom")

    assert sessions.calls == [("get", ("t1",), {})]


async def test_mark_failed_marks_a_still_in_flight_session_failed() -> None:
    sessions = _FakeSessionStore()
    sessions._session.status = "running"
    service = ChatQueueService(sessions, object())  # type: ignore[arg-type]

    await service.mark_failed("t1", "boom")

    assert sessions.calls == [
        ("get", ("t1",), {}),
        ("set_status", ("t1", "failed"), {"error": "boom"}),
    ]
