"""Declarative base for the ORM schema models.

These models are the runtime data-access layer for `agentdrops.repository` *and* the
autogenerate source-of-truth for Alembic (`db/migrations/env.py`'s `target_metadata`).
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
