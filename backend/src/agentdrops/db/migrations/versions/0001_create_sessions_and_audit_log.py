# backend/src/agentdrops/db/migrations/versions/0001_create_sessions_and_audit_log.py
"""create sessions and audit_log tables

Revision ID: 0001
Revises:
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'clarifying'")),
        sa.Column("report", sa.Text(), nullable=True),
        sa.Column("sources", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("thread_id"),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("detail", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["thread_id"], ["sessions.thread_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_log_thread_id", "audit_log", ["thread_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_log_thread_id", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("sessions")
