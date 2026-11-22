from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.datetime_utils import utc_now_naive
from app.db.session import Base

# -----------------------------------------------------------------------------
# Auth / RBAC
# -----------------------------------------------------------------------------


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    # Theme palette id from the shared design system; empty means the
    # application default until the account sets one.
    theme: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Colour overrides keyed '<palette>:<node_key>'.
    node_colors: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    default_start_page: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # UI behaviour preferences (kept in DB so they roam across devices).
    sticky_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_apply_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    diagram_source_collapsed_by_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    diagram_sidebar_collapsed_by_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(
        String(160), unique=True, index=True, nullable=False
    )
    email: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # One of roles.py roles.
    role: Mapped[str] = mapped_column(String(50), default="viewer", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Local second factor: enabled means local sign-in needs the ceremony.
    # Every change to the enrolment bumps mfa_version, and a session whose
    # recorded version no longer matches is refused at resolution, so the
    # browser's other sessions end with the change. Wrong TOTP and recovery
    # codes are counted across sign-ins from mfa_code_failures_since; see
    # app/security/mfa.py.
    mfa_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    mfa_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    mfa_totp_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    mfa_totp_last_step: Mapped[int] = mapped_column(
        Integer, nullable=False, default=-1, server_default="-1"
    )
    mfa_code_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    mfa_code_failures_since: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False
    )

    preferences: Mapped[UserPreference | None] = relationship(
        "UserPreference", uselist=False, backref="user", cascade="all, delete-orphan"
    )

    shortcuts: Mapped[list["UserShortcut"]] = relationship(
        "UserShortcut", back_populates="user", cascade="all, delete-orphan"
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # How the session was created. Used to decide whether logout should trigger
    # RP-initiated logout (OIDC) or just clear the local session.
    auth_method: Mapped[str] = mapped_column(
        String(20), nullable=False, default="local"
    )

    # The second-factor state this session was issued with: a session proves
    # the factor only when its recorded enrolment version matches the
    # account's and the ceremony completed. See local_session_allowed in
    # app/security/mfa.py.
    mfa_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    mfa_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    # Optional: store the last OIDC id_token for this session so we can pass
    # id_token_hint to the provider's end_session endpoint (if configured).
    oidc_id_token: Mapped[str | None] = mapped_column(Text, nullable=True)


class MfaCredential(Base):
    """A registered WebAuthn security key or passkey."""

    __tablename__ = "mfa_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    credential_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    sign_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MfaRecoveryCode(Base):
    """One-time recovery codes, stored hashed."""

    __tablename__ = "mfa_recovery_codes"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)


class MfaChallenge(Base):
    """A pending second-factor ceremony, never part of the session namespace.

    The browser holds only the unhashed token; the row is looked up by the
    token's SHA-256 digest and carries the account state it was issued for.
    """

    __tablename__ = "mfa_challenges"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    password_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


# -----------------------------------------------------------------------------
# External identities (OIDC)
# -----------------------------------------------------------------------------


class UserIdentity(Base):
    __tablename__ = "user_identities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Provider type, e.g. "oidc"
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="oidc")
    issuer: Mapped[str] = mapped_column(String(500), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)

    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    preferred_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    claims: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_user_identity_issuer_subject"),
    )


class UserSsoEmail(Base):
    """An address whose mailbox the account has proved, for SSO linking.

    Ported from KEEN: an identity provider that reports one of these addresses
    as verified links its identity to the account at the first sign-in.
    """

    __tablename__ = "user_sso_emails"

    email: Mapped[str] = mapped_column(String(256), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    verified_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive
    )


class SsoEmailChallenge(Base):
    """The one outstanding mailbox proof an account has requested.

    It holds a digest of the e-mailed token and the account's password and
    second-factor state when it was requested, so a change to either ends it.
    """

    __tablename__ = "sso_email_challenges"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(256), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    mfa_version: Mapped[int] = mapped_column(Integer, nullable=False)
    password_digest: Mapped[str] = mapped_column(String(64), nullable=False)


