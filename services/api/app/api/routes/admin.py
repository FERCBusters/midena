from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.api.deps import (
    DbId,
    OptionalDbId,
    PageLimit,
    PageOffset,
    get_request_user,
    require_admin,
)
from app.api.payloads import (
    AdminGroupCreatePayload,
    AdminGroupPermissionsUpdatePayload,
    AdminGroupUpdatePayload,
    AdminSetPasswordPayload,
    AdminUserAccessUpdatePayload,
    AdminUserCreatePayload,
    AdminUserUpdatePayload,
    GlobalDiagramChromePayload,
)
from app.core.email_address import single_mailbox
from app.db.models import (
    AuditLog,
    Diagram,
    DiagramLock,
    GlobalDiagramChrome,
    Group,
    GroupPermission,
    LoginDevice,
    Permission,
    User,
    UserGroup,
    UserPermission,
)
from app.db.session import get_db
from app.security import sign_in_throttle as throttle
from app.security.auth import create_user, get_password_hash, get_user_by_email
from app.security.client_addr import request_client_address
from app.security.permissions import PERM_AUDITTRAIL_READ, has_permission
from app.security.roles import (
    active_admin_count,
    attach_effective_role,
    lock_admin_changes,
    normalize_role,
)
from app.security.sessions import end_all_sessions
from app.services import security_notifications
from app.services.diagram_theme import normalise_diagram_theme
from app.services.entity_changelog import (
    CHANGELOG_ENTITY_TYPES,
    list_entity_changelogs,
    record_entity_changelog,
)
from app.tasks.notifications import kick_delivery

logger = logging.getLogger(__name__)

router = APIRouter()


def _ensure_an_admin_remains(db: Session, detail: str) -> None:
    """Refuse a pending change that leaves no active administrator, counting
    accounts that hold the role through a group as well as directly."""
    if active_admin_count(db) == 0:
        db.rollback()
        raise HTTPException(status_code=409, detail=detail)


def require_audit_access(
    user: User = Depends(get_request_user), db: Session = Depends(get_db)
) -> User:
    eff = attach_effective_role(db, user)
    if eff != "admin" and not has_permission(db, user, PERM_AUDITTRAIL_READ):
        raise HTTPException(status_code=403, detail="Audit access required")
    return user


def _group_to_dict(g: Group) -> dict:
    return {
        "id": g.id,
        "name": g.name,
        "description": g.description,
        "role": g.role,
    }


def _permission_to_dict(p: Permission) -> dict:
    return {
        "id": p.id,
        "code": p.code,
        "description": p.description,
    }


