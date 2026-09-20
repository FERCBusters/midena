"""replace public flag with diagram visibility

Revision ID: 0003_midena_diagram_visibility
Revises: 0002_midena_diagram_types
Create Date: 2026-06-19
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_midena_diagram_visibility"
down_revision = "0002_midena_diagram_types"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    if table_name not in _table_names():
        return set()
    return {col["name"] for col in sa.inspect(op.get_bind()).get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    if table_name not in _table_names():
        return set()
    return {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    if "diagrams" not in _table_names():
        return
    cols = _columns("diagrams")
    if "visibility" not in cols:
        op.add_column(
            "diagrams",
            sa.Column(
                "visibility",
                sa.String(length=32),
                nullable=False,
                server_default="private",
            ),
        )
        cols = _columns("diagrams")
    if {"visibility", "is_public"}.issubset(cols):
        op.execute(
            "UPDATE diagrams SET visibility = CASE WHEN is_public "
            "THEN 'public' ELSE 'private' END"
        )
    if "ix_diagrams_visibility" not in _indexes("diagrams"):
        op.create_index("ix_diagrams_visibility", "diagrams", ["visibility"])
    cols = _columns("diagrams")
    if "is_public" in cols:
        if "ix_diagrams_is_public" in _indexes("diagrams"):
            op.drop_index("ix_diagrams_is_public", table_name="diagrams")
        op.drop_column("diagrams", "is_public")


def downgrade() -> None:
    if "diagrams" not in _table_names():
        return
    cols = _columns("diagrams")
    if "is_public" not in cols:
        op.add_column(
            "diagrams",
            sa.Column(
                "is_public", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
        )
        cols = _columns("diagrams")
    if {"is_public", "visibility"}.issubset(cols):
        op.execute("UPDATE diagrams SET is_public = TRUE WHERE visibility = 'public'")
    if "ix_diagrams_is_public" not in _indexes("diagrams"):
        op.create_index("ix_diagrams_is_public", "diagrams", ["is_public"])
    if "visibility" in _columns("diagrams"):
        if "ix_diagrams_visibility" in _indexes("diagrams"):
            op.drop_index("ix_diagrams_visibility", table_name="diagrams")
        op.drop_column("diagrams", "visibility")
