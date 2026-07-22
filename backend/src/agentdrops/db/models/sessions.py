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
        sa.Text(), nullable=False, server_default=sa.text("'clarifying'")
    )
    report: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    sources: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )
