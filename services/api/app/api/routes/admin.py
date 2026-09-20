from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.api.deps import get_request_user, require_admin
from app.api.payloads import (
    AdminUserCreatePayload,
    AdminUserUpdatePayload,
    GlobalDiagramChromePayload,
)
from app.db.models import (
    AuditLog,
    Diagram,
    DiagramLock,
    GlobalDiagramChrome,
    Group,
    GroupPermission,
    Permission,
    User,
    UserEmail,
    UserGroup,
    UserPermission,
)
from app.db.session import get_db
from app.security.auth import create_user
from app.security.permissions import PERM_AUDITTRAIL_READ, has_permission
from app.security.roles import attach_effective_role, normalize_role
from app.services.entity_changelog import list_entity_changelogs
from app.services.diagram_theme import normalise_diagram_theme

router = APIRouter()


def require_audit_access(
    user: User = Depends(get_request_user), db: Session = Depends(get_db)
) -> User:
    eff = attach_effective_role(db, user)
    if eff != "admin" and not has_permission(db, user, PERM_AUDITTRAIL_READ):
        raise HTTPException(status_code=403, detail="Audit access required")
    return user


def _group_to_dict(g: Group) -> dict:
    return {"id": g.id, "name": g.name, "description": g.description, "role": g.role}


def _permission_to_dict(p: Permission) -> dict:
    return {"id": p.id, "code": p.code, "description": p.description}


@router.get("/v1/admin/users")
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.username.asc()).all()
    return {
        "items": [
            {
                "id": u.id,
                "username": u.username,
                "email": getattr(u, "email", None),
                "role": u.role,
                "effective_role": attach_effective_role(db, u),
                "is_active": u.is_active,
                "created_at": u.created_at,
                "updated_at": u.updated_at,
                "last_login_at": u.last_login_at,
            }
            for u in users
        ]
    }


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
    return {
        "id": u.id,
        "username": u.username,
        "email": getattr(u, "email", None),
        "role": u.role,
        "effective_role": attach_effective_role(db, u),
        "is_active": u.is_active,
    }


