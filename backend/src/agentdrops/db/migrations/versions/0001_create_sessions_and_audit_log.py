# backend/src/agentdrops/db/migrations/versions/0001_create_sessions_and_audit_log.py
"""create sessions and audit_log tables

Revision ID: 0001
Revises:
Create Date: 2026-07-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE sessions (
            thread_id   TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'clarifying',
            report      TEXT,
            sources     JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE audit_log (
            id          BIGSERIAL PRIMARY KEY,
            thread_id   TEXT NOT NULL REFERENCES sessions(thread_id) ON DELETE CASCADE,
            operation   TEXT NOT NULL,
            status      TEXT NOT NULL,
            detail      JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_audit_log_thread_id ON audit_log (thread_id)")


def downgrade() -> None:
    op.execute("DROP TABLE audit_log")
    op.execute("DROP TABLE sessions")
