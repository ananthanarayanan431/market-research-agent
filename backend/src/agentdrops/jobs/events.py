"""Redis pub/sub transport for live turn events: the worker publishes, `/chat/stream` relays."""

import json
from collections.abc import AsyncIterator
from typing import Any

from redis.asyncio import Redis

_CHANNEL_PREFIX = "events:"


def _channel(thread_id: str) -> str:
    return f"{_CHANNEL_PREFIX}{thread_id}"


async def publish_event(redis: Redis, thread_id: str, event: dict[str, Any]) -> None:
    await redis.publish(_channel(thread_id), json.dumps(event))


async def subscribe_events(redis: Redis, thread_id: str) -> AsyncIterator[dict[str, Any]]:
    """Yield every event published on `thread_id`'s channel until the caller stops iterating."""
    pubsub = redis.pubsub()
    await pubsub.subscribe(_channel(thread_id))
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            yield json.loads(message["data"])
    finally:
        await pubsub.unsubscribe(_channel(thread_id))
        await pubsub.aclose()  # type: ignore[no-untyped-call]  # redis-py's aclose() lacks type annotations
