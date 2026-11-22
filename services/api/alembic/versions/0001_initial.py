"""Initial MIDENA schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-22

Written out table by table: a revision never builds tables from the live
models, so every installation gets the same schema from the same revision.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=True),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("path", sa.String(length=256), nullable=False),
        sa.Column("query_string", sa.Text(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("client_ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=256), nullable=True),
        sa.Column("referer", sa.String(length=512), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_audit_logs_method"), "audit_logs", ["method"], unique=False
    )
    op.create_index(op.f("ix_audit_logs_path"), "audit_logs", ["path"], unique=False)
    op.create_index(
        op.f("ix_audit_logs_status_code"), "audit_logs", ["status_code"], unique=False
    )
    op.create_index(op.f("ix_audit_logs_ts"), "audit_logs", ["ts"], unique=False)
    op.create_index(
        op.f("ix_audit_logs_username"), "audit_logs", ["username"], unique=False
    )
    op.create_table(
        "diagram_tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("name_lower", sa.String(length=80), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_diagram_tags_name_lower"), "diagram_tags", ["name_lower"], unique=True
    )
    op.create_table(
        "groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_groups_name"), "groups", ["name"], unique=True)
    op.create_table(
        "login_throttles",
        sa.Column("name_key", sa.String(length=64), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("gate_until", sa.DateTime(), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("name_key"),
    )
    op.create_index(
        op.f("ix_login_throttles_last_failure_at"),
        "login_throttles",
        ["last_failure_at"],
        unique=False,
    )
    op.create_table(
        "oidc_login_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=255), nullable=False),
        sa.Column("nonce", sa.String(length=255), nullable=False),
        sa.Column("code_verifier", sa.String(length=255), nullable=False),
        sa.Column("next_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_oidc_login_states_state"), "oidc_login_states", ["state"], unique=True
    )
    op.create_table(
        "permissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_permissions_code"), "permissions", ["code"], unique=True)
    op.create_table(
        "rate_limit_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("identifier", sa.String(length=255), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_rate_limit_entries_identifier"),
        "rate_limit_entries",
        ["identifier"],
        unique=False,
    )
    op.create_index(
        op.f("ix_rate_limit_entries_timestamp"),
        "rate_limit_entries",
        ["timestamp"],
        unique=False,
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=160), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("mfa_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("mfa_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("mfa_totp_secret", sa.Text(), nullable=True),
        sa.Column(
            "mfa_totp_last_step", sa.Integer(), server_default="-1", nullable=False
        ),
        sa.Column(
            "mfa_code_failures", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("mfa_code_failures_since", sa.DateTime(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)
    op.create_table(
        "entity_changelogs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("entity_ref", sa.String(length=160), nullable=True),
        sa.Column("entity_title", sa.String(length=512), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "before_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "after_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("changed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("changed_by_username", sa.String(length=128), nullable=True),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.Column("request_method", sa.String(length=16), nullable=True),
        sa.Column("request_path", sa.String(length=256), nullable=True),
        sa.ForeignKeyConstraint(
            ["changed_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_entity_changelogs_action"),
        "entity_changelogs",
        ["action"],
        unique=False,
    )
    op.create_index(
        op.f("ix_entity_changelogs_changed_at"),
        "entity_changelogs",
        ["changed_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_entity_changelogs_changed_by_user_id"),
        "entity_changelogs",
        ["changed_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_entity_changelogs_changed_by_username"),
        "entity_changelogs",
        ["changed_by_username"],
        unique=False,
    )
    op.create_index(
        op.f("ix_entity_changelogs_entity_id"),
        "entity_changelogs",
        ["entity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_entity_changelogs_entity_ref"),
        "entity_changelogs",
        ["entity_ref"],
        unique=False,
    )
    op.create_index(
        op.f("ix_entity_changelogs_entity_type"),
        "entity_changelogs",
        ["entity_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_entity_changelogs_request_path"),
        "entity_changelogs",
        ["request_path"],
        unique=False,
    )
    op.create_table(
        "folders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uuid", sa.UUID(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["parent_id"], ["folders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("parent_id", "name", name="uq_folder_parent_name"),
    )
    op.create_index(
        op.f("ix_folders_parent_id"), "folders", ["parent_id"], unique=False
    )
    op.create_index(op.f("ix_folders_uuid"), "folders", ["uuid"], unique=True)
    op.create_table(
        "global_diagram_chrome",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("header_text", sa.Text(), nullable=True),
        sa.Column("footer_text", sa.Text(), nullable=True),
        sa.Column(
            "theme_settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "group_permissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("permission_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["permission_id"], ["permissions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "permission_id", name="uq_group_permission"),
    )
    op.create_table(
        "login_devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name_key", sa.String(length=64), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_login_devices_expires_at"),
        "login_devices",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_login_devices_user_id"), "login_devices", ["user_id"], unique=False
    )
    op.create_table(
        "managed_configuration_revisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version"),
    )
    op.create_index(
        op.f("ix_managed_configuration_revisions_name"),
        "managed_configuration_revisions",
        ["name"],
        unique=False,
    )
    op.create_table(
        "managed_configurations",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("name"),
    )
    op.create_table(
        "mfa_challenges",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("password_digest", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_mfa_challenges_expires_at"),
        "mfa_challenges",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mfa_challenges_user_id"), "mfa_challenges", ["user_id"], unique=False
    )
    op.create_table(
        "mfa_credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("credential_id", sa.Text(), nullable=False),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("sign_count", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("credential_id"),
    )
    op.create_index(
        op.f("ix_mfa_credentials_user_id"), "mfa_credentials", ["user_id"], unique=False
    )
    op.create_table(
        "mfa_recovery_codes",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "code_hash"),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("recipient", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="pending", nullable=False
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notifications_pending",
        "notifications",
        ["status", "next_attempt_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_user_id"), "notifications", ["user_id"], unique=False
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("auth_method", sa.String(length=20), nullable=False),
        sa.Column("mfa_verified", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("mfa_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("oidc_id_token", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_sessions_session_id"), "sessions", ["session_id"], unique=True
    )
    op.create_table(
        "sso_email_challenges",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=256), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("mfa_version", sa.Integer(), nullable=False),
        sa.Column("password_digest", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_sso_email_challenges_user_id"),
        "sso_email_challenges",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "user_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "group_id", name="uq_user_group"),
    )
    op.create_table(
        "user_identities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("issuer", sa.String(length=500), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("preferred_username", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("claims", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "issuer", "subject", name="uq_user_identity_issuer_subject"
        ),
    )
    op.create_index(
        op.f("ix_user_identities_user_id"), "user_identities", ["user_id"], unique=False
    )
    op.create_table(
        "user_login_ips",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("address", sa.String(length=45), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "address"),
    )
    op.create_table(
        "user_permissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("permission_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["permission_id"], ["permissions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "permission_id", name="uq_user_permission"),
    )
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("theme", sa.String(length=16), nullable=True),
        sa.Column(
            "node_colors", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("default_start_page", sa.String(length=255), nullable=True),
        sa.Column("sticky_enabled", sa.Boolean(), nullable=False),
        sa.Column("auto_apply_enabled", sa.Boolean(), nullable=False),
        sa.Column("diagram_source_collapsed_by_default", sa.Boolean(), nullable=False),
        sa.Column("diagram_sidebar_collapsed_by_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_table(
        "user_shortcuts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_user_shortcuts_user_name"),
    )
    op.create_index(
        op.f("ix_user_shortcuts_user_id"), "user_shortcuts", ["user_id"], unique=False
    )
    op.create_table(
        "user_sso_emails",
        sa.Column("email", sa.String(length=256), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("verified_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("email"),
    )
    op.create_index(
        op.f("ix_user_sso_emails_user_id"), "user_sso_emails", ["user_id"], unique=False
    )
    op.create_table(
        "diagrams",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uuid", sa.UUID(), nullable=False),
        sa.Column("public_token", sa.String(length=96), nullable=False),
        sa.Column("diagram_type", sa.String(length=32), nullable=False),
        sa.Column("visibility", sa.String(length=32), nullable=False),
        sa.Column("folder_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("slug", sa.String(length=240), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("current_version_id", sa.Integer(), nullable=True),
        sa.Column("header_text", sa.Text(), nullable=True),
        sa.Column("footer_text", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["folder_id"], ["folders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_diagrams_created_by_user_id"),
        "diagrams",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_diagrams_diagram_type"), "diagrams", ["diagram_type"], unique=False
    )
    op.create_index(
        op.f("ix_diagrams_folder_id"), "diagrams", ["folder_id"], unique=False
    )
    op.create_index(op.f("ix_diagrams_name"), "diagrams", ["name"], unique=False)
    op.create_index(
        op.f("ix_diagrams_public_token"), "diagrams", ["public_token"], unique=True
    )
    op.create_index(op.f("ix_diagrams_slug"), "diagrams", ["slug"], unique=False)
    op.create_index(op.f("ix_diagrams_uuid"), "diagrams", ["uuid"], unique=True)
    op.create_index(
        op.f("ix_diagrams_visibility"), "diagrams", ["visibility"], unique=False
    )
    op.create_table(
        "diagram_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("diagram_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("element_id", sa.String(length=255), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_resolved", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["diagram_id"], ["diagrams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_diagram_comments_diagram_id"),
        "diagram_comments",
        ["diagram_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_diagram_comments_element_id"),
        "diagram_comments",
        ["element_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_diagram_comments_user_id"),
        "diagram_comments",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "diagram_entity_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("diagram_id", sa.Integer(), nullable=False),
        sa.Column("element_id", sa.String(length=255), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_ref", sa.String(length=512), nullable=False),
        sa.Column("label", sa.String(length=512), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column(
            "metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["diagram_id"], ["diagrams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "diagram_id",
            "element_id",
            "entity_type",
            "entity_ref",
            name="uq_diagram_entity_link",
        ),
    )
    op.create_index(
        op.f("ix_diagram_entity_links_diagram_id"),
        "diagram_entity_links",
        ["diagram_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_diagram_entity_links_element_id"),
        "diagram_entity_links",
        ["element_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_diagram_entity_links_entity_ref"),
        "diagram_entity_links",
        ["entity_ref"],
        unique=False,
    )
    op.create_index(
        op.f("ix_diagram_entity_links_entity_type"),
        "diagram_entity_links",
        ["entity_type"],
        unique=False,
    )
    op.create_table(
        "diagram_locks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("diagram_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("locked_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["diagram_id"], ["diagrams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_diagram_locks_diagram_id"),
        "diagram_locks",
        ["diagram_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_diagram_locks_expires_at"),
        "diagram_locks",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_diagram_locks_user_id"), "diagram_locks", ["user_id"], unique=False
    )
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
        sa.ForeignKeyConstraint(["diagram_id"], ["diagrams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_diagram_metadata_links_diagram_id"),
        "diagram_metadata_links",
        ["diagram_id"],
        unique=False,
    )
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
        sa.ForeignKeyConstraint(["diagram_id"], ["diagrams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("diagram_id", "user_id", name="uq_diagram_share_user"),
    )
    op.create_index(
        op.f("ix_diagram_shares_diagram_id"),
        "diagram_shares",
        ["diagram_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_diagram_shares_user_id"), "diagram_shares", ["user_id"], unique=False
    )
    op.create_table(
        "diagram_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("diagram_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("diagram_type", sa.String(length=32), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("bpmn_xml", sa.Text(), nullable=False),
        sa.Column("sequence_text", sa.Text(), nullable=True),
        sa.Column("flowchart_text", sa.Text(), nullable=True),
        sa.Column("svg_xml", sa.Text(), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["diagram_id"], ["diagrams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "diagram_id", "version_number", name="uq_diagram_version_number"
        ),
    )
    op.create_index(
        op.f("ix_diagram_versions_created_at"),
        "diagram_versions",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_diagram_versions_diagram_id"),
        "diagram_versions",
        ["diagram_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_diagram_versions_diagram_type"),
        "diagram_versions",
        ["diagram_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_diagram_versions_diagram_type"), table_name="diagram_versions"
    )
    op.drop_index(op.f("ix_diagram_versions_diagram_id"), table_name="diagram_versions")
    op.drop_index(op.f("ix_diagram_versions_created_at"), table_name="diagram_versions")
    op.drop_table("diagram_versions")
    op.drop_index(op.f("ix_diagram_shares_user_id"), table_name="diagram_shares")
    op.drop_index(op.f("ix_diagram_shares_diagram_id"), table_name="diagram_shares")
    op.drop_table("diagram_shares")
    op.drop_index(
        op.f("ix_diagram_metadata_links_diagram_id"),
        table_name="diagram_metadata_links",
    )
    op.drop_table("diagram_metadata_links")
    op.drop_index(op.f("ix_diagram_locks_user_id"), table_name="diagram_locks")
    op.drop_index(op.f("ix_diagram_locks_expires_at"), table_name="diagram_locks")
    op.drop_index(op.f("ix_diagram_locks_diagram_id"), table_name="diagram_locks")
    op.drop_table("diagram_locks")
    op.drop_index(
        op.f("ix_diagram_entity_links_entity_type"), table_name="diagram_entity_links"
    )
    op.drop_index(
        op.f("ix_diagram_entity_links_entity_ref"), table_name="diagram_entity_links"
    )
    op.drop_index(
        op.f("ix_diagram_entity_links_element_id"), table_name="diagram_entity_links"
    )
    op.drop_index(
        op.f("ix_diagram_entity_links_diagram_id"), table_name="diagram_entity_links"
    )
    op.drop_table("diagram_entity_links")
    op.drop_index(op.f("ix_diagram_comments_user_id"), table_name="diagram_comments")
    op.drop_index(op.f("ix_diagram_comments_element_id"), table_name="diagram_comments")
    op.drop_index(op.f("ix_diagram_comments_diagram_id"), table_name="diagram_comments")
    op.drop_table("diagram_comments")
    op.drop_index(op.f("ix_diagrams_visibility"), table_name="diagrams")
    op.drop_index(op.f("ix_diagrams_uuid"), table_name="diagrams")
    op.drop_index(op.f("ix_diagrams_slug"), table_name="diagrams")
    op.drop_index(op.f("ix_diagrams_public_token"), table_name="diagrams")
    op.drop_index(op.f("ix_diagrams_name"), table_name="diagrams")
    op.drop_index(op.f("ix_diagrams_folder_id"), table_name="diagrams")
    op.drop_index(op.f("ix_diagrams_diagram_type"), table_name="diagrams")
    op.drop_index(op.f("ix_diagrams_created_by_user_id"), table_name="diagrams")
    op.drop_table("diagrams")
    op.drop_index(op.f("ix_user_sso_emails_user_id"), table_name="user_sso_emails")
    op.drop_table("user_sso_emails")
    op.drop_index(op.f("ix_user_shortcuts_user_id"), table_name="user_shortcuts")
    op.drop_table("user_shortcuts")
    op.drop_table("user_preferences")
    op.drop_table("user_permissions")
    op.drop_table("user_login_ips")
    op.drop_index(op.f("ix_user_identities_user_id"), table_name="user_identities")
    op.drop_table("user_identities")
    op.drop_table("user_groups")
    op.drop_index(
        op.f("ix_sso_email_challenges_user_id"), table_name="sso_email_challenges"
    )
    op.drop_table("sso_email_challenges")
    op.drop_index(op.f("ix_sessions_session_id"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_index("ix_notifications_pending", table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("mfa_recovery_codes")
    op.drop_index(op.f("ix_mfa_credentials_user_id"), table_name="mfa_credentials")
    op.drop_table("mfa_credentials")
    op.drop_index(op.f("ix_mfa_challenges_user_id"), table_name="mfa_challenges")
    op.drop_index(op.f("ix_mfa_challenges_expires_at"), table_name="mfa_challenges")
    op.drop_table("mfa_challenges")
    op.drop_table("managed_configurations")
    op.drop_index(
        op.f("ix_managed_configuration_revisions_name"),
        table_name="managed_configuration_revisions",
    )
    op.drop_table("managed_configuration_revisions")
    op.drop_index(op.f("ix_login_devices_user_id"), table_name="login_devices")
    op.drop_index(op.f("ix_login_devices_expires_at"), table_name="login_devices")
    op.drop_table("login_devices")
    op.drop_table("group_permissions")
    op.drop_table("global_diagram_chrome")
    op.drop_index(op.f("ix_folders_uuid"), table_name="folders")
    op.drop_index(op.f("ix_folders_parent_id"), table_name="folders")
    op.drop_table("folders")
    op.drop_index(
        op.f("ix_entity_changelogs_request_path"), table_name="entity_changelogs"
    )
    op.drop_index(
        op.f("ix_entity_changelogs_entity_type"), table_name="entity_changelogs"
    )
    op.drop_index(
        op.f("ix_entity_changelogs_entity_ref"), table_name="entity_changelogs"
    )
    op.drop_index(
        op.f("ix_entity_changelogs_entity_id"), table_name="entity_changelogs"
    )
    op.drop_index(
        op.f("ix_entity_changelogs_changed_by_username"), table_name="entity_changelogs"
    )
    op.drop_index(
        op.f("ix_entity_changelogs_changed_by_user_id"), table_name="entity_changelogs"
    )
    op.drop_index(
        op.f("ix_entity_changelogs_changed_at"), table_name="entity_changelogs"
    )
    op.drop_index(op.f("ix_entity_changelogs_action"), table_name="entity_changelogs")
    op.drop_table("entity_changelogs")
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
    op.drop_index(
        op.f("ix_rate_limit_entries_timestamp"), table_name="rate_limit_entries"
    )
    op.drop_index(
        op.f("ix_rate_limit_entries_identifier"), table_name="rate_limit_entries"
    )
    op.drop_table("rate_limit_entries")
    op.drop_index(op.f("ix_permissions_code"), table_name="permissions")
    op.drop_table("permissions")
    op.drop_index(op.f("ix_oidc_login_states_state"), table_name="oidc_login_states")
    op.drop_table("oidc_login_states")
    op.drop_index(
        op.f("ix_login_throttles_last_failure_at"), table_name="login_throttles"
    )
    op.drop_table("login_throttles")
    op.drop_index(op.f("ix_groups_name"), table_name="groups")
    op.drop_table("groups")
    op.drop_index(op.f("ix_diagram_tags_name_lower"), table_name="diagram_tags")
    op.drop_table("diagram_tags")
    op.drop_index(op.f("ix_audit_logs_username"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_ts"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_status_code"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_path"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_method"), table_name="audit_logs")
    op.drop_table("audit_logs")
