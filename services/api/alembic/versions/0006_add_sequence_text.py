"""add missing sequence_text column

Revision ID: 0006_add_sequence_text
Revises: 0005_flowchart_diagram_type
Create Date: 2026-06-24

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006_add_sequence_text"
down_revision = "0005_flowchart_diagram_type"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    from alembic import op
    from sqlalchemy import inspect

    return set(inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    from alembic import op
    from sqlalchemy import inspect

    if table_name not in _table_names():
        return set()
    return {col["name"] for col in inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    version_cols = _columns("diagram_versions")

    if "sequence_text" not in version_cols:
        op.add_column(
            "diagram_versions",
            sa.Column("sequence_text", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    if "diagram_versions" in _table_names():
        version_cols = _columns("diagram_versions")
        if "sequence_text" in version_cols:
            op.drop_column("diagram_versions", "sequence_text")
