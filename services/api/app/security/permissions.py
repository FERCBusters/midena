from __future__ import annotations

from sqlalchemy import and_, exists
from sqlalchemy.orm import Session

from app.db.models import GroupPermission, Permission, User, UserGroup, UserPermission
from app.security.roles import (
    ROLE_ADMIN,
    ROLE_ARCHITECT,
    ROLE_CONTRIBUTOR,
    ROLE_DIAGRAM_ADMIN,
    ROLE_ENGINEER,
    ROLE_MAINTAINER,
    ROLE_PRODUCT_OWNER,
    attach_effective_role,
)

# Permission codes used by the API
PERM_DIAGRAM_READ_PRIVATE = "diagram.read_private"
PERM_DIAGRAM_WRITE = "diagram.write"
PERM_DIAGRAM_COMMENT = "diagram.comment"
PERM_DIAGRAM_EXPORT = "diagram.export"
PERM_FOLDER_MANAGE = "folder.manage"
PERM_AUDITTRAIL_READ = "audittrail.read"

ROLE_DEFAULT_PERMISSIONS = {
    ROLE_ADMIN: {"*"},
    ROLE_DIAGRAM_ADMIN: {
        PERM_FOLDER_MANAGE,
        PERM_DIAGRAM_READ_PRIVATE,
        PERM_DIAGRAM_EXPORT,
    },
    ROLE_MAINTAINER: {
        PERM_DIAGRAM_READ_PRIVATE,
        PERM_DIAGRAM_WRITE,
        PERM_DIAGRAM_COMMENT,
        PERM_DIAGRAM_EXPORT,
        PERM_FOLDER_MANAGE,
    },
    ROLE_CONTRIBUTOR: {
        PERM_DIAGRAM_READ_PRIVATE,
        PERM_DIAGRAM_WRITE,
        PERM_DIAGRAM_COMMENT,
        PERM_DIAGRAM_EXPORT,
    },
    ROLE_ENGINEER: {
        PERM_DIAGRAM_READ_PRIVATE,
        PERM_DIAGRAM_COMMENT,
        PERM_DIAGRAM_EXPORT,
    },
    ROLE_PRODUCT_OWNER: {
        PERM_DIAGRAM_READ_PRIVATE,
        PERM_DIAGRAM_COMMENT,
        PERM_DIAGRAM_EXPORT,
    },
    ROLE_ARCHITECT: {
        PERM_DIAGRAM_READ_PRIVATE,
        PERM_DIAGRAM_WRITE,
        PERM_DIAGRAM_COMMENT,
        PERM_DIAGRAM_EXPORT,
        PERM_FOLDER_MANAGE,
    },
}


DEFAULT_PERMISSION_SEED = [
    {
        "code": PERM_DIAGRAM_READ_PRIVATE,
        "description": "Read every diagram marked private, not only one's own and those shared with one",
    },
    {
        "code": PERM_DIAGRAM_WRITE,
        "description": "Create diagrams, and edit one's own and those shared for editing",
    },
    {"code": PERM_DIAGRAM_COMMENT, "description": "Comment on readable diagrams"},
    {"code": PERM_DIAGRAM_EXPORT, "description": "Export readable diagrams"},
    {
        "code": PERM_FOLDER_MANAGE,
        "description": "Create, rename, move and delete folders",
    },
    {
        "code": PERM_AUDITTRAIL_READ,
        "description": "View request audit logs and semantic entity changelogs",
    },
]


def seed_default_permissions(db: Session) -> None:
    """Idempotently seed baseline permission rows used by this application."""
    existing_codes = {
        code
        for (code,) in db.query(Permission.code)
        .filter(Permission.code.in_([p["code"] for p in DEFAULT_PERMISSION_SEED]))
        .all()
    }
    changed = False
    for item in DEFAULT_PERMISSION_SEED:
        if item["code"] in existing_codes:
            continue
        db.add(Permission(code=item["code"], description=item.get("description")))
        changed = True
    if changed:
        db.commit()


def _has_direct_permission(db: Session, user_id: int, code: str) -> bool:
    return (
        db.query(
            exists().where(
                and_(
                    UserPermission.user_id == user_id,
                    UserPermission.permission_id == Permission.id,
                    Permission.code == code,
                )
            )
        ).scalar()
        is True
    )


def _has_group_permission(db: Session, user_id: int, code: str) -> bool:
    return (
        db.query(
            exists().where(
                and_(
                    UserGroup.user_id == user_id,
                    UserGroup.group_id == GroupPermission.group_id,
                    GroupPermission.permission_id == Permission.id,
                    Permission.code == code,
                )
            )
        ).scalar()
        is True
    )


def has_permission(db: Session, user: User, code: str) -> bool:
    """Return True if the user has the given permission code."""

    effective_role = attach_effective_role(db, user)
    if effective_role == ROLE_ADMIN:
        return True

    role_codes = ROLE_DEFAULT_PERMISSIONS.get(effective_role, set())
    if "*" in role_codes or code in role_codes:
        return True

    if _has_direct_permission(db, user.id, code):
        return True

    if _has_group_permission(db, user.id, code):
        return True

    return False