class OidcLoginState(Base):
    __tablename__ = "oidc_login_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    nonce: Mapped[str] = mapped_column(String(255), nullable=False)
    code_verifier: Mapped[str] = mapped_column(String(255), nullable=False)

    next_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class UserShortcut(Base):
    __tablename__ = "user_shortcuts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="shortcuts")

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_user_shortcuts_user_name"),
    )


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(
        String(200), unique=True, index=True, nullable=False
    )

    # Optional group role (used in role inheritance).
    role: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False
    )

    # Optional human-friendly description shown in the admin UI.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class UserGroup(Base):
    __tablename__ = "user_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )

    __table_args__ = (UniqueConstraint("user_id", "group_id", name="uq_user_group"),)


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(
        String(120), unique=True, index=True, nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class UserPermission(Base):
    __tablename__ = "user_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    permission_id: Mapped[int] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "permission_id", name="uq_user_permission"),
    )


class GroupPermission(Base):
    __tablename__ = "group_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    permission_id: Mapped[int] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("group_id", "permission_id", name="uq_group_permission"),
    )


# -----------------------------------------------------------------------------
# MIDENA diagram domain
# -----------------------------------------------------------------------------


class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, index=True, default=uuid.uuid4, nullable=False
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("folders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False
    )

    parent: Mapped["Folder | None"] = relationship(
        "Folder", remote_side="Folder.id", back_populates="children"
    )
    children: Mapped[list["Folder"]] = relationship("Folder", back_populates="parent")

    __table_args__ = (
        UniqueConstraint("parent_id", "name", name="uq_folder_parent_name"),
    )


class DiagramTag(Base):
    __tablename__ = "diagram_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    name_lower: Mapped[str] = mapped_column(
        String(80), unique=True, index=True, nullable=False
    )
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#6f42c1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False
    )


class Diagram(Base):
    __tablename__ = "diagrams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, index=True, default=uuid.uuid4, nullable=False
    )
    public_token: Mapped[str] = mapped_column(
        String(96),
        unique=True,
        index=True,
        default=lambda: uuid.uuid4().hex + uuid.uuid4().hex,
        nullable=False,
    )
    diagram_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="bpmn", index=True
    )
    visibility: Mapped[str] = mapped_column(
        String(32), nullable=False, default="private", index=True
    )
    folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("folders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    slug: Mapped[str | None] = mapped_column(String(240), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    current_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    header_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    footer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False
    )

    folder: Mapped[Folder | None] = relationship("Folder")
    versions: Mapped[list["DiagramVersion"]] = relationship(
        "DiagramVersion", back_populates="diagram", cascade="all, delete-orphan"
    )
    comments: Mapped[list["DiagramComment"]] = relationship(
        "DiagramComment", back_populates="diagram", cascade="all, delete-orphan"
    )
    links: Mapped[list["DiagramEntityLink"]] = relationship(
        "DiagramEntityLink", back_populates="diagram", cascade="all, delete-orphan"
    )
    metadata_links: Mapped[list["DiagramMetadataLink"]] = relationship(
        "DiagramMetadataLink", back_populates="diagram", cascade="all, delete-orphan"
    )
    shares: Mapped[list["DiagramShare"]] = relationship(
        "DiagramShare", back_populates="diagram", cascade="all, delete-orphan"
    )
    locks: Mapped[list["DiagramLock"]] = relationship(
        "DiagramLock", back_populates="diagram", cascade="all, delete-orphan"
    )


class DiagramVersion(Base):
    __tablename__ = "diagram_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    diagram_id: Mapped[int] = mapped_column(
        ForeignKey("diagrams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    diagram_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="bpmn", index=True
    )
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    bpmn_xml: Mapped[str] = mapped_column(Text, nullable=False)
    sequence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    flowchart_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    svg_xml: Mapped[str | None] = mapped_column(Text, nullable=True)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False, index=True
    )

    diagram: Mapped[Diagram] = relationship("Diagram", back_populates="versions")

    __table_args__ = (
        UniqueConstraint(
            "diagram_id", "version_number", name="uq_diagram_version_number"
        ),
    )


