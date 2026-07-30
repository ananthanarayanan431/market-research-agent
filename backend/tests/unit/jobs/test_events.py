import asyncio

import pytest
from fakeredis import FakeServer
from fakeredis.aioredis import FakeRedis

from agentdrops.jobs.events import publish_event, subscribe_events


@pytest.fixture
def shared_server() -> FakeServer:
    """`subscribe_events` and `publish_event` run against separate Redis client instances in
    prod (API vs. worker process) — sharing one FakeServer reproduces that across two fake
    clients, since a single FakeRedis instance's pubsub never sees another instance's publish."""
    return FakeServer()


async def test_subscribe_receives_a_published_event(shared_server: FakeServer) -> None:
    publisher = FakeRedis(server=shared_server, decode_responses=True)
    subscriber = FakeRedis(server=shared_server, decode_responses=True)

    events = subscribe_events(subscriber, "t1")
    first_event = asyncio.ensure_future(events.__anext__())
    await asyncio.sleep(0.05)  # let the subscribe() call land before publishing
    await publish_event(publisher, "t1", {"type": "progress", "step": "Planning"})

    assert await first_event == {"type": "progress", "step": "Planning"}


async def test_subscribe_only_receives_its_own_thread_id(shared_server: FakeServer) -> None:
    publisher = FakeRedis(server=shared_server, decode_responses=True)
    subscriber = FakeRedis(server=shared_server, decode_responses=True)

    events = subscribe_events(subscriber, "t1")
    first_event = asyncio.ensure_future(events.__anext__())
    await asyncio.sleep(0.05)
    await publish_event(publisher, "other-thread", {"type": "progress", "step": "Ignored"})
    await publish_event(publisher, "t1", {"type": "progress", "step": "Mine"})

    assert await first_event == {"type": "progress", "step": "Mine"}