@router.get("/v1/admin/users")
def list_users(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    users = db.query(User).order_by(User.username.asc()).all()
    out = []
    for u in users:
        eff = attach_effective_role(db, u)
        out.append(
            {
                "id": u.id,
                "username": u.username,
                "email": getattr(u, "email", None),
                "role": u.role,
                "effective_role": eff,
                "is_active": u.is_active,
                "created_at": u.created_at,
                "updated_at": u.updated_at,
                "last_login_at": u.last_login_at,
            }
        )
    return {"items": out}


@router.post("/v1/admin/users")
def create_user_route(
    payload: AdminUserCreatePayload,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        u = create_user(
            db,
            username=payload.username,
            password=payload.password,
            email=payload.email,
            role=payload.role,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    eff = attach_effective_role(db, u)
    return {
        "id": u.id,
        "username": u.username,
        "email": getattr(u, "email", None),
        "role": u.role,
        "effective_role": eff,
        "is_active": u.is_active,
    }


@router.patch("/v1/admin/users/{user_id}")
def update_user_route(
    user_id: DbId,
    payload: AdminUserUpdatePayload,
    me: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    u = db.query(User).filter(User.id == user_id).one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    new_role = u.role
    if payload.role is not None:
        nr = normalize_role(payload.role)
        if nr is None:
            raise HTTPException(status_code=400, detail="Invalid role")
        new_role = nr

    new_is_active = (
        u.is_active if payload.is_active is None else bool(payload.is_active)
    )
    if u.id == me.id and payload.is_active is False:
        raise HTTPException(
            status_code=400, detail="You cannot deactivate your own account"
        )

    # Safety: don't allow demoting or deactivating the last active admin, the
    # same guard every path that can remove an administrator applies.
    lock_admin_changes(db)

    if payload.email is not None:
        email = None
        if payload.email.strip():
            email = single_mailbox(payload.email)
            if email is None:
                raise HTTPException(status_code=400, detail="Invalid email address")
            email = email.lower()
            other = get_user_by_email(db, email)
            if other is not None and other.id != u.id:
                raise HTTPException(status_code=400, detail="Email already in use")
        u.email = email

    if payload.role is not None:
        u.role = new_role
    if payload.is_active is False and u.is_active:
        # As in KEEN, deactivation ends the account's sessions for good: they
        # do not return if the account is activated again, and the enrolment
        # version moves on so pending ceremonies and address proofs end too.
        end_all_sessions(db, u)
    if payload.is_active is not None:
        u.is_active = new_is_active

    db.add(u)
    _ensure_an_admin_remains(
        db, "Cannot demote or deactivate the last active admin user"
    )
    db.commit()
    db.refresh(u)
    eff = attach_effective_role(db, u)
    return {
        "id": u.id,
        "username": u.username,
        "email": getattr(u, "email", None),
        "role": u.role,
        "effective_role": eff,
        "is_active": u.is_active,
    }


@router.post("/v1/admin/users/{user_id}/password")
def set_user_password_route(
    user_id: DbId,
    payload: AdminSetPasswordPayload,
    request: Request,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """An administrator's password reset, as KEEN's.

    The account's sessions and every browser's recognition end, its
    sign-in throttle starts afresh, and its owner is mailed a notice.
    """
    target = (
        db.query(User)
        .filter(User.id == user_id)
        .populate_existing()
        .with_for_update()
        .one_or_none()
    )
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        target.password_hash = get_password_hash(
            payload.new_password, username=target.username
        )
    except ValueError as problem:
        raise HTTPException(status_code=400, detail=str(problem)) from problem
    # Every session ends, whichever way it was signed in: a reset answers a
    # suspected takeover, and a session opened through a provider is as much
    # part of one as a password session.
    end_all_sessions(db, target)
    db.query(LoginDevice).filter(LoginDevice.user_id == target.id).delete(
        synchronize_session=False
    )
    throttle.clear_throttle(db, throttle.name_key(target.username))
    notice_queued = security_notifications.enqueue(
        db, target, "password-reset", ip=request_client_address(request)
    )
    db.add(target)
    db.commit()
    if notice_queued:
        kick_delivery()
    return {"ok": True}


@router.delete("/v1/admin/users/{user_id}")
def delete_user_route(
    user_id: DbId,
    me: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Hard-delete a user.

    Notes:
      - Cascades will remove sessions, shortcuts, preferences, group links, etc.
      - Diagrams, versions and folders keep their rows; their author columns
        are set to NULL.
    """
    if int(user_id) == int(me.id):
        raise HTTPException(status_code=400, detail="You cannot delete your own user")

    u = db.query(User).filter(User.id == user_id).one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    # Safety: don't allow deleting the last active admin.
    lock_admin_changes(db)
    db.delete(u)
    _ensure_an_admin_remains(db, "Cannot delete the last active admin user")
    db.commit()
    return {"status": "ok", "deleted_user_id": user_id}


@router.get("/v1/admin/users/{user_id}/access")
def get_user_access(
    user_id: DbId,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    u = db.query(User).filter(User.id == user_id).one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    group_ids = [
        gid
        for (gid,) in db.query(UserGroup.group_id)
        .filter(UserGroup.user_id == user_id)
        .all()
    ]
    permission_ids = [
        pid
        for (pid,) in db.query(UserPermission.permission_id)
        .filter(UserPermission.user_id == user_id)
        .all()
    ]

    groups = db.query(Group).order_by(Group.name.asc()).all()
    perms = db.query(Permission).order_by(Permission.code.asc()).all()

    return {
        "user_id": user_id,
        "group_ids": group_ids,
        "permission_ids": permission_ids,
        "available_groups": [_group_to_dict(g) for g in groups],
        "available_permissions": [_permission_to_dict(p) for p in perms],
    }


@router.put("/v1/admin/users/{user_id}/access")
def set_user_access(
    user_id: DbId,
    body: AdminUserAccessUpdatePayload,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    u = db.query(User).filter(User.id == user_id).one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    group_ids = sorted(set(body.group_ids))
    permission_ids = sorted(set(body.permission_ids))

    # Safety: stripping the last active admin's own access would lock the
    # installation out; refuse the change and ask for another admin.
    lock_admin_changes(db)
    if (
        (u.role or "").lower() == "admin"
        and bool(u.is_active)
        and not permission_ids
        and not group_ids
    ):
        if active_admin_count(db) <= 1:
            raise HTTPException(
                status_code=409,
                detail="Cannot strip access from the last active admin user",
            )

    if group_ids:
        existing_groups = db.query(Group.id).filter(Group.id.in_(group_ids)).count()
        if existing_groups != len(group_ids):
            raise HTTPException(
                status_code=400, detail="one or more group_ids are invalid"
            )

    if permission_ids:
        existing_perms = (
            db.query(Permission.id).filter(Permission.id.in_(permission_ids)).count()
        )
        if existing_perms != len(permission_ids):
            raise HTTPException(
                status_code=400, detail="one or more permission_ids are invalid"
            )

    db.query(UserGroup).filter(UserGroup.user_id == user_id).delete()
    db.query(UserPermission).filter(UserPermission.user_id == user_id).delete()

    for gid in group_ids:
        db.add(UserGroup(user_id=user_id, group_id=gid))
    for pid in permission_ids:
        db.add(UserPermission(user_id=user_id, permission_id=pid))

    # An account that is an administrator through a group stays one, or
    # another administrator exists.
    _ensure_an_admin_remains(db, "Cannot strip access from the last active admin user")
    db.commit()
    db.refresh(u)

    return {
        "status": "ok",
        "user_id": user_id,
        "group_ids": group_ids,
        "permission_ids": permission_ids,
    }


@router.get("/v1/admin/groups")
def list_groups(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    items = db.query(Group).order_by(Group.name.asc()).all()

    out = []
    for g in items:
        # Count rows rather than a specific column to avoid schema drift issues
        # (e.g. older databases where the join table may not have a populated id).
        members = db.query(UserGroup).filter(UserGroup.group_id == g.id).count()
        perms = (
            db.query(GroupPermission.id)
            .filter(GroupPermission.group_id == g.id)
            .count()
        )
        out.append(
            {
                **_group_to_dict(g),
                "member_count": members,
                "permission_count": perms,
            }
        )

    return {"items": out}


@router.post("/v1/admin/groups")
def create_group(
    body: AdminGroupCreatePayload,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    role = normalize_role(body.role) if body.role is not None else None
    if body.role is not None and role is None:
        raise HTTPException(status_code=400, detail="invalid role")

    existing = db.query(Group).filter(Group.name == name).one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="group exists")

    g = Group(
        name=name,
        description=(body.description or "").strip() or None,
        role=role,
    )
    db.add(g)
    db.commit()
    db.refresh(g)

    return _group_to_dict(g)


@router.patch("/v1/admin/groups/{group_id}")
def update_group(
    group_id: DbId,
    payload: AdminGroupUpdatePayload,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    g = db.query(Group).filter(Group.id == group_id).one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="group not found")

    body = payload.model_dump(exclude_unset=True)

    if "name" in body:
        name = (body.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name cannot be empty")
        existing = (
            db.query(Group)
            .filter(Group.name == name, Group.id != group_id)
            .one_or_none()
        )
        if existing:
            raise HTTPException(status_code=409, detail="group name already exists")
        g.name = name

    if "description" in body:
        g.description = (body.get("description") or "").strip() or None

    if "role" in body:
        raw_role = body.get("role")
        if raw_role is None or str(raw_role).strip() == "":
            g.role = None
        else:
            nr = normalize_role(str(raw_role))
            if nr is None:
                raise HTTPException(status_code=400, detail="invalid role")
            g.role = nr

    db.add(g)
    if "role" in body:
        lock_admin_changes(db)
        _ensure_an_admin_remains(db, "This group gives the last active admin its role")
    db.commit()
    db.refresh(g)
    return _group_to_dict(g)


@router.delete("/v1/admin/groups/{group_id}")
def delete_group(
    group_id: DbId,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Hard-delete a group.

    Cascades remove membership links and group permissions.
    """
    g = db.query(Group).filter(Group.id == group_id).one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="group not found")

    lock_admin_changes(db)
    db.delete(g)
    _ensure_an_admin_remains(db, "This group gives the last active admin its role")
    db.commit()
    return {"status": "ok", "deleted_group_id": group_id}


@router.get("/v1/admin/groups/{group_id}/permissions")
def get_group_permissions(
    group_id: DbId,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    g = db.query(Group).filter(Group.id == group_id).one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="group not found")

    permission_ids = [
        pid
        for (pid,) in db.query(GroupPermission.permission_id)
        .filter(GroupPermission.group_id == group_id)
        .all()
    ]
    perms = db.query(Permission).order_by(Permission.code.asc()).all()

    return {
        "group_id": group_id,
        "permission_ids": permission_ids,
        "available_permissions": [_permission_to_dict(p) for p in perms],
    }


@router.put("/v1/admin/groups/{group_id}/permissions")
def set_group_permissions(
    group_id: DbId,
    body: AdminGroupPermissionsUpdatePayload,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    g = db.query(Group).filter(Group.id == group_id).one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="group not found")

    permission_ids = sorted(set(body.permission_ids))

    if permission_ids:
        existing_perms = (
            db.query(Permission.id).filter(Permission.id.in_(permission_ids)).count()
        )
        if existing_perms != len(permission_ids):
            raise HTTPException(
                status_code=400, detail="one or more permission_ids are invalid"
            )

    db.query(GroupPermission).filter(GroupPermission.group_id == group_id).delete()
    for pid in permission_ids:
        db.add(GroupPermission(group_id=group_id, permission_id=pid))
    db.commit()

    return {"status": "ok", "group_id": group_id, "permission_ids": permission_ids}


@router.get("/v1/admin/permissions")
def list_permissions(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    items = db.query(Permission).order_by(Permission.code.asc()).all()
    return {"items": [_permission_to_dict(p) for p in items]}


@router.post("/v1/admin/users/{user_id}/permissions/{permission_id}")
def add_user_permission(
    user_id: DbId,
    permission_id: DbId,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    u = db.query(User).filter(User.id == user_id).one_or_none()
    p = db.query(Permission).filter(Permission.id == permission_id).one_or_none()
    if not u or not p:
        raise HTTPException(status_code=404, detail="user or permission not found")

    existing = (
        db.query(UserPermission)
        .filter(
            UserPermission.user_id == user_id,
            UserPermission.permission_id == permission_id,
        )
        .one_or_none()
    )
    if existing:
        return {"status": "ok", "already_linked": True}

    db.add(UserPermission(user_id=user_id, permission_id=permission_id))
    db.commit()
    return {"status": "ok"}


@router.get("/v1/admin/audit")
def admin_audit_trail(
    limit: PageLimit = 50,
    offset: PageOffset = 0,
    username: str | None = None,
    path: str | None = None,
    method: str | None = None,
    status_min: Annotated[int | None, Query(ge=100, le=599)] = None,
    status_max: Annotated[int | None, Query(ge=100, le=599)] = None,
    _: User = Depends(require_audit_access),
    db: Session = Depends(get_db),
):
    """List KEEN-style internal UI/API request audit trail entries."""

    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))

    # Sign-in callbacks are listed too: their query values are recorded as
    # REDACTED, so the row shows that a sign-in completed and nothing more.
    qry = db.query(AuditLog)
    if username:
        qry = qry.filter(AuditLog.username.icontains(username.strip(), autoescape=True))
    if path:
        qry = qry.filter(AuditLog.path.icontains(path.strip(), autoescape=True))
    if method:
        m = method.strip().upper()
        if m:
            qry = qry.filter(AuditLog.method == m)
    if status_min is not None:
        qry = qry.filter(AuditLog.status_code >= status_min)
    if status_max is not None:
        qry = qry.filter(AuditLog.status_code <= status_max)

    total = qry.order_by(None).count()
    rows = qry.order_by(desc(AuditLog.ts)).limit(limit).offset(offset).all()
    items = [
        {
            "id": str(row.id),
            "ts": row.ts.isoformat() if row.ts else None,
            "username": row.username,
            "method": row.method,
            "path": row.path,
            "query_string": row.query_string,
            "status_code": row.status_code,
            "duration_ms": row.duration_ms,
            "client_ip": row.client_ip,
            "user_agent": row.user_agent,
            "referer": row.referer,
        }
        for row in rows
    ]
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@router.get("/v1/admin/entity-changelog")
def admin_entity_changelog(
    limit: PageLimit = 50,
    offset: PageOffset = 0,
    entity_type: str | None = None,
    entity_id: OptionalDbId = None,
    username: str | None = None,
    q: str | None = None,
    _: User = Depends(require_audit_access),
    db: Session = Depends(get_db),
):
    """List semantic before/after changelogs for diagram workspace entities."""

    if entity_type:
        entity_type = entity_type.strip().lower()
        if entity_type not in CHANGELOG_ENTITY_TYPES:
            raise HTTPException(status_code=400, detail="Invalid entity_type")
    return list_entity_changelogs(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        username=username,
        q=q,
        limit=limit,
        offset=offset,
    )


def _pending_notification_count(db: Session) -> int:
    from app.db.models import Notification

    return db.query(Notification).filter(Notification.status == "pending").count()


@router.get("/v1/admin/features")
def admin_features(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Installation feature switches with their stored and deployment settings."""
    from app.core import features

    return features.state(db).admin()


@router.put("/v1/admin/features")
def update_admin_features(
    payload: dict[str, Any] = Body(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Save feature switches against the configuration version they started from."""
    from app.core import features

    return features.update(db, user, payload.get("version"), payload.get("changes"))


@router.get("/v1/admin/notifications")
def admin_notifications(
    limit: PageLimit = 50,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """The e-mail outbox: every queued mail's delivery state and failure."""
    from app.db.models import Notification

    limit = max(1, min(int(limit or 50), 200))
    rows = (
        db.query(Notification)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .all()
    )
    pending = db.query(Notification).filter(Notification.status == "pending").count()
    failed = db.query(Notification).filter(Notification.status == "failed").count()
    return {
        "pending": pending,
        "failed": failed,
        "notifications": [
            {
                "id": str(row.id),
                "user_id": row.user_id,
                "recipient": row.recipient,
                "subject": row.subject,
                "status": row.status,
                "attempts": row.attempts,
                "last_error": row.last_error,
                "created_at": row.created_at,
                "sent_at": row.sent_at,
            }
            for row in rows
        ],
    }


@router.get("/v1/admin/diagram-locks")
def list_diagram_locks(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = (
        db.query(DiagramLock, Diagram, User)
        .join(Diagram, Diagram.id == DiagramLock.diagram_id)
        .outerjoin(User, User.id == DiagramLock.user_id)
        .order_by(desc(DiagramLock.locked_at))
        .limit(500)
        .all()
    )
    return {
        "items": [
            {
                "id": lock.id,
                "diagram_id": diagram.id,
                "diagram_uuid": str(diagram.uuid),
                "diagram_name": diagram.name,
                "locked_by": user.username if user else None,
                "user_id": lock.user_id,
                "locked_at": lock.locked_at,
                "expires_at": lock.expires_at,
                "heartbeat_at": lock.heartbeat_at,
                "note": lock.note,
            }
            for lock, diagram, user in rows
        ]
    }


@router.post("/v1/admin/diagrams/{diagram_id}/unlock")
def admin_unlock_diagram(
    diagram_id: DbId,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    diagram = db.query(Diagram).filter(Diagram.id == diagram_id).one_or_none()
    if diagram is None:
        raise HTTPException(status_code=404, detail="Diagram not found")
    lock = db.query(DiagramLock).filter(DiagramLock.diagram_id == diagram.id).first()
    if lock is not None:
        record_entity_changelog(
            db,
            entity_type="diagram_lock",
            entity_id=diagram.id,
            action="deleted",
            before={"user_id": lock.user_id, "expires_at": lock.expires_at},
            after=None,
            user=user,
            request_method=request.method,
            request_path=request.url.path,
        )
        db.delete(lock)
    db.commit()
    return {"ok": True, "diagram_id": diagram.id}


def _chrome_dict(row: GlobalDiagramChrome | None) -> dict:
    return {
        "header_text": row.header_text if row else None,
        "footer_text": row.footer_text if row else None,
        "theme_settings": normalise_diagram_theme(row.theme_settings if row else None),
    }


@router.get("/v1/admin/diagram-chrome")
def get_global_diagram_chrome(
    _: User = Depends(require_admin), db: Session = Depends(get_db)
):
    return _chrome_dict(db.get(GlobalDiagramChrome, 1))


@router.put("/v1/admin/diagram-chrome")
def set_global_diagram_chrome(
    payload: GlobalDiagramChromePayload,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    # One row; concurrent saves take its lock in turn.
    row = (
        db.query(GlobalDiagramChrome)
        .filter(GlobalDiagramChrome.id == 1)
        .with_for_update()
        .one_or_none()
    )
    before = _chrome_dict(row)
    if row is None:
        row = GlobalDiagramChrome(id=1)
    row.header_text = payload.header_text
    row.footer_text = payload.footer_text
    if payload.theme_settings is not None:
        row.theme_settings = normalise_diagram_theme(payload.theme_settings)
    elif not row.theme_settings:
        row.theme_settings = normalise_diagram_theme(None)
    row.updated_by_user_id = user.id
    db.add(row)
    db.flush()
    after = _chrome_dict(row)
    record_entity_changelog(
        db,
        entity_type="diagram_chrome",
        entity_id=1,
        action="updated",
        before=before,
        after=after,
        user=user,
        request_method=request.method,
        request_path=request.url.path,
    )
    db.commit()
    return after
