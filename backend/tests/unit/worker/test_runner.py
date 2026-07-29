import json
from collections.abc import AsyncIterator
from typing import Any

from fakeredis.aioredis import FakeRedis

from agentdrops.service.chat_service import ChatService
from agentdrops.worker.runner import TURN_FAILED_MESSAGE, run_turn


class _FakeSessions:
    def __init__(self) -> None:
        self.statuses: list[tuple[str, str]] = []

    async def touch(self, thread_id: str, *, title: str) -> None:
        return None

    async def set_status(self, thread_id: str, status: str, **_kwargs: object) -> None:
        self.statuses.append((thread_id, status))

    async def add_source(self, thread_id: str, topic: str, summary: str) -> None:
        return None


class _FakeAudit:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    async def record(self, thread_id: str, **kwargs: object) -> None:
        self.records.append({"thread_id": thread_id, **kwargs})


class _FakeGraph:
    """Streams a clarify turn immediately — enough to exercise the publish path without
    re-testing `ChatService.run_turn`'s own node-mapping logic (already covered by
    `tests/unit/api/v1/test_chat.py`)."""

    async def astream(
        self, _inputs: dict, config: dict, stream_mode: list[str]
    ) -> AsyncIterator[tuple[str, dict]]:
        yield (
            "updates",
            {
                "clarify_with_user": {
                    "needs_clarification": True,
                    "messages": [_Message("Which region should I focus on?")],
                }
            },
        )


class _Message:
    def __init__(self, content: str) -> None:
        self.content = content


class _FailingGraph:
    async def astream(
        self, _inputs: dict, config: dict, stream_mode: list[str]
    ) -> AsyncIterator[tuple[str, dict]]:
        raise RuntimeError("LLM provider unavailable")
        yield ("updates", {})  # pragma: no cover — makes this an async generator


async def _published(redis: FakeRedis, thread_id: str) -> list[dict[str, Any]]:
    raw = await redis.lrange(f"_test_published:{thread_id}", 0, -1)
    return [json.loads(r) for r in raw]


class _RecordingRedis(FakeRedis):
    """Records every `publish` call to a list key, so the test can assert on emitted events
    without a second pub/sub subscriber (already covered by `tests/unit/jobs/test_events.py`)."""

    async def publish(self, channel: str, message: str) -> int:  # type: ignore[override]
        await self.rpush(f"_test_published:{channel.removeprefix('events:')}", message)
        return 1


async def test_run_turn_publishes_every_event_from_chat_service() -> None:
    redis = _RecordingRedis(decode_responses=True)
    sessions = _FakeSessions()
    audit = _FakeAudit()
    chat_service = ChatService(_FakeGraph(), sessions, audit)  # type: ignore[arg-type]

    await run_turn(
        chat_service, "t1", "Research the EV market", operation="chat_stream", redis=redis
    )

    published = await _published(redis, "t1")
    assert published == [
        {"type": "clarify", "thread_id": "t1", "response": "Which region should I focus on?"}
    ]
    assert sessions.statuses == [("t1", "clarifying")]


async def test_run_turn_records_failure_and_publishes_error_on_exception() -> None:
    redis = _RecordingRedis(decode_responses=True)
    sessions = _FakeSessions()
    audit = _FakeAudit()
    chat_service = ChatService(_FailingGraph(), sessions, audit)  # type: ignore[arg-type]

    await run_turn(chat_service, "t1", "Research the EV market", operation="chat", redis=redis)

    published = await _published(redis, "t1")
    assert published == [{"type": "error", "thread_id": "t1", "message": TURN_FAILED_MESSAGE}]
    assert sessions.statuses == [("t1", "failed")]
    assert audit.records == [
        {
            "thread_id": "t1",
            "operation": "chat",
            "status": "failed",
            "detail": {"error": "LLM provider unavailable"},
        }
    ]