@router.patch("/v1/admin/users/{user_id}")
def update_user_route(
    user_id: int,
    payload: AdminUserUpdatePayload,
    me: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    u = db.query(User).filter(User.id == user_id).one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.role is not None:
        nr = normalize_role(payload.role)
        if nr is None:
            raise HTTPException(status_code=400, detail="Invalid role")
        u.role = nr
    if payload.is_active is not None:
        u.is_active = bool(payload.is_active)
    if payload.email is not None:
        e = (payload.email or "").strip().lower() or None
        if e:
            existing_user = (
                db.query(User).filter(User.email == e, User.id != u.id).one_or_none()
            )
            existing_email = (
                db.query(UserEmail)
                .filter(UserEmail.email_lower == e, UserEmail.user_id != u.id)
                .one_or_none()
            )
            if existing_user or existing_email:
                raise HTTPException(status_code=400, detail="Email already in use")
            row = db.query(UserEmail).filter(UserEmail.email_lower == e).one_or_none()
            if row:
                row.is_primary = True
                row.is_verified = True
                db.add(row)
            else:
                db.add(
                    UserEmail(
                        user_id=u.id,
                        email=e,
                        email_lower=e,
                        source="admin",
                        is_primary=True,
                        is_verified=True,
                    )
                )
            db.query(UserEmail).filter(
                UserEmail.user_id == u.id, UserEmail.email_lower != e
            ).update({"is_primary": False}, synchronize_session=False)
        u.email = e
    db.add(u)
    db.commit()
    db.refresh(u)
    return {
        "id": u.id,
        "username": u.username,
        "email": getattr(u, "email", None),
        "role": u.role,
        "effective_role": attach_effective_role(db, u),
        "is_active": u.is_active,
    }


@router.delete("/v1/admin/users/{user_id}")
def delete_user_route(
    user_id: int, me: User = Depends(require_admin), db: Session = Depends(get_db)
):
    if int(user_id) == int(me.id):
        raise HTTPException(status_code=400, detail="You cannot delete your own user")
    u = db.query(User).filter(User.id == user_id).one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if (u.role or "").lower() == "admin" and bool(u.is_active):
        active_admins = (
            db.query(User.id)
            .filter(User.role == "admin", User.is_active.is_(True))
            .count()
        )
        if active_admins <= 1:
            raise HTTPException(
                status_code=409, detail="Cannot delete the last active admin user"
            )
    db.delete(u)
    db.commit()
    return {"status": "ok", "deleted_user_id": user_id}


@router.get("/v1/admin/users/{user_id}/access")
def get_user_access(
    user_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)
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
    user_id: int,
    body: dict,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    u = db.query(User).filter(User.id == user_id).one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        group_ids = sorted({int(x) for x in body.get("group_ids") or []})
        permission_ids = sorted({int(x) for x in body.get("permission_ids") or []})
    except Exception as e:
        raise HTTPException(
            status_code=400, detail="group_ids and permission_ids must be integer lists"
        ) from e
    if group_ids and db.query(Group.id).filter(Group.id.in_(group_ids)).count() != len(
        group_ids
    ):
        raise HTTPException(status_code=400, detail="one or more group_ids are invalid")
    if permission_ids and db.query(Permission.id).filter(
        Permission.id.in_(permission_ids)
    ).count() != len(permission_ids):
        raise HTTPException(
            status_code=400, detail="one or more permission_ids are invalid"
        )
    db.query(UserGroup).filter(UserGroup.user_id == user_id).delete()
    db.query(UserPermission).filter(UserPermission.user_id == user_id).delete()
    for gid in group_ids:
        db.add(UserGroup(user_id=user_id, group_id=gid))
    for pid in permission_ids:
        db.add(UserPermission(user_id=user_id, permission_id=pid))
    db.commit()
    return {
        "status": "ok",
        "user_id": user_id,
        "group_ids": group_ids,
        "permission_ids": permission_ids,
    }


@router.get("/v1/admin/groups")
def list_groups(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    items = db.query(Group).order_by(Group.name.asc()).all()
    out = []
    for g in items:
        out.append(
            {
                **_group_to_dict(g),
                "member_count": db.query(UserGroup)
                .filter(UserGroup.group_id == g.id)
                .count(),
                "permission_count": db.query(GroupPermission.id)
                .filter(GroupPermission.group_id == g.id)
                .count(),
            }
        )
    return {"items": out}


@router.post("/v1/admin/groups")
def create_group(
    body: dict, _: User = Depends(require_admin), db: Session = Depends(get_db)
):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    role = normalize_role(body.get("role")) if body.get("role") is not None else None
    if body.get("role") is not None and role is None:
        raise HTTPException(status_code=400, detail="invalid role")
    if db.query(Group).filter(Group.name == name).one_or_none():
        raise HTTPException(status_code=409, detail="group exists")
    g = Group(
        name=name,
        description=(body.get("description") or "").strip() or None,
        role=role,
    )
    db.add(g)
    db.commit()
    db.refresh(g)
    return _group_to_dict(g)


@router.patch("/v1/admin/groups/{group_id}")
def update_group(
    group_id: int,
    body: dict,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    g = db.query(Group).filter(Group.id == group_id).one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="group not found")
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
        g.role = (
            None
            if raw_role is None or str(raw_role).strip() == ""
            else normalize_role(str(raw_role))
        )
        if raw_role and g.role is None:
            raise HTTPException(status_code=400, detail="invalid role")
    db.add(g)
    db.commit()
    db.refresh(g)
    return _group_to_dict(g)


@router.delete("/v1/admin/groups/{group_id}")
def delete_group(
    group_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)
):
    g = db.query(Group).filter(Group.id == group_id).one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="group not found")
    db.delete(g)
    db.commit()
    return {"status": "ok", "deleted_group_id": group_id}


@router.get("/v1/admin/groups/{group_id}/permissions")
def get_group_permissions(
    group_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)
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
    group_id: int,
    body: dict,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    g = db.query(Group).filter(Group.id == group_id).one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="group not found")
    try:
        permission_ids = sorted({int(x) for x in body.get("permission_ids") or []})
    except Exception as e:
        raise HTTPException(
            status_code=400, detail="permission_ids must be integer list"
        ) from e
    if permission_ids and db.query(Permission.id).filter(
        Permission.id.in_(permission_ids)
    ).count() != len(permission_ids):
        raise HTTPException(
            status_code=400, detail="one or more permission_ids are invalid"
        )
    db.query(GroupPermission).filter(GroupPermission.group_id == group_id).delete()
    for pid in permission_ids:
        db.add(GroupPermission(group_id=group_id, permission_id=pid))
    db.commit()
    return {"status": "ok", "group_id": group_id, "permission_ids": permission_ids}


