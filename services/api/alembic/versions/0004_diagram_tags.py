"""add diagram tag catalogue

Revision ID: 0004_midena_diagram_tags
Revises: 0003_midena_diagram_visibility
Create Date: 2026-06-19
"""

from __future__ import annotations

import hashlib

from alembic import op
import sqlalchemy as sa

revision = "0004_midena_diagram_tags"
down_revision = "0003_midena_diagram_visibility"
branch_labels = None
depends_on = None

TAG_COLOURS = [
    "#6f42c1",
    "#0d6efd",
    "#198754",
    "#dc3545",
    "#fd7e14",
    "#20c997",
    "#0dcaf0",
    "#d63384",
    "#6610f2",
    "#6c757d",
]


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table_name: str) -> set[str]:
    if table_name not in _table_names():
        return set()
    return {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _constraints(table_name: str) -> set[str]:
    if table_name not in _table_names():
        return set()
    insp = sa.inspect(op.get_bind())
    return {item["name"] for item in insp.get_unique_constraints(table_name)}


def _color_for_tag(name: str) -> str:
    digest = hashlib.sha1(name.lower().encode("utf-8")).hexdigest()
    return TAG_COLOURS[int(digest[:2], 16) % len(TAG_COLOURS)]


def _iter_existing_tags() -> dict[str, str]:
    bind = op.get_bind()
    if "diagrams" not in _table_names():
        return {}
    rows = bind.execute(
        sa.text("SELECT tags FROM diagrams WHERE tags IS NOT NULL")
    ).all()
    labels: dict[str, str] = {}
    for (tags,) in rows:
        if not isinstance(tags, list):
            continue
        for raw in tags:
            tag = str(raw or "").strip()
            if not tag:
                continue
            labels.setdefault(tag.lower(), tag[:80])
    return labels


def upgrade() -> None:
    tables = _table_names()
    if "diagram_tags" not in tables:
        op.create_table(
            "diagram_tags",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=80), nullable=False),
            sa.Column("name_lower", sa.String(length=80), nullable=False),
            sa.Column(
                "color",
                sa.String(length=7),
                nullable=False,
                server_default="#6f42c1",
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name_lower", name="uq_diagram_tags_name_lower"),
        )
    if "ix_diagram_tags_name_lower" not in _indexes("diagram_tags"):
        op.create_index(
            "ix_diagram_tags_name_lower",
            "diagram_tags",
            ["name_lower"],
            unique=True,
        )

    bind = op.get_bind()
    existing = {
        row[0]
        for row in bind.execute(sa.text("SELECT name_lower FROM diagram_tags")).all()
    }
    for key, label in _iter_existing_tags().items():
        if key in existing:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO diagram_tags (name, name_lower, color, created_at, updated_at) "
                "VALUES (:name, :key, :color, NOW(), NOW())"
            ),
            {"name": label, "key": key, "color": _color_for_tag(label)},
        )


def downgrade() -> None:
    if "diagram_tags" not in _table_names():
        return
    if "ix_diagram_tags_name_lower" in _indexes("diagram_tags"):
        op.drop_index("ix_diagram_tags_name_lower", table_name="diagram_tags")
    op.drop_table("diagram_tags")
