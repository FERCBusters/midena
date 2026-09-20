"""initial MIDENA schema

Revision ID: 0001_initial_midena
Revises:
Create Date: 2026-06-18
"""

from __future__ import annotations

from alembic import op

from app.db.session import Base
import app.db.models  # noqa: F401 - registers models with Base.metadata

revision = "0001_initial_midena"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
