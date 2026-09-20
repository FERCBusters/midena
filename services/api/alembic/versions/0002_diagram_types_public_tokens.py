"""diagram types, hard-to-guess embeds, metadata links and shares

Revision ID: 0002_midena_diagram_types
Revises: 0001_initial_midena
Create Date: 2026-06-19
"""

from __future__ import annotations

from alembic import op
import secrets
import sqlalchemy as sa

revision = "0002_midena_diagram_types"
down_revision = "0001_initial_midena"
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
    bind = op.get_bind()
    diagram_cols = _columns("diagrams")
    version_cols = _columns("diagram_versions")

    if "public_token" not in diagram_cols:
        op.add_column(
            "diagrams",
            sa.Column("public_token", sa.String(length=96), nullable=True),
        )
    if "diagram_type" not in diagram_cols:
        op.add_column(
            "diagrams",
            sa.Column(
                "diagram_type",
                sa.String(length=32),
                nullable=False,
                server_default="bpmn",
            ),
        )
    if "diagram_type" not in version_cols:
        op.add_column(
            "diagram_versions",
            sa.Column(
                "diagram_type",
                sa.String(length=32),
                nullable=False,
                server_default="bpmn",
            ),
        )
    if "source_text" not in version_cols:
        op.add_column(
            "diagram_versions", sa.Column("source_text", sa.Text(), nullable=True)
        )

    diagram_cols = _columns("diagrams")
    version_cols = _columns("diagram_versions")
    if {"source_text", "bpmn_xml"}.issubset(version_cols):
        bind.execute(
            sa.text(
                "UPDATE diagram_versions SET source_text = bpmn_xml "
                "WHERE source_text IS NULL"
            )
        )
    if "public_token" in diagram_cols:
        diagram_rows = bind.execute(
            sa.text(
                "SELECT id FROM diagrams WHERE public_token IS NULL OR public_token = ''"
            )
        ).all()
        for (diagram_id,) in diagram_rows:
            bind.execute(
                sa.text("UPDATE diagrams SET public_token = :token WHERE id = :id"),
                {"token": secrets.token_urlsafe(36), "id": diagram_id},
            )
        op.alter_column("diagrams", "public_token", nullable=False)

    diagram_indexes = _indexes("diagrams")
    version_indexes = _indexes("diagram_versions")
    if "ix_diagrams_public_token" not in diagram_indexes:
        op.create_index(
            "ix_diagrams_public_token", "diagrams", ["public_token"], unique=True
        )
    if "ix_diagrams_diagram_type" not in diagram_indexes:
        op.create_index("ix_diagrams_diagram_type", "diagrams", ["diagram_type"])
    if "ix_diagram_versions_diagram_type" not in version_indexes:
        op.create_index(
            "ix_diagram_versions_diagram_type", "diagram_versions", ["diagram_type"]
        )

    tables = _table_names()
    if "diagram_metadata_links" not in tables:
        op.create_table(
            "diagram_metadata_links",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("diagram_id", sa.Integer(), nullable=False),
            sa.Column("label", sa.String(length=512), nullable=False),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["diagram_id"], ["diagrams.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    if "ix_diagram_metadata_links_diagram_id" not in _indexes("diagram_metadata_links"):
        op.create_index(
            "ix_diagram_metadata_links_diagram_id",
            "diagram_metadata_links",
            ["diagram_id"],
        )
    if "diagram_shares" not in tables:
        op.create_table(
            "diagram_shares",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("diagram_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["diagram_id"], ["diagrams.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("diagram_id", "user_id", name="uq_diagram_share_user"),
        )
    share_indexes = _indexes("diagram_shares")
    if "ix_diagram_shares_diagram_id" not in share_indexes:
        op.create_index(
            "ix_diagram_shares_diagram_id", "diagram_shares", ["diagram_id"]
        )
    if "ix_diagram_shares_user_id" not in share_indexes:
        op.create_index("ix_diagram_shares_user_id", "diagram_shares", ["user_id"])


def downgrade() -> None:
    if "diagram_shares" in _table_names():
        share_indexes = _indexes("diagram_shares")
        if "ix_diagram_shares_user_id" in share_indexes:
            op.drop_index("ix_diagram_shares_user_id", table_name="diagram_shares")
        if "ix_diagram_shares_diagram_id" in share_indexes:
            op.drop_index("ix_diagram_shares_diagram_id", table_name="diagram_shares")
        op.drop_table("diagram_shares")
    if "diagram_metadata_links" in _table_names():
        if "ix_diagram_metadata_links_diagram_id" in _indexes("diagram_metadata_links"):
            op.drop_index(
                "ix_diagram_metadata_links_diagram_id",
                table_name="diagram_metadata_links",
            )
        op.drop_table("diagram_metadata_links")
    if "diagram_versions" in _table_names():
        if "ix_diagram_versions_diagram_type" in _indexes("diagram_versions"):
            op.drop_index(
                "ix_diagram_versions_diagram_type", table_name="diagram_versions"
            )
        version_cols = _columns("diagram_versions")
        if "source_text" in version_cols:
            op.drop_column("diagram_versions", "source_text")
        if "diagram_type" in version_cols:
            op.drop_column("diagram_versions", "diagram_type")
    if "diagrams" in _table_names():
        diagram_indexes = _indexes("diagrams")
        if "ix_diagrams_diagram_type" in diagram_indexes:
            op.drop_index("ix_diagrams_diagram_type", table_name="diagrams")
        if "ix_diagrams_public_token" in diagram_indexes:
            op.drop_index("ix_diagrams_public_token", table_name="diagrams")
        diagram_cols = _columns("diagrams")
        if "diagram_type" in diagram_cols:
            op.drop_column("diagrams", "diagram_type")
        if "public_token" in diagram_cols:
            op.drop_column("diagrams", "public_token")
