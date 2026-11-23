from __future__ import annotations

import uuid
from datetime import datetime

from myf.core.datetime_utils import utc_now_naive
from myf.db.accounts import (
    AuditLogMixin,
    GroupMixin,
    MfaChallengeMixin,
    MfaCredentialMixin,
    MfaRecoveryCodeMixin,
    OidcLoginStateMixin,
    PermissionMixin,
    SecurityNotificationMixin,
    SsoEmailChallengeMixin,
    UserIdentityMixin,
    UserLoginIPMixin,
    UserMixin,
    UserSsoEmailMixin,
    association_tables,
)
from sqlalchemy import (
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

from app.db.session import Base

# -----------------------------------------------------------------------------
# Accounts: myf's tables (myf.db.accounts) with MIDENA's additions
# -----------------------------------------------------------------------------

# Folder and Diagram have a column named uuid, which a class-level annotation
# would read instead of the module.
Uuid = uuid.UUID


user_groups, user_permissions, group_permissions = association_tables(Base.metadata)


class User(Base, UserMixin):
    preferences: Mapped[UserPreference | None] = relationship(
        "UserPreference", uselist=False, backref="user", cascade="all, delete-orphan"
    )
    shortcuts: Mapped[list["UserShortcut"]] = relationship(
        "UserShortcut", back_populates="user", cascade="all, delete-orphan"
    )


class Group(Base, GroupMixin):
    pass


class Permission(Base, PermissionMixin):
    pass


class UserIdentity(Base, UserIdentityMixin):
    pass


class OidcLoginState(Base, OidcLoginStateMixin):
    pass


class MfaCredential(Base, MfaCredentialMixin):
    pass


class MfaRecoveryCode(Base, MfaRecoveryCodeMixin):
    pass


class MfaChallenge(Base, MfaChallengeMixin):
    pass


class UserLoginIP(Base, UserLoginIPMixin):
    pass


class SecurityNotification(Base, SecurityNotificationMixin):
    pass


class UserSsoEmail(Base, UserSsoEmailMixin):
    pass


class SsoEmailChallenge(Base, SsoEmailChallengeMixin):
    pass


class AuditLog(Base, AuditLogMixin):
    """Requests recorded as the audit trail (myf.middleware). Semantic
    before/after changes are stored separately in EntityChangelog."""


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Uuid] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
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


class UserShortcut(Base):
    __tablename__ = "user_shortcuts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Uuid] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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


# -----------------------------------------------------------------------------
# MIDENA diagram domain
# -----------------------------------------------------------------------------


class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[Uuid] = mapped_column(
        UUID(as_uuid=True), unique=True, index=True, default=uuid.uuid4, nullable=False
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("folders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_user_id: Mapped[Uuid | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
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
    uuid: Mapped[Uuid] = mapped_column(
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
    created_by_user_id: Mapped[Uuid | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    updated_by_user_id: Mapped[Uuid | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
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
    created_by_user_id: Mapped[Uuid | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
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
    user_id: Mapped[Uuid | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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
    user_id: Mapped[Uuid | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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
    created_by_user_id: Mapped[Uuid | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
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
    created_by_user_id: Mapped[Uuid | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
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
    user_id: Mapped[Uuid] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="viewer")
    created_by_user_id: Mapped[Uuid | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
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
    updated_by_user_id: Mapped[Uuid | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False
    )


# -----------------------------------------------------------------------------
# Cross-cutting
# -----------------------------------------------------------------------------


class ManagedConfiguration(Base):
    """Versioned administrator setting, such as the installation features.

    Ported from KEEN: each change bumps the version, which saves check against
    so two administrators cannot silently overwrite one another.
    """

    __tablename__ = "managed_configurations"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    document: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[Uuid | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
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
    updated_by: Mapped[Uuid | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )

    __table_args__ = (UniqueConstraint("name", "version"),)


class Notification(Base):
    """Transactional e-mail outbox.

    Senders queue a row inside their own transaction; the worker delivers it
    with exponential backoff and records the outcome, so a broken SMTP
    configuration is visible instead of silently swallowed. A sent message's
    body is cleared (verification links are one-time secrets); bodies fail
    after eight attempts like the KEEN outbox this model ships for parity.
    """

    __tablename__ = "notifications"

    id: Mapped[Uuid] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[Uuid | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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

    id: Mapped[Uuid] = mapped_column(
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

    changed_by_user_id: Mapped[Uuid | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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
