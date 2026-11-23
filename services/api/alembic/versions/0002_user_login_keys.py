"""Keep each account's login key

Revision ID: 0002_user_login_keys
Revises: 0001_initial
Create Date: 2026-11-23

Sign-in limits, recognised browsers and account creation treat usernames that
differ only in case, width, spacing or invisible characters as one name. The
login key, a digest of the name sign-in compares, lets the accounts a name
compares equal to be found by an indexed read, so working out a sign-in's
limits costs the same whatever the name and however many accounts there are.
Every existing account's key is computed from its username.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from mosp.security.names import login_key

# revision identifiers, used by Alembic.
revision: str = "0002_user_login_keys"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("login_key", sa.String(length=64), nullable=True))
    bind = op.get_bind()
    users = sa.table(
        "users", sa.column("id"), sa.column("username"), sa.column("login_key")
    )
    for account_id, username in bind.execute(sa.select(users.c.id, users.c.username)):
        bind.execute(
            users.update()
            .where(users.c.id == account_id)
            .values(login_key=login_key(username))
        )
    op.alter_column("users", "login_key", nullable=False)
    op.create_index(op.f("ix_users_login_key"), "users", ["login_key"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_login_key"), table_name="users")
    op.drop_column("users", "login_key")
