from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from mosp.core.datetime_utils import utc_now_naive
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from app.db.models import Diagram, EntityChangelog, Folder, User

_CHANGE_FIELD_LABELS = {
    "name": "Name",
    "description": "Description",
    "folder_id": "Folder",
    "parent_id": "Parent folder",
    "visibility": "Visibility",
    "tags": "Tags",
    "current_version_number": "Current version",
    "header_text": "Header text",
    "footer_text": "Footer text",
    "bpmn_xml": "BPMN XML",
    "svg_xml": "SVG XML",
    "version_number": "Version number",
    "change_summary": "Change summary",
    "element_id": "Diagram element",
    "entity_type": "Linked entity type",
    "entity_ref": "Linked entity reference",
    "url": "URL",
    "label": "Label",
    "notes": "Notes",
    "role": "Share role",
    "user_id": "Shared user",
    "username": "Username",
    "email": "Email",
}

_ENTITY_LABELS = {
    "diagram": "Diagram",
    "diagram_version": "Diagram version",
    "folder": "Folder",
    "diagram_comment": "Diagram comment",
    "diagram_entity_link": "Diagram entity link",
    "diagram_metadata_link": "Diagram metadata link",
    "diagram_share": "Diagram share",
    "diagram_tag": "Diagram tag",
    "diagram_lock": "Diagram lock",
    "diagram_chrome": "Diagram header, footer and theme",
}
# The entity types the changelog records, and so the only ones a filter names.
CHANGELOG_ENTITY_TYPES = frozenset(_ENTITY_LABELS)


