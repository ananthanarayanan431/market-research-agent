"""ORM mapping for `contexthub_documents`/`contexthub_chunks`
(`db/migrations/versions/0006_add_contexthub_tables.py`)."""

from datetime import datetime

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

EMBEDDING_DIM = 1536
"""Matches `text-embedding-3-small`; a different embedding model needs its own migration."""


class ContextHubDocumentTable(Base):
    __tablename__ = "contexthub_documents"

    id: Mapped[str] = mapped_column(sa.Text(), primary_key=True)
    title: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    source_type: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    source_name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    content_type: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    status: Mapped[str] = mapped_column(
        sa.Text(), nullable=False, server_default=sa.text("'processing'")
    )
    error: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    minio_key: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        onupdate=sa.text("now()"),
        nullable=False,
    )


class ContextHubChunkTable(Base):
    __tablename__ = "contexthub_chunks"

    id: Mapped[str] = mapped_column(sa.Text(), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        sa.Text(),
        sa.ForeignKey("contexthub_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    content: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
