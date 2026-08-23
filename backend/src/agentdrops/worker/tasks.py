"""Celery task entrypoint: bridges Celery's synchronous task execution into the async
graph/service/Redis stack. This is the only place `asyncio.run` appears, since everything it
calls into (the graph, repositories, services, pub/sub) is async."""

import asyncio
import logging

import httpx
from redis.asyncio import Redis

from agentdrops.agents.checkpointer import checkpointer
from agentdrops.agents.contexthub.chunk import chunk_text
from agentdrops.agents.contexthub.embeddings import EmbeddingClient
from agentdrops.agents.contexthub.extract import extract_file_text, fetch_url_text
from agentdrops.agents.graph import build_market_researcher
from agentdrops.config import Settings, get_settings
from agentdrops.db.engine import create_engine, create_session_factory
from agentdrops.jobs.events import publish_event
from agentdrops.repository.audit import AuditLog
from agentdrops.repository.contexthub import ContextHubStore
from agentdrops.repository.sessions import SessionStore
from agentdrops.service.chat_service import ChatService
from agentdrops.storage.contexthub import ContextHubStorage
from agentdrops.worker.celery_app import celery_app
from agentdrops.worker.runner import TURN_FAILED_MESSAGE, run_turn

logger = logging.getLogger(__name__)


async def _execute(thread_id: str, message: str, operation: str, settings: Settings) -> None:
    redis: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        engine = create_engine(settings)
        try:
            session_factory = create_session_factory(engine)
            sessions = SessionStore(session_factory)
            audit = AuditLog(session_factory)
            try:
                async with (
                    httpx.AsyncClient(timeout=30.0) as client,
                    checkpointer(settings) as saver,
                ):
                    graph = build_market_researcher(settings, client, saver)
                    chat_service = ChatService(graph, sessions, audit)
                    await run_turn(
                        chat_service, thread_id, message, operation=operation, redis=redis
                    )
            except Exception as exc:
                # Only construction (engine/httpx/checkpointer/graph) reaches here — turn-time
                # failures are already caught and reported by `run_turn` itself, which does not
                # re-raise. Without this, a failure here (e.g. Postgres unreachable) would leave
                # the session stuck at its prior status with no terminal event ever published.
                logger.exception("worker setup failed for thread_id=%s", thread_id)
                await sessions.set_status(thread_id, "failed", error=str(exc))
                await audit.record(
                    thread_id, operation=operation, status="failed", detail={"error": str(exc)}
                )
                await publish_event(
                    redis,
                    thread_id,
                    {"type": "error", "thread_id": thread_id, "message": TURN_FAILED_MESSAGE},
                )
        finally:
            await engine.dispose()
    finally:
        await redis.aclose()


@celery_app.task(name="agentdrops.run_turn")  # type: ignore[untyped-decorator]
def run_turn_task(thread_id: str, message: str, operation: str) -> None:
    asyncio.run(_execute(thread_id, message, operation, get_settings()))


async def _execute_ingest(document_id: str, settings: Settings) -> None:
    engine = create_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        store = ContextHubStore(session_factory)
        storage = ContextHubStorage(settings)
        async with httpx.AsyncClient(timeout=30.0) as client:
            embedder = EmbeddingClient(
                api_key=settings.embedding_api_key,
                base_url=settings.embedding_base_url,
                model=settings.embedding_model,
                client=client,
            )
            try:
                document = await store.get_document(document_id)
                assert document is not None, f"unknown contexthub document_id={document_id}"

                if document.source_type == "url":
                    text = await fetch_url_text(document.source_name, client)
                else:
                    assert document.minio_key is not None
                    raw = await storage.get(document.minio_key)
                    text = extract_file_text(document.content_type, raw)

                chunks = chunk_text(
                    text, settings.contexthub_chunk_size, settings.contexthub_chunk_overlap
                )
                embeddings = await embedder.embed(chunks)
                await store.insert_chunks(document.id, chunks, embeddings)
                await store.mark_ready(document.id)
            except Exception as exc:
                logger.exception("contexthub ingestion failed for document_id=%s", document_id)
                await store.mark_failed(document_id, str(exc))
    finally:
        await engine.dispose()


@celery_app.task(name="agentdrops.ingest_contexthub_document")  # type: ignore[untyped-decorator]
def ingest_contexthub_document_task(document_id: str) -> None:
    asyncio.run(_execute_ingest(document_id, get_settings()))