@router.get("/v1/admin/permissions")
def list_permissions(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    items = db.query(Permission).order_by(Permission.code.asc()).all()
    return {"items": [_permission_to_dict(p) for p in items]}


@router.post("/v1/admin/users/{user_id}/permissions/{permission_id}")
def add_user_permission(
    user_id: int,
    permission_id: int,
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


@router.get("/v1/admin/diagram-locks")
def list_diagram_locks(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = (
        db.query(DiagramLock, Diagram, User)
        .join(Diagram, Diagram.id == DiagramLock.diagram_id)
        .outerjoin(User, User.id == DiagramLock.user_id)
        .order_by(desc(DiagramLock.locked_at))
        .all()
    )
    return {
        "items": [
            {
                "id": lock.id,
                "diagram_id": diagram.id,
                "diagram_uuid": str(diagram.uuid),
                "diagram_name": diagram.name,
                "locked_by": getattr(user, "username", None),
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
    diagram_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)
):
    diagram = db.query(Diagram).filter(Diagram.id == diagram_id).one_or_none()
    if not diagram:
        raise HTTPException(status_code=404, detail="Diagram not found")
    db.query(DiagramLock).filter(DiagramLock.diagram_id == diagram.id).delete()
    db.commit()
    return {"ok": True, "diagram_id": diagram.id}


@router.get("/v1/admin/diagram-chrome")
def get_global_diagram_chrome(
    _: User = Depends(require_admin), db: Session = Depends(get_db)
):
    row = (
        db.query(GlobalDiagramChrome).filter(GlobalDiagramChrome.id == 1).one_or_none()
    )
    return {
        "header_text": getattr(row, "header_text", None),
        "footer_text": getattr(row, "footer_text", None),
        "theme_settings": normalise_diagram_theme(getattr(row, "theme_settings", None)),
    }


@router.put("/v1/admin/diagram-chrome")
def set_global_diagram_chrome(
    payload: GlobalDiagramChromePayload,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = (
        db.query(GlobalDiagramChrome).filter(GlobalDiagramChrome.id == 1).one_or_none()
    )
    if not row:
        row = GlobalDiagramChrome(id=1)
    row.header_text = payload.header_text
    row.footer_text = payload.footer_text
    if payload.theme_settings is not None:
        row.theme_settings = normalise_diagram_theme(payload.theme_settings)
    elif not getattr(row, "theme_settings", None):
        row.theme_settings = normalise_diagram_theme(None)
    row.updated_by_user_id = user.id
    row.updated_at = datetime.utcnow()
    db.add(row)
    db.commit()
    return {
        "header_text": row.header_text,
        "footer_text": row.footer_text,
        "theme_settings": normalise_diagram_theme(row.theme_settings),
    }


@router.get("/v1/admin/audit")
def admin_audit_trail(
    limit: int = 50,
    offset: int = 0,
    username: str | None = None,
    path: str | None = None,
    method: str | None = None,
    status_min: int | None = None,
    status_max: int | None = None,
    _: User = Depends(require_audit_access),
    db: Session = Depends(get_db),
):
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    qry = db.query(AuditLog).filter(
        ~(AuditLog.path.ilike("%/v1/auth%") & AuditLog.path.ilike("%callback%"))
    )
    if username:
        qry = qry.filter(AuditLog.username.ilike(f"%{username.strip()}%"))
    if path:
        qry = qry.filter(AuditLog.path.ilike(f"%{path.strip()}%"))
    if method:
        m = method.strip().upper()
        if m:
            qry = qry.filter(AuditLog.method == m)
    if status_min is not None:
        try:
            qry = qry.filter(AuditLog.status_code >= int(status_min))
        except Exception:
            pass
    if status_max is not None:
        try:
            qry = qry.filter(AuditLog.status_code <= int(status_max))
        except Exception:
            pass
    total = qry.order_by(None).count()
    rows = qry.order_by(desc(AuditLog.ts)).limit(limit).offset(offset).all()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
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
        ],
    }


@router.get("/v1/admin/entity-changelog")
def admin_entity_changelog(
    limit: int = 50,
    offset: int = 0,
    entity_type: str | None = None,
    entity_id: int | None = None,
    username: str | None = None,
    q: str | None = None,
    _: User = Depends(require_audit_access),
    db: Session = Depends(get_db),
):
    if entity_type:
        entity_type = entity_type.strip().lower()
        if entity_type not in {
            "diagram",
            "diagram_version",
            "folder",
            "diagram_comment",
            "diagram_entity_link",
            "diagram_metadata_link",
            "diagram_share",
            "diagram_lock",
        }:
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
