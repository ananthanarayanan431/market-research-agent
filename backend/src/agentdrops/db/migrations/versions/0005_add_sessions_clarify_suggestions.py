# backend/src/agentdrops/db/migrations/versions/0005_add_sessions_clarify_suggestions.py
"""add sessions.clarify_suggestions

Backs the LLM-generated example answers shown alongside a clarifying question
(`SessionStore.set_status(..., clarify_suggestions=...)`), so a reopened mid-clarification
session can show the same chips it showed live.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column(
            "clarify_suggestions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("sessions", "clarify_suggestions")
