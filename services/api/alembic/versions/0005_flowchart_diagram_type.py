"""flowchart diagram type and flowchart_text column

Revision ID: 0005_flowchart_diagram_type
Revises: 0004_midena_diagram_tags
Create Date: 2026-06-24

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005_flowchart_diagram_type"
down_revision = "0004_midena_diagram_tags"
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


def _indexes(table_name: str) -> set[str]:
    from alembic import op
    from sqlalchemy import inspect

    if table_name not in _table_names():
        return set()
    return {idx["name"] for idx in inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    version_cols = _columns("diagram_versions")

    if "sequence_text" not in version_cols:
        op.add_column(
            "diagram_versions",
            sa.Column("sequence_text", sa.Text(), nullable=True),
        )

    if "flowchart_text" not in version_cols:
        op.add_column(
            "diagram_versions",
            sa.Column("flowchart_text", sa.Text(), nullable=True),
        )

    version_indexes = _indexes("diagram_versions")
    if "ix_diagram_versions_diagram_type" not in version_indexes:
        op.create_index(
            "ix_diagram_versions_diagram_type", "diagram_versions", ["diagram_type"]
        )


def downgrade() -> None:
    if "diagram_versions" in _table_names():
        version_cols = _columns("diagram_versions")
        if "flowchart_text" in version_cols:
            op.drop_column("diagram_versions", "flowchart_text")
        if "sequence_text" in version_cols:
            op.drop_column("diagram_versions", "sequence_text")
        version_indexes = _indexes("diagram_versions")
        if "ix_diagram_versions_diagram_type" in version_indexes:
            op.drop_index(
                "ix_diagram_versions_diagram_type", table_name="diagram_versions"
            )
