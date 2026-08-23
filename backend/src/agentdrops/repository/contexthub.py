"""Postgres-backed Context Hub document/chunk registry: CRUD for uploaded documents plus
pgvector cosine-similarity search over their chunks. Global (no thread_id) — see
db/migrations/versions/0006_add_contexthub_tables.py for the schema."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentdrops.db.models import ContextHubChunkTable, ContextHubDocumentTable

Status = Literal["processing", "ready", "failed"]


@dataclass
class ContextHubDocumentRecord:
    id: str
    title: str
    source_type: str
    source_name: str
    content_type: str
    status: Status
    created_at: datetime
    error: str | None = None
    minio_key: str | None = None


@dataclass
class ContextHubChunkMatch:
    document_id: str
    document_title: str
    content: str
    distance: float


def _to_record(row: ContextHubDocumentTable) -> ContextHubDocumentRecord:
    return ContextHubDocumentRecord(
        id=row.id,
        title=row.title,
        source_type=row.source_type,
        source_name=row.source_name,
        content_type=row.content_type,
        status=row.status,  # type: ignore[arg-type]
        created_at=row.created_at,
        error=row.error,
        minio_key=row.minio_key,
    )


class ContextHubStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_document(
        self, *, title: str, source_type: str, source_name: str, content_type: str
    ) -> ContextHubDocumentRecord:
        async with self._session_factory() as session:
            row = ContextHubDocumentTable(
                id=str(uuid.uuid4()),
                title=title,
                source_type=source_type,
                source_name=source_name,
                content_type=content_type,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _to_record(row)

    async def set_minio_key(self, document_id: str, minio_key: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(ContextHubDocumentTable)
                .where(ContextHubDocumentTable.id == document_id)
                .values(minio_key=minio_key)
            )
            await session.commit()

    async def mark_ready(self, document_id: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(ContextHubDocumentTable)
                .where(ContextHubDocumentTable.id == document_id)
                .values(status="ready", error=None)
            )
            await session.commit()

    async def mark_failed(self, document_id: str, error: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(ContextHubDocumentTable)
                .where(ContextHubDocumentTable.id == document_id)
                .values(status="failed", error=error)
            )
            await session.commit()

    async def get_document(self, document_id: str) -> ContextHubDocumentRecord | None:
        async with self._session_factory() as session:
            row = await session.get(ContextHubDocumentTable, document_id)
            return _to_record(row) if row is not None else None

    async def list_documents(self) -> list[ContextHubDocumentRecord]:
        async with self._session_factory() as session:
            stmt = select(ContextHubDocumentTable).order_by(
                ContextHubDocumentTable.created_at.desc()
            )
            result = await session.execute(stmt)
            return [_to_record(row) for row in result.scalars().all()]

    async def delete_document(self, document_id: str) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                delete(ContextHubDocumentTable)
                .where(ContextHubDocumentTable.id == document_id)
                .returning(ContextHubDocumentTable.id)
            )
            deleted = result.scalar_one_or_none() is not None
            await session.commit()
            return deleted

    async def insert_chunks(
        self, document_id: str, chunks: list[str], embeddings: list[list[float]]
    ) -> None:
        async with self._session_factory() as session:
            rows = [
                ContextHubChunkTable(
                    id=str(uuid.uuid4()),
                    document_id=document_id,
                    chunk_index=index,
                    content=content,
                    embedding=embedding,
                )
                for index, (content, embedding) in enumerate(zip(chunks, embeddings, strict=True))
            ]
            session.add_all(rows)
            await session.commit()

    async def search_chunks(self, embedding: list[float], top_k: int) -> list[ContextHubChunkMatch]:
        async with self._session_factory() as session:
            distance = ContextHubChunkTable.embedding.cosine_distance(embedding)
            stmt = (
                select(
                    ContextHubChunkTable.document_id,
                    ContextHubDocumentTable.title,
                    ContextHubChunkTable.content,
                    distance.label("distance"),
                )
                .join(
                    ContextHubDocumentTable,
                    ContextHubChunkTable.document_id == ContextHubDocumentTable.id,
                )
                .where(ContextHubDocumentTable.status == "ready")
                .order_by(distance)
                .limit(top_k)
            )
            result = await session.execute(stmt)
            return [
                ContextHubChunkMatch(
                    document_id=row.document_id,
                    document_title=row.title,
                    content=row.content,
                    distance=row.distance,
                )
                for row in result.all()
            ]
