# backend/src/agentdrops/db/migrations/versions/0006_add_contexthub_tables.py
"""add contexthub_documents and contexthub_chunks

Global knowledge-base tables backing agents/contexthub/ — the `context_hub_search` tool's
retrieval store. Requires the pgvector extension (image already switched to
pgvector/pgvector:pg16 in docker-compose.yml).

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

EMBEDDING_DIM = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "contexthub_documents",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'processing'")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("minio_key", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_contexthub_documents_created_at", "contexthub_documents", ["created_at"]
    )

    op.create_table(
        "contexthub_chunks",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "document_id", sa.Text(),
            sa.ForeignKey(
                "contexthub_documents.id", ondelete="CASCADE",
                name="fk_contexthub_chunks_document_id_contexthub_documents",
            ),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
    )
    op.create_index("ix_contexthub_chunks_document_id", "contexthub_chunks", ["document_id"])
    op.execute(
        "CREATE INDEX ix_contexthub_chunks_embedding ON contexthub_chunks "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    op.drop_index("ix_contexthub_chunks_embedding", table_name="contexthub_chunks")
    op.drop_index("ix_contexthub_chunks_document_id", table_name="contexthub_chunks")
    op.drop_table("contexthub_chunks")
    op.drop_index("ix_contexthub_documents_created_at", table_name="contexthub_documents")
    op.drop_table("contexthub_documents")