def _clean_scalar(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(k): _clean_scalar(v)
            for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(value, (list, tuple, set)):
        return [_clean_scalar(v) for v in value]
    return value


def _norm(value: Any) -> Any:
    value = _clean_scalar(value)
    if value == "":
        return None
    if isinstance(value, str) and len(value) > 500:
        return f"{value[:500]}…"
    return value


def _field_label(field: str) -> str:
    return _CHANGE_FIELD_LABELS.get(field, field.replace("_", " ").title())


def _truncate_db_text(value: Any, max_len: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def diff_states(
    before: dict[str, Any] | None, after: dict[str, Any] | None
) -> list[dict[str, Any]]:
    before = before or {}
    after = after or {}
    skip = {"id", "uuid", "created_at", "updated_at"}
    fields = sorted((set(before.keys()) | set(after.keys())) - skip)
    changes: list[dict[str, Any]] = []
    for field in fields:
        old = _norm(before.get(field))
        new = _norm(after.get(field))
        if old == new:
            continue
        changes.append(
            {"field": field, "label": _field_label(field), "before": old, "after": new}
        )
    return changes


def _entity_display(
    entity_type: str, state: dict[str, Any] | None
) -> tuple[str | None, str | None]:
    state = state or {}
    ref = state.get("uuid") or state.get("id") or state.get("element_id")
    title = (
        state.get("name")
        or state.get("display")
        or state.get("entity_ref")
        or state.get("body")
    )
    return (_truncate_db_text(ref, 160), _truncate_db_text(title, 512))


def _summarise(entity_type: str, action: str, changes: list[dict[str, Any]]) -> str:
    label = _ENTITY_LABELS.get(entity_type, entity_type.replace("_", " ").title())
    if action == "created":
        return f"{label} created"
    if action == "deleted":
        return f"{label} deleted"
    if not changes:
        return f"{label} saved with no semantic changes"
    names = [str(c.get("label") or c.get("field")) for c in changes[:4]]
    suffix = "" if len(changes) <= 4 else f" and {len(changes) - 4} more"
    return f"Updated {', '.join(names)}{suffix}"


def record_entity_changelog(
    db: Session,
    *,
    entity_type: str,
    entity_id: int,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    user: User | None = None,
    request_method: str | None = None,
    request_path: str | None = None,
) -> EntityChangelog | None:
    entity_type = str(entity_type or "").strip().lower()
    if entity_type not in _ENTITY_LABELS:
        raise ValueError(f"Unsupported changelog entity_type: {entity_type}")

    clean_before = _clean_scalar(before) if before is not None else None
    clean_after = _clean_scalar(after) if after is not None else None
    if action == "updated":
        changes = diff_states(clean_before, clean_after)
        if not changes:
            return None
    elif action == "created":
        changes = diff_states(None, clean_after)
    elif action == "deleted":
        changes = diff_states(clean_before, None)
    else:
        changes = diff_states(clean_before, clean_after)
        if not changes:
            return None

    display_state = clean_after or clean_before or {}
    entity_ref, entity_title = _entity_display(entity_type, display_state)
    entry = EntityChangelog(
        entity_type=entity_type,
        entity_id=int(entity_id),
        entity_ref=entity_ref,
        entity_title=entity_title,
        action=action,
        summary=_summarise(entity_type, action, changes),
        before_state=clean_before,
        after_state=clean_after,
        changes=changes,
        changed_by_user_id=getattr(user, "id", None),
        changed_by_username=getattr(user, "username", None),
        request_method=request_method or None,
        request_path=request_path or None,
        changed_at=utc_now_naive(),
    )
    db.add(entry)
    db.flush()
    return entry


def folder_changelog_state(folder: Folder | None) -> dict[str, Any] | None:
    if folder is None:
        return None
    return {
        "id": int(folder.id),
        "uuid": str(folder.uuid),
        "name": folder.name,
        "parent_id": folder.parent_id,
        "description": folder.description,
        "sort_order": int(folder.sort_order or 0),
        "created_at": folder.created_at,
        "updated_at": folder.updated_at,
    }


def diagram_changelog_state(diagram: Diagram | None) -> dict[str, Any] | None:
    if diagram is None:
        return None
    current_version_number = None
    if diagram.current_version_id:
        for ver in diagram.versions or []:
            if int(ver.id) == int(diagram.current_version_id):
                current_version_number = int(ver.version_number)
                break
    return {
        "id": int(diagram.id),
        "uuid": str(diagram.uuid),
        "name": diagram.name,
        "description": diagram.description,
        "folder_id": diagram.folder_id,
        "visibility": getattr(diagram, "visibility", None) or "private",
        "tags": list(diagram.tags or []),
        "current_version_id": diagram.current_version_id,
        "current_version_number": current_version_number,
        "header_text": diagram.header_text,
        "footer_text": diagram.footer_text,
        "created_at": diagram.created_at,
        "updated_at": diagram.updated_at,
    }


def _serialise_changelog(row: EntityChangelog) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "entity_ref": row.entity_ref,
        "entity_title": row.entity_title,
        "action": row.action,
        "summary": row.summary,
        "before_state": row.before_state,
        "after_state": row.after_state,
        "changes": row.changes or [],
        "changed_by_user_id": row.changed_by_user_id,
        "changed_by_username": row.changed_by_username,
        "changed_at": row.changed_at.isoformat() if row.changed_at else None,
        "request_method": row.request_method,
        "request_path": row.request_path,
    }


def list_entity_changelogs(
    db: Session,
    *,
    entity_type: str | None = None,
    entity_id: int | None = None,
    username: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    qry = db.query(EntityChangelog)
    if entity_type:
        qry = qry.filter(EntityChangelog.entity_type == entity_type.strip().lower())
    if entity_id is not None:
        qry = qry.filter(EntityChangelog.entity_id == int(entity_id))
    if username:
        qry = qry.filter(
            EntityChangelog.changed_by_username.icontains(
                username.strip(), autoescape=True
            )
        )
    if q:
        needle = q.strip()
        qry = qry.filter(
            or_(
                EntityChangelog.entity_ref.icontains(needle, autoescape=True),
                EntityChangelog.entity_title.icontains(needle, autoescape=True),
                EntityChangelog.summary.icontains(needle, autoescape=True),
                EntityChangelog.changed_by_username.icontains(needle, autoescape=True),
            )
        )
    total = qry.order_by(None).count()
    rows = (
        qry.order_by(desc(EntityChangelog.changed_at)).limit(limit).offset(offset).all()
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [_serialise_changelog(row) for row in rows],
    }
