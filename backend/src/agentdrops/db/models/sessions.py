"""ORM mapping for the `sessions` table (`db/migrations/versions/0001_...py`)."""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SessionTable(Base):
    __tablename__ = "sessions"

    thread_id: Mapped[str] = mapped_column(sa.Text(), primary_key=True)
    title: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    status: Mapped[str] = mapped_column(
        sa.Text(), nullable=False, server_default=sa.text("'queued'")
    )
    report: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    clarify_question: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    clarify_suggestions: Mapped[list[str]] = mapped_column(
        JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    error: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    sources: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    pinned: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, server_default=sa.text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        onupdate=sa.text("now()"),
        nullable=False,
    )
