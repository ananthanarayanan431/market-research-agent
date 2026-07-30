"""add queued status default and clarify_question/error columns

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("sessions", "status", server_default=sa.text("'queued'"))
    op.add_column("sessions", sa.Column("clarify_question", sa.Text(), nullable=True))
    op.add_column("sessions", sa.Column("error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "error")
    op.drop_column("sessions", "clarify_question")
    op.alter_column("sessions", "status", server_default=sa.text("'clarifying'"))
