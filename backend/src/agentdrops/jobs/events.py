"""Redis pub/sub transport for live turn events: the worker publishes, `/chat/stream` relays."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

_CHANNEL_PREFIX = "events:"


def _channel(thread_id: str) -> str:
    return f"{_CHANNEL_PREFIX}{thread_id}"


async def publish_event(redis: Redis, thread_id: str, event: dict[str, Any]) -> None:
    await redis.publish(_channel(thread_id), json.dumps(event))


@asynccontextmanager
async def open_subscription(redis: Redis, thread_id: str) -> AsyncIterator[PubSub]:
    """Subscribe to `thread_id`'s channel for the duration of the context — subscribing before
    triggering the work that will publish to it closes the enqueue-then-subscribe race where an
    event published before the caller subscribes is lost forever (plain Redis pub/sub has no
    replay). Owning cleanup as a context manager (rather than leaving it to the first
    consumer of the subscription) guarantees the subscription and connection are released even
    if the caller's block raises before ever consuming an event — e.g. if enqueueing the
    triggering work fails."""
    pubsub = redis.pubsub()
    await pubsub.subscribe(_channel(thread_id))
    try:
        yield pubsub
    finally:
        await pubsub.unsubscribe(_channel(thread_id))
        await pubsub.aclose()  # type: ignore[no-untyped-call]  # redis-py's aclose() lacks type annotations


async def consume_subscription(pubsub: PubSub) -> AsyncIterator[dict[str, Any]]:
    """Yield every event received on an already-subscribed `PubSub`, until the caller stops
    iterating. Does not own the subscription's lifecycle — see `open_subscription`."""
    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        yield json.loads(message["data"])


async def subscribe_events(redis: Redis, thread_id: str) -> AsyncIterator[dict[str, Any]]:
    """Yield every event published on `thread_id`'s channel until the caller stops iterating."""
    async with open_subscription(redis, thread_id) as pubsub:
        async for event in consume_subscription(pubsub):
            yield event
