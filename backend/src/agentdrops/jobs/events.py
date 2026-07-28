"""Redis pub/sub transport for live turn events: the worker publishes, `/chat/stream` relays."""

import json
from collections.abc import AsyncIterator
from typing import Any

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

_CHANNEL_PREFIX = "events:"


def _channel(thread_id: str) -> str:
    return f"{_CHANNEL_PREFIX}{thread_id}"


async def publish_event(redis: Redis, thread_id: str, event: dict[str, Any]) -> None:
    await redis.publish(_channel(thread_id), json.dumps(event))


async def open_subscription(redis: Redis, thread_id: str) -> PubSub:
    """Subscribe to `thread_id`'s channel and return the handle — split from `subscribe_events`
    so a caller can subscribe *before* triggering the work that will publish to it, closing the
    enqueue-then-subscribe race where an event published before the caller subscribes is lost
    forever (plain Redis pub/sub has no replay)."""
    pubsub = redis.pubsub()
    await pubsub.subscribe(_channel(thread_id))
    return pubsub


async def consume_subscription(pubsub: PubSub, thread_id: str) -> AsyncIterator[dict[str, Any]]:
    """Yield every event received on an already-subscribed `PubSub`, until the caller stops
    iterating or the connection drops."""
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            yield json.loads(message["data"])
    finally:
        await pubsub.unsubscribe(_channel(thread_id))
        await pubsub.aclose()  # type: ignore[no-untyped-call]  # redis-py's aclose() lacks type annotations


async def subscribe_events(redis: Redis, thread_id: str) -> AsyncIterator[dict[str, Any]]:
    """Yield every event published on `thread_id`'s channel until the caller stops iterating."""
    pubsub = await open_subscription(redis, thread_id)
    async for event in consume_subscription(pubsub, thread_id):
        yield event
