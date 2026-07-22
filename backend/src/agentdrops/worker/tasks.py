"""Celery task entrypoint: bridges Celery's synchronous task execution into the async
graph/service/Redis stack. This is the only place `asyncio.run` appears, since everything it
calls into (the graph, repositories, services, pub/sub) is async."""

import asyncio

import httpx
from redis.asyncio import Redis

from agentdrops.agents.checkpointer import checkpointer
from agentdrops.agents.graph import build_market_researcher
from agentdrops.config import Settings, get_settings
from agentdrops.db.engine import create_engine, create_session_factory
from agentdrops.repository.audit import AuditLog
from agentdrops.repository.sessions import SessionStore
from agentdrops.service.chat_service import ChatService
from agentdrops.worker.celery_app import celery_app
from agentdrops.worker.runner import run_turn


async def _execute(thread_id: str, message: str, operation: str, settings: Settings) -> None:
    redis: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        engine = create_engine(settings)
        try:
            async with (
                httpx.AsyncClient(timeout=30.0) as client,
                checkpointer(settings) as saver,
            ):
                session_factory = create_session_factory(engine)
                graph = build_market_researcher(settings, client, saver)
                sessions = SessionStore(session_factory)
                audit = AuditLog(session_factory)
                chat_service = ChatService(graph, sessions, audit)
                await run_turn(chat_service, thread_id, message, operation=operation, redis=redis)
        finally:
            await engine.dispose()
    finally:
        await redis.aclose()


@celery_app.task(name="agentdrops.run_turn")  # type: ignore[untyped-decorator]
def run_turn_task(thread_id: str, message: str, operation: str) -> None:
    asyncio.run(_execute(thread_id, message, operation, get_settings()))
