# backend/src/agentdrops/db/migrations/versions/0003_index_sessions_created_at.py
"""index sessions.created_at

`SessionStore.list_recent` (repository/sessions.py) orders by `created_at DESC` with no
supporting index, forcing a full-table sort as sessions accumulate.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_sessions_created_at", "sessions", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_sessions_created_at", table_name="sessions")
