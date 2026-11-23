"""MIDENA's permission catalogue.

Accounts hold myf's roles (admin, normal, inherit) and these permissions,
directly or through their groups; myf.security.permissions answers whether an
account holds one. An administrator holds every permission.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Permission

PERM_DIAGRAM_READ_PRIVATE = "diagram.read_private"
PERM_DIAGRAM_WRITE = "diagram.write"
PERM_DIAGRAM_COMMENT = "diagram.comment"
PERM_DIAGRAM_EXPORT = "diagram.export"
PERM_FOLDER_MANAGE = "folder.manage"
PERM_AUDITTRAIL_READ = "audittrail.read"


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
