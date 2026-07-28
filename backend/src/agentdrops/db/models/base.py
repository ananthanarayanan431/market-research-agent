"""Declarative base for the ORM schema models.

These models are the runtime data-access layer for `agentdrops.repository` *and* the
autogenerate source-of-truth for Alembic (`db/migrations/env.py`'s `target_metadata`).
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Fixed constraint-naming convention so `alembic revision --autogenerate` always emits
# deterministic constraint/index names, instead of dialect-dependent auto-generated ones that
# make later `alter_column`/`drop_constraint` migrations depend on guessing the live name.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