class DiagramLock(Base):
    __tablename__ = "diagram_locks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    diagram_id: Mapped[int] = mapped_column(
        ForeignKey("diagrams.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    locked_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    diagram: Mapped[Diagram] = relationship("Diagram", back_populates="locks")
    user: Mapped[User | None] = relationship("User")


class DiagramComment(Base):
    __tablename__ = "diagram_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    diagram_id: Mapped[int] = mapped_column(
        ForeignKey("diagrams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    element_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False
    )

    diagram: Mapped[Diagram] = relationship("Diagram", back_populates="comments")
    user: Mapped[User | None] = relationship("User")


class DiagramEntityLink(Base):
    __tablename__ = "diagram_entity_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    diagram_id: Mapped[int] = mapped_column(
        ForeignKey("diagrams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    element_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_ref: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(String(512), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False
    )

    diagram: Mapped[Diagram] = relationship("Diagram", back_populates="links")

    __table_args__ = (
        UniqueConstraint(
            "diagram_id",
            "element_id",
            "entity_type",
            "entity_ref",
            name="uq_diagram_entity_link",
        ),
    )


class DiagramMetadataLink(Base):
    __tablename__ = "diagram_metadata_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    diagram_id: Mapped[int] = mapped_column(
        ForeignKey("diagrams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False
    )

    diagram: Mapped[Diagram] = relationship("Diagram", back_populates="metadata_links")
    created_by: Mapped[User | None] = relationship("User")


class DiagramShare(Base):
    __tablename__ = "diagram_shares"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    diagram_id: Mapped[int] = mapped_column(
        ForeignKey("diagrams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="viewer")
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False
    )

    diagram: Mapped[Diagram] = relationship("Diagram", back_populates="shares")
    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    created_by: Mapped[User | None] = relationship(
        "User", foreign_keys=[created_by_user_id]
    )

    __table_args__ = (
        UniqueConstraint("diagram_id", "user_id", name="uq_diagram_share_user"),
    )


class GlobalDiagramChrome(Base):
    __tablename__ = "global_diagram_chrome"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    header_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    footer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    theme_settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False
    )


# -----------------------------------------------------------------------------
# Cross-cutting
# -----------------------------------------------------------------------------


class RateLimitEntry(Base):
    __tablename__ = "rate_limit_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identifier: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False, index=True
    )


class LoginThrottle(Base):
    """Consecutive password failures from unrecognised browsers, per compared
    username digest (app/security/sign_in_throttle.py)."""

    __tablename__ = "login_throttles"

    name_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gate_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_failure_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False, index=True
    )


class LoginDevice(Base):
    """A browser that has proved an account's password: its hashed device
    cookie, bound to the username it signed in with."""

    __tablename__ = "login_devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name_key: Mapped[str] = mapped_column(String(64), nullable=False)
    failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class UserLoginIP(Base):
    """An address an account has completed a sign-in from.

    Ported from KEEN: a sign-in from an address not yet listed mails the
    account a security notice. Rows are kept until the account is deleted.
    """

    __tablename__ = "user_login_ips"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    address: Mapped[str] = mapped_column(String(45), primary_key=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )


class ManagedConfiguration(Base):
    """Versioned administrator setting, such as the installation features.

    Ported from KEEN: each change bumps the version, which saves check against
    so two administrators cannot silently overwrite one another.
    """

    __tablename__ = "managed_configurations"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    document: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False
    )


class ManagedConfigurationRevision(Base):
    """Every saved version of a managed configuration, kept as history."""

    __tablename__ = "managed_configuration_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    document: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )

    __table_args__ = (UniqueConstraint("name", "version"),)


class AuditLog(Base):
    """Record UI/API requests as an internal audit trail.

    This intentionally mirrors KEEN's request-level audit log shape. Semantic
    before/after business changes are stored separately in EntityChangelog.
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False, index=True
    )

    username: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    method: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    path: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    query_string: Mapped[str | None] = mapped_column(Text, nullable=True)

    status_code: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)
    referer: Mapped[str | None] = mapped_column(String(512), nullable=True)


class Notification(Base):
    """Transactional e-mail outbox.

    Senders queue a row inside their own transaction; the worker delivers it
    with exponential backoff and records the outcome, so a broken SMTP
    configuration is visible instead of silently swallowed. A sent message's
    body is cleared (verification links are one-time secrets); bodies fail
    after eight attempts like the KEEN outbox this model ships for parity.
    """

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="pending", nullable=False, server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0"
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )

    __table_args__ = (Index("ix_notifications_pending", "status", "next_attempt_at"),)


class EntityChangelog(Base):
    """Immutable semantic changelog for user-facing diagram workspace changes."""

    __tablename__ = "entity_changelogs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    entity_ref: Mapped[str | None] = mapped_column(
        String(160), nullable=True, index=True
    )
    entity_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    before_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    changes: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    changed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    changed_by_username: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False, index=True
    )
    request_method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    request_path: Mapped[str | None] = mapped_column(
        String(256), nullable=True, index=True
    )

    changed_by: Mapped[User | None] = relationship(
        "User", foreign_keys=[changed_by_user_id]
    )
