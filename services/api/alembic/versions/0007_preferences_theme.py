"""preferences and global diagram theme

Revision ID: 0007_preferences_theme
Revises: 0006_add_sequence_text
Create Date: 2026-07-01

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007_preferences_theme"
down_revision = "0006_add_sequence_text"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    from sqlalchemy import inspect

    return set(inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    from sqlalchemy import inspect

    if table_name not in _table_names():
        return set()
    return {col["name"] for col in inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    if "user_preferences" in _table_names():
        pref_cols = _columns("user_preferences")
        if "diagram_source_collapsed_by_default" not in pref_cols:
            op.add_column(
                "user_preferences",
                sa.Column(
                    "diagram_source_collapsed_by_default",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.true(),
                ),
            )
        if "diagram_sidebar_collapsed_by_default" not in pref_cols:
            op.add_column(
                "user_preferences",
                sa.Column(
                    "diagram_sidebar_collapsed_by_default",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.true(),
                ),
            )

    if "global_diagram_chrome" in _table_names():
        chrome_cols = _columns("global_diagram_chrome")
        if "theme_settings" not in chrome_cols:
            op.add_column(
                "global_diagram_chrome",
                sa.Column(
                    "theme_settings",
                    postgresql.JSONB(astext_type=sa.Text()),
                    nullable=False,
                    server_default=sa.text("'{}'::jsonb"),
                ),
            )


def downgrade() -> None:
    if "global_diagram_chrome" in _table_names():
        chrome_cols = _columns("global_diagram_chrome")
        if "theme_settings" in chrome_cols:
            op.drop_column("global_diagram_chrome", "theme_settings")

    if "user_preferences" in _table_names():
        pref_cols = _columns("user_preferences")
        if "diagram_sidebar_collapsed_by_default" in pref_cols:
            op.drop_column("user_preferences", "diagram_sidebar_collapsed_by_default")
        if "diagram_source_collapsed_by_default" in pref_cols:
            op.drop_column("user_preferences", "diagram_source_collapsed_by_default")
