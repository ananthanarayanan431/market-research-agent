"""ORM mapping for the `audit_log` table (`db/migrations/versions/0001_...py`).

Named `AuditLogTable`, not `AuditLog`, to keep it visually distinct from
`agentdrops.repository.audit.AuditLog` (the data-access class that actually queries this table).
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AuditLogTable(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(sa.BigInteger(), primary_key=True)
    thread_id: Mapped[str] = mapped_column(
        sa.Text(),
        sa.ForeignKey("sessions.thread_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    operation: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    status: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    detail: Mapped[dict[str, object]] = mapped_column(
        JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )
