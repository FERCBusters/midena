from __future__ import annotations

from datetime import datetime, timedelta
import re
import secrets
import uuid
import xml.etree.ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import String, func, or_
from sqlalchemy.orm import Session

from app.api.deps import get_request_user, require_admin
from app.api.payloads import (
    DiagramCommentCreatePayload,
    DiagramCommentUpdatePayload,
    DiagramAIGeneratePayload,
    DiagramCreatePayload,
    DiagramEntityLinkPayload,
    DiagramLockPayload,
    DiagramTagCreatePayload,
    DiagramTagUpdatePayload,
    DiagramMetadataLinkPayload,
    DiagramSavePayload,
    DiagramSharePayload,
    DiagramUpdatePayload,
    FolderCreatePayload,
    FolderUpdatePayload,
    GoogleDriveExportPayload,
)
from app.db.models import (
    Diagram,
    DiagramComment,
    DiagramEntityLink,
    DiagramLock,
    DiagramMetadataLink,
    DiagramShare,
    DiagramTag,
    DiagramVersion,
    Folder,
    GlobalDiagramChrome,
    User,
    UserEmail,
)
from app.db.session import get_db
from app.security.permissions import (
    PERM_DIAGRAM_COMMENT,
    PERM_DIAGRAM_EXPORT,
    PERM_DIAGRAM_READ_PRIVATE,
    PERM_DIAGRAM_WRITE,
    PERM_FOLDER_MANAGE,
    has_permission,
)
from app.security.roles import attach_effective_role
from app.services.entity_changelog import (
    diagram_changelog_state,
    folder_changelog_state,
    list_entity_changelogs,
    record_entity_changelog,
)
from app.core.config import settings
from app.services.google_drive import GoogleDriveExportError, upload_base64_to_drive
from app.services.diagram_theme import normalise_diagram_theme
from app.services.diagram_ai import (
    DiagramAIError,
    ai_status as diagram_ai_status,
    generate_diagram_code,
)
from app.services.mailer import send_diagram_share_email
from app.security.rate_limit import check_rate_limit, record_rate_limit_attempt

router = APIRouter()

DEFAULT_BPMN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
  xmlns:di="http://www.omg.org/spec/DD/20100524/DI"
  id="Definitions_1" targetNamespace="https://midena.example.com/schema/bpmn">
  <bpmn:process id="Process_1" isExecutable="false">
    <bpmn:startEvent id="StartEvent_1" name="Start" />
  </bpmn:process>
  <bpmndi:BPMNDiagram id="BPMNDiagram_1">
    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="Process_1">
      <bpmndi:BPMNShape id="StartEvent_1_di" bpmnElement="StartEvent_1">
        <dc:Bounds x="152" y="102" width="36" height="36" />
      </bpmndi:BPMNShape>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>"""

DEFAULT_SEQUENCE_TEXT = """title MIDENA web sequence diagram
participant User
participant MIDENA
User->MIDENA: Open diagram
MIDENA-->User: Render read-only or editable view
"""

DEFAULT_FLOWCHART_TEXT = """flowchart LR
    A["Start"]
    B["Process"]
    C["End"]
    A-->B
    B-->C
"""

TAG_COLOURS = [
    "#6f42c1",
    "#0d6efd",
    "#198754",
    "#dc3545",
    "#fd7e14",
    "#20c997",
    "#0dcaf0",
    "#d63384",
    "#6610f2",
    "#6c757d",
]
TAG_COLOUR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _slugify(value: str) -> str:
    raw = str(value or "").strip().lower()
    raw = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    return raw[:200] or "item"


def _clean_tag_name(value: str | None) -> str:
    name = str(value or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Tag name must not be empty")
    if len(name) > 80:
        raise HTTPException(
            status_code=400, detail="Tag name must be at most 80 characters"
        )
    return name


def _tag_key(value: str | None) -> str:
    return _clean_tag_name(value).lower()


def _sql_like_escape(value: str) -> str:
    return (
        str(value or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )


def _tag_json_text_like_pattern(value: str) -> str:
    # Diagram.tags is stored as JSONB. Matching the quoted JSON string avoids
    # broad substring matches where a tag such as "prod" also matches
    # "production". Tags are normalised to lower case before filtering.
    return f'%"{_sql_like_escape(value.lower())}"%'


def _random_tag_colour() -> str:
    return secrets.choice(TAG_COLOURS)


def _normalise_tag_colour(value: str | None) -> str:
    if value is None or str(value).strip() == "":
        return _random_tag_colour()
    colour = str(value).strip()
    if not TAG_COLOUR_RE.match(colour):
        raise HTTPException(
            status_code=400, detail="Tag colour must be a #RRGGBB hex colour"
        )
    return colour.lower()


def _tag_to_dict(row: DiagramTag, count: int = 0) -> dict:
    return {
        "id": int(row.id),
        "name": row.name,
        "tag": row.name,
        "name_lower": row.name_lower,
        "color": row.color,
        "count": int(count or 0),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _diagram_tag_counts(rows: list[Diagram]) -> tuple[dict[str, int], dict[str, str]]:
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    for row in rows:
        for raw in row.tags or []:
            tag = str(raw or "").strip()
            if not tag:
                continue
            key = tag.lower()
            labels.setdefault(key, tag)
            counts[key] = counts.get(key, 0) + 1
    return counts, labels


def _ensure_diagram_tags(db: Session, tags: list[str] | None) -> None:
    for raw in tags or []:
        tag = _clean_tag_name(raw)
        key = tag.lower()
        exists = db.query(DiagramTag).filter(DiagramTag.name_lower == key).one_or_none()
        if exists:
            continue
        db.add(DiagramTag(name=tag, name_lower=key, color=_random_tag_colour()))
    db.flush()


def _sync_tag_catalog_from_diagrams(
    db: Session, rows: list[Diagram] | None = None
) -> None:
    rows = rows if rows is not None else db.query(Diagram).all()
    _, labels = _diagram_tag_counts(rows)
    if not labels:
        return
    existing = {
        row.name_lower
        for row in db.query(DiagramTag).filter(DiagramTag.name_lower.in_(labels)).all()
    }
    for key, label in labels.items():
        if key not in existing:
            db.add(DiagramTag(name=label, name_lower=key, color=_random_tag_colour()))
    db.flush()


def _replace_tag_on_diagrams(db: Session, old_name: str, new_name: str) -> int:
    old_key = old_name.lower()
    changed = 0
    for diagram in db.query(Diagram).all():
        tags = []
        seen: set[str] = set()
        did_change = False
        for raw in diagram.tags or []:
            tag = str(raw or "").strip()
            if not tag:
                continue
            if tag.lower() == old_key:
                tag = new_name
                did_change = True
            key = tag.lower()
            if key in seen:
                did_change = True
                continue
            seen.add(key)
            tags.append(tag)
        if did_change:
            diagram.tags = tags
            db.add(diagram)
            changed += 1
    if changed:
        db.flush()
    return changed


def _require_admin_role(db: Session, user: User) -> None:
    if _effective_role(db, user) != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


def _ensure_not_dangerous_xml(
    xml: str,
    *,
    expected_hint: str | None = None,
    allow_svg_doctype: bool = False,
) -> str:
    value = str(xml or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="XML must not be empty")
    lower = value.lower()
    if "<!entity" in lower or "<?xml-stylesheet" in lower:
        raise HTTPException(
            status_code=400,
            detail="ENTITY and xml-stylesheet declarations are not allowed",
        )
    if "<!doctype" in lower:
        if not allow_svg_doctype:
            raise HTTPException(
                status_code=400, detail="DOCTYPE declarations are not allowed"
            )
        doctype_match = re.search(r"<!doctype\s+svg\b[^>]*>", value, flags=re.I | re.S)
        if not doctype_match or "[" in doctype_match.group(0):
            raise HTTPException(
                status_code=400,
                detail="SVG DOCTYPE with an internal subset is not allowed",
            )
        value = value[: doctype_match.start()] + value[doctype_match.end() :]
    try:
        root = ET.fromstring(value)
    except ET.ParseError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid XML: {exc}") from exc
    if expected_hint and expected_hint not in str(root.tag).lower():
        raise HTTPException(status_code=400, detail=f"Expected {expected_hint} XML")
    return value


def _validate_bpmn_xml(xml: str) -> str:
    return _ensure_not_dangerous_xml(xml, expected_hint="definitions")


def _validate_svg_xml(svg: str | None) -> str | None:
    if svg is None:
        return None
    value = _ensure_not_dangerous_xml(svg, expected_hint="svg", allow_svg_doctype=True)
    try:
        root = ET.fromstring(value)
    except ET.ParseError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid SVG XML: {exc}") from exc

    forbidden_elements = {
        "script", "foreignobject", "iframe", "object", "embed", "audio", "video"
    }
    link_attributes = {"href", "{http://www.w3.org/1999/xlink}href"}
    for element in root.iter():
        tag = str(element.tag).rsplit("}", 1)[-1].lower()
        if tag in forbidden_elements:
            raise HTTPException(status_code=400, detail=f"Unsafe SVG element: {tag}")
        for raw_name, raw_value in element.attrib.items():
            name = str(raw_name).lower()
            attr_value = str(raw_value or "").strip()
            if name.startswith("on"):
                raise HTTPException(status_code=400, detail="SVG event handlers are not allowed")
            if name in link_attributes:
                normalized = re.sub(r"[\x00-\x20]+", "", attr_value).lower()
                if normalized and not normalized.startswith("#"):
                    raise HTTPException(status_code=400, detail="External SVG links are not allowed")
            if name == "style" and re.search(
                r"(?:url\s*\(|expression\s*\(|@import)", attr_value, flags=re.I
            ):
                raise HTTPException(status_code=400, detail="Unsafe SVG style is not allowed")
    return value


def _validate_rendered_svg_for_save(svg: str | None, diagram_label: str) -> str:
    if not str(svg or "").strip():
        raise HTTPException(
            status_code=400,
            detail=f"Validate the {diagram_label} before saving. Fix any syntax errors and try again.",
        )
    value = _validate_svg_xml(svg)
    if not value:
        raise HTTPException(
            status_code=400,
            detail=f"Validate the {diagram_label} before saving. Fix any syntax errors and try again.",
        )
    return value


def _normalize_diagram_type(value: str | None) -> str:
    raw = str(value or "bpmn").strip().lower()
    aliases = {
        "bpmn": "bpmn",
        "bpmn-js": "bpmn",
        "sequence": "sequence",
        "web-sequence": "sequence",
        "web_sequence": "sequence",
        "websequencediagram": "sequence",
        "websequencediagrams": "sequence",
        "wsd": "sequence",
        "flowchart": "flowchart",
        "flow": "flowchart",
        "mermaid-flowchart": "flowchart",
        "mermaid_flowchart": "flowchart",
    }
    if raw not in aliases:
        raise HTTPException(
            status_code=400, detail="diagram_type must be bpmn, sequence, or flowchart"
        )
    return aliases[raw]


def _normalize_visibility(value: str | None) -> str:
    if value is None:
        return "private"
    raw = str(value or "private").strip().lower().replace("-", "_")
    aliases = {
        "private": "private",
        "private_to_me": "private",
        "me": "private",
        "owner": "private",
        "internal": "internal",
        "private_internal": "internal",
        "authenticated": "internal",
        "public": "public",
    }
    if raw not in aliases:
        raise HTTPException(
            status_code=400, detail="visibility must be private, internal, or public"
        )
    return aliases[raw]


def _diagram_visibility(row: Diagram) -> str:
    value = getattr(row, "visibility", None)
    if value in {"private", "internal", "public"}:
        return value
    return "private"


def _is_public_diagram(row: Diagram) -> bool:
    return _diagram_visibility(row) == "public"


def _validate_sequence_text(text: str | None) -> str:
    value = str(text or "").strip()
    if not value:
        raise HTTPException(
            status_code=400, detail="Sequence diagram code must not be empty"
        )
    lower = value.lower()
    if (
        "<script" in lower
        or "javascript:" in lower
        or "<?xml" in lower
        or "<!doctype" in lower
    ):
        raise HTTPException(
            status_code=400, detail="Sequence diagram code contains unsafe markup"
        )
    if re.search(r"<[a-zA-Z/!][^>]*>", value):
        raise HTTPException(
            status_code=400,
            detail="HTML markup is not allowed in sequence diagram code",
        )
    return value


def _validate_flowchart_text(text: str | None) -> str:
    value = str(text or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="Flowchart code must not be empty")
    lower = value.lower()
    if (
        "<script" in lower
        or "javascript:" in lower
        or "<?xml" in lower
        or "<!doctype" in lower
    ):
        raise HTTPException(
            status_code=400, detail="Flowchart code contains unsafe markup"
        )
    return value


def _source_for_create(payload: DiagramCreatePayload) -> tuple[str, str, str | None]:
    diagram_type = _normalize_diagram_type(payload.diagram_type)
    if diagram_type == "sequence":
        source = payload.sequence_text or payload.source_text or DEFAULT_SEQUENCE_TEXT
        return (
            diagram_type,
            _validate_sequence_text(source),
            _validate_svg_xml(payload.svg_xml),
        )
    if diagram_type == "flowchart":
        source = payload.flowchart_text or payload.source_text or DEFAULT_FLOWCHART_TEXT
        return (
            diagram_type,
            _validate_flowchart_text(source),
            _validate_svg_xml(payload.svg_xml),
        )
    source = payload.bpmn_xml or payload.source_text or DEFAULT_BPMN_XML
    return diagram_type, _validate_bpmn_xml(source), _validate_svg_xml(payload.svg_xml)


def _source_for_save(
    payload: DiagramSavePayload, fallback_type: str
) -> tuple[str, str, str | None]:
    diagram_type = _normalize_diagram_type(payload.diagram_type or fallback_type)
    if diagram_type == "sequence":
        source = payload.sequence_text or payload.source_text or payload.bpmn_xml
        return (
            diagram_type,
            _validate_sequence_text(source),
            _validate_rendered_svg_for_save(payload.svg_xml, "sequence diagram"),
        )
    if diagram_type == "flowchart":
        source = (
            payload.flowchart_text
            or payload.source_text
            or payload.bpmn_xml
            or DEFAULT_FLOWCHART_TEXT
        )
        return (
            diagram_type,
            _validate_flowchart_text(source),
            _validate_rendered_svg_for_save(payload.svg_xml, "flowchart"),
        )
    source = payload.bpmn_xml or payload.source_text
    if not source:
        raise HTTPException(status_code=400, detail="BPMN XML must not be empty")
    return diagram_type, _validate_bpmn_xml(source), _validate_svg_xml(payload.svg_xml)


def _version_source(row: DiagramVersion | None, diagram_type: str | None) -> str:
    normalized_type = _normalize_diagram_type(
        diagram_type or getattr(row, "diagram_type", None) or "bpmn"
    )
    if normalized_type == "sequence":
        if not row:
            return DEFAULT_SEQUENCE_TEXT
        return (
            row.sequence_text
            or row.source_text
            or row.bpmn_xml
            or DEFAULT_SEQUENCE_TEXT
        )
    if normalized_type == "flowchart":
        if not row:
            return DEFAULT_FLOWCHART_TEXT
        return (
            row.flowchart_text
            or row.source_text
            or row.bpmn_xml
            or DEFAULT_FLOWCHART_TEXT
        )
    if not row:
        return DEFAULT_BPMN_XML
    return row.bpmn_xml or row.source_text or DEFAULT_BPMN_XML


def _version_text_columns(diagram_type: str, source_text: str) -> dict[str, str | None]:
    return {
        "sequence_text": source_text if diagram_type == "sequence" else None,
        "flowchart_text": source_text if diagram_type == "flowchart" else None,
    }


def _new_public_token() -> str:
    return secrets.token_urlsafe(36)


def _absolute_url(path: str, request: Request | None = None) -> str:
    base = (settings.public_base_url or "").strip().rstrip("/")
    if not base and request is not None:
        try:
            base = str(request.base_url).rstrip("/")
        except Exception:
            base = ""
    return f"{base}{path}" if base else path


def _effective_role(db: Session, user: User) -> str:
    return attach_effective_role(db, user)


def _can_read_private(db: Session, user: User) -> bool:
    return _effective_role(db, user) == "admin" or has_permission(
        db, user, PERM_DIAGRAM_READ_PRIVATE
    )


def _require_perm(db: Session, user: User, code: str, label: str) -> None:
    if _effective_role(db, user) == "admin":
        return
    if not has_permission(db, user, code):
        raise HTTPException(status_code=403, detail=f"{label} permission required")


def _diagram_query_for_user(db: Session, user: User | None):
    qry = db.query(Diagram)
    if user is None:
        return qry.filter(Diagram.visibility == "public")
    if _can_read_private(db, user):
        return qry
    shared_ids = db.query(DiagramShare.diagram_id).filter(
        DiagramShare.user_id == user.id
    )
    return qry.filter(
        or_(
            Diagram.visibility.in_(["internal", "public"]),
            Diagram.created_by_user_id == user.id,
            Diagram.id.in_(shared_ids),
        )
    )


def _share_for_user(
    db: Session, diagram: Diagram, user: User | None
) -> DiagramShare | None:
    if user is None:
        return None
    return (
        db.query(DiagramShare)
        .filter(DiagramShare.diagram_id == diagram.id, DiagramShare.user_id == user.id)
        .one_or_none()
    )


def _can_manage_sharing(db: Session, diagram: Diagram, user: User) -> bool:
    return _effective_role(db, user) == "admin" or diagram.created_by_user_id == user.id


def _can_delete_diagram(db: Session, diagram: Diagram, user: User) -> bool:
    return _effective_role(db, user) == "admin" or diagram.created_by_user_id == user.id


def _can_write_diagram(db: Session, diagram: Diagram, user: User) -> bool:
    if _effective_role(db, user) == "admin":
        return True
    if diagram.created_by_user_id == user.id:
        return has_permission(db, user, PERM_DIAGRAM_WRITE)
    share = _share_for_user(db, diagram, user)
    return bool(
        share
        and share.role == "editor"
        and has_permission(db, user, PERM_DIAGRAM_WRITE)
    )


def _get_public_diagram(
    db: Session, diagram_uuid: str, public_token: str | None
) -> Diagram:
    try:
        val = uuid.UUID(str(diagram_uuid))
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Diagram not found") from exc
    token = str(public_token or "").strip()
    if not token:
        raise HTTPException(
            status_code=404, detail="Diagram not found or public token missing"
        )
    diagram = (
        db.query(Diagram)
        .filter(
            Diagram.uuid == val,
            Diagram.visibility == "public",
            Diagram.public_token == token,
        )
        .one_or_none()
    )
    if not diagram:
        raise HTTPException(status_code=404, detail="Diagram not found")
    return diagram


def _get_diagram(
    db: Session,
    diagram_ref: str,
    user: User | None = None,
    *,
    require_write: bool = False,
) -> Diagram:
    qry = _diagram_query_for_user(db, user)
    try:
        val = uuid.UUID(str(diagram_ref))
        qry = qry.filter(Diagram.uuid == val)
    except Exception:
        qry = (
            qry.filter(Diagram.id == int(diagram_ref))
            if str(diagram_ref).isdigit()
            else qry.filter(Diagram.slug == diagram_ref)
        )
    diagram = qry.one_or_none()
    if not diagram:
        raise HTTPException(status_code=404, detail="Diagram not found")
    if require_write:
        assert user is not None
        if not _can_write_diagram(db, diagram, user):
            raise HTTPException(
                status_code=403, detail="Diagram write permission required"
            )
    return diagram


def _folder_is_descendant(
    db: Session, folder_id: int, maybe_descendant_id: int | None
) -> bool:
    """Return True if maybe_descendant_id is below folder_id in the folder tree."""
    current = maybe_descendant_id
    seen: set[int] = set()
    while current is not None and current not in seen:
        if int(current) == int(folder_id):
            return True
        seen.add(int(current))
        parent_id = (
            db.query(Folder.parent_id).filter(Folder.id == int(current)).scalar()
        )
        current = parent_id
    return False


def _get_folder(db: Session, folder_id: int | None) -> Folder | None:
    if folder_id is None:
        return None
    folder = db.query(Folder).filter(Folder.id == int(folder_id)).one_or_none()
    if not folder:
        raise HTTPException(status_code=400, detail="folder_id does not exist")
    return folder


def _current_version(db: Session, diagram: Diagram) -> DiagramVersion | None:
    if diagram.current_version_id:
        row = (
            db.query(DiagramVersion)
            .filter(DiagramVersion.id == diagram.current_version_id)
            .one_or_none()
        )
        if row:
            return row
    return (
        db.query(DiagramVersion)
        .filter(DiagramVersion.diagram_id == diagram.id)
        .order_by(DiagramVersion.version_number.desc())
        .first()
    )


def _active_lock(db: Session, diagram: Diagram) -> DiagramLock | None:
    lock = (
        db.query(DiagramLock).filter(DiagramLock.diagram_id == diagram.id).one_or_none()
    )
    if not lock:
        return None
    if lock.expires_at and lock.expires_at < datetime.utcnow():
        db.delete(lock)
        db.flush()
        return None
    return lock


def _ensure_lock_allows_write(db: Session, diagram: Diagram, user: User) -> None:
    lock = _active_lock(db, diagram)
    if lock and lock.user_id != user.id:
        raise HTTPException(status_code=423, detail="Diagram is locked by another user")


def _folder_to_dict(row: Folder) -> dict:
    return {
        "id": int(row.id),
        "uuid": str(row.uuid),
        "name": row.name,
        "slug": row.slug,
        "description": row.description,
        "parent_id": row.parent_id,
        "sort_order": int(row.sort_order or 0),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _diagram_summary(db: Session, row: Diagram) -> dict:
    ver = _current_version(db, row)
    lock = _active_lock(db, row)
    return {
        "id": int(row.id),
        "uuid": str(row.uuid),
        "diagram_type": getattr(row, "diagram_type", "bpmn") or "bpmn",
        "name": row.name,
        "slug": row.slug,
        "description": row.description,
        "folder_id": row.folder_id,
        "folder_name": getattr(row.folder, "name", None),
        "visibility": _diagram_visibility(row),
        "public_token": row.public_token if _is_public_diagram(row) else None,
        "tags": list(row.tags or []),
        "current_version_id": row.current_version_id,
        "current_version_number": int(ver.version_number) if ver else None,
        "created_by_user_id": row.created_by_user_id,
        "locked": bool(lock),
        "locked_by": (
            getattr(getattr(lock, "user", None), "username", None) if lock else None
        ),
        "lock_expires_at": getattr(lock, "expires_at", None),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _entity_link_to_dict(row: DiagramEntityLink) -> dict:
    return {
        "id": int(row.id),
        "element_id": row.element_id,
        "entity_type": row.entity_type,
        "entity_ref": row.entity_ref,
        "label": row.label or row.entity_ref,
        "url": row.url,
        "metadata": row.metadata_json or {},
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _entity_links_for_diagram(db: Session, diagram_id: int) -> list[dict]:
    rows = (
        db.query(DiagramEntityLink)
        .filter(DiagramEntityLink.diagram_id == diagram_id)
        .order_by(
            DiagramEntityLink.element_id.asc(), DiagramEntityLink.created_at.asc()
        )
        .all()
    )
    return [_entity_link_to_dict(row) for row in rows]


def _metadata_link_to_dict(row: DiagramMetadataLink) -> dict:
    return {
        "id": int(row.id),
        "label": row.label,
        "url": row.url,
        "notes": row.notes,
        "created_by_user_id": row.created_by_user_id,
        "created_by_username": getattr(
            getattr(row, "created_by", None), "username", None
        ),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _metadata_links_for_diagram(db: Session, diagram_id: int) -> list[dict]:
    rows = (
        db.query(DiagramMetadataLink)
        .filter(DiagramMetadataLink.diagram_id == diagram_id)
        .order_by(DiagramMetadataLink.created_at.asc(), DiagramMetadataLink.label.asc())
        .all()
    )
    return [_metadata_link_to_dict(row) for row in rows]


def _user_notification_email(db: Session, user: User) -> str | None:
    if (user.email or "").strip():
        return str(user.email).strip()
    row = (
        db.query(UserEmail)
        .filter(UserEmail.user_id == user.id)
        .order_by(UserEmail.is_primary.desc(), UserEmail.email.asc())
        .first()
    )
    return str(row.email).strip() if row and row.email else None


def _share_to_dict(row: DiagramShare) -> dict:
    email = getattr(row.user, "email", None)
    return {
        "id": int(row.id),
        "diagram_id": int(row.diagram_id),
        "user_id": int(row.user_id),
        "username": getattr(row.user, "username", None),
        "email": email,
        "role": row.role,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _resolve_share_user(db: Session, identifier: str) -> User:
    raw = str(identifier or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="User identifier is required")
    lowered = raw.lower()
    user = (
        db.query(User)
        .filter(or_(User.username.ilike(raw), User.email.ilike(lowered)))
        .one_or_none()
    )
    if not user:
        email_row = (
            db.query(UserEmail).filter(UserEmail.email_lower == lowered).one_or_none()
        )
        if email_row:
            user = db.query(User).filter(User.id == email_row.user_id).one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=404, detail="Active user not found")
    return user


def _diagram_detail(
    db: Session, row: Diagram, *, include_xml: bool = True, user: User | None = None
) -> dict:
    data = _diagram_summary(db, row)
    ver = _current_version(db, row)
    chrome = (
        db.query(GlobalDiagramChrome).filter(GlobalDiagramChrome.id == 1).one_or_none()
    )
    data.update(
        {
            "header_text": (
                row.header_text
                if row.header_text is not None
                else getattr(chrome, "header_text", None)
            ),
            "footer_text": (
                row.footer_text
                if row.footer_text is not None
                else getattr(chrome, "footer_text", None)
            ),
            "embed_url": (
                f"/embed/{row.uuid}/{row.public_token}"
                if _is_public_diagram(row)
                else None
            ),
            "public_view_url": (
                f"/public/diagrams/{row.uuid}/{row.public_token}.html"
                if _is_public_diagram(row)
                else None
            ),
            "entity_links": _entity_links_for_diagram(db, row.id),
            "metadata_links": _metadata_links_for_diagram(db, row.id),
            "diagram_theme": normalise_diagram_theme(
                getattr(chrome, "theme_settings", None)
            ),
        }
    )
    if user is not None:
        data["can_delete"] = _can_delete_diagram(db, row, user)
    if include_xml:
        current_type = (ver.diagram_type if ver else row.diagram_type) or "bpmn"
        current_source = _version_source(ver, current_type)
        data.update(
            {
                "bpmn_xml": (
                    current_source
                    if current_type != "bpmn"
                    else _version_source(ver, "bpmn")
                ),
                "source_text": current_source,
                "sequence_text": current_source if current_type == "sequence" else None,
                "flowchart_text": (
                    current_source if current_type == "flowchart" else None
                ),
                "svg_xml": ver.svg_xml if ver else None,
            }
        )
    return data


def _version_to_dict(row: DiagramVersion, *, include_xml: bool = False) -> dict:
    data = {
        "id": int(row.id),
        "diagram_id": int(row.diagram_id),
        "version_number": int(row.version_number),
        "diagram_type": getattr(row, "diagram_type", "bpmn") or "bpmn",
        "change_summary": row.change_summary,
        "created_by_user_id": row.created_by_user_id,
        "created_at": row.created_at,
    }
    if include_xml:
        current_type = row.diagram_type or "bpmn"
        current_source = _version_source(row, current_type)
        data["bpmn_xml"] = (
            current_source if current_type != "bpmn" else _version_source(row, "bpmn")
        )
        data["source_text"] = current_source
        data["sequence_text"] = current_source if current_type == "sequence" else None
        data["flowchart_text"] = current_source if current_type == "flowchart" else None
        data["svg_xml"] = row.svg_xml
    return data


@router.get("/v1/folders")
def list_folders(_: User = Depends(get_request_user), db: Session = Depends(get_db)):
    rows = (
        db.query(Folder)
        .order_by(
            Folder.parent_id.asc().nullsfirst(),
            Folder.sort_order.asc(),
            Folder.name.asc(),
        )
        .all()
    )
    return {"items": [_folder_to_dict(row) for row in rows]}


@router.post("/v1/folders")
def create_folder(
    payload: FolderCreatePayload,
    request: Request,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    _require_perm(db, user, PERM_FOLDER_MANAGE, "Folder management")
    _get_folder(db, payload.parent_id)
    row = Folder(
        name=payload.name.strip(),
        slug=_slugify(payload.name),
        parent_id=payload.parent_id,
        description=(payload.description or "").strip() or None,
        sort_order=int(payload.sort_order or 0),
        created_by_user_id=user.id,
    )
    db.add(row)
    db.flush()
    record_entity_changelog(
        db,
        entity_type="folder",
        entity_id=row.id,
        action="created",
        before=None,
        after=folder_changelog_state(row),
        user=user,
        request_method=request.method,
        request_path=request.url.path,
    )
    db.commit()
    db.refresh(row)
    return _folder_to_dict(row)


@router.patch("/v1/folders/{folder_id}")
def update_folder(
    folder_id: int,
    payload: FolderUpdatePayload,
    request: Request,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    _require_perm(db, user, PERM_FOLDER_MANAGE, "Folder management")
    row = db.query(Folder).filter(Folder.id == folder_id).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Folder not found")
    before = folder_changelog_state(row)
    if payload.name is not None:
        row.name = payload.name.strip()
        row.slug = _slugify(row.name)
    if "parent_id" in payload.model_fields_set:
        if payload.parent_id == row.id:
            raise HTTPException(
                status_code=400, detail="Folder cannot be parent of itself"
            )
        _get_folder(db, payload.parent_id)
        if _folder_is_descendant(db, row.id, payload.parent_id):
            raise HTTPException(
                status_code=400,
                detail="Folder cannot be moved under its own descendant",
            )
        row.parent_id = payload.parent_id
    if payload.description is not None:
        row.description = payload.description.strip() or None
    if payload.sort_order is not None:
        row.sort_order = int(payload.sort_order)
    db.add(row)
    db.flush()
    record_entity_changelog(
        db,
        entity_type="folder",
        entity_id=row.id,
        action="updated",
        before=before,
        after=folder_changelog_state(row),
        user=user,
        request_method=request.method,
        request_path=request.url.path,
    )
    db.commit()
    db.refresh(row)
    return _folder_to_dict(row)


@router.delete("/v1/folders/{folder_id}")
def delete_folder(
    folder_id: int,
    request: Request,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    _require_perm(db, user, PERM_FOLDER_MANAGE, "Folder management")
    row = db.query(Folder).filter(Folder.id == folder_id).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Folder not found")
    before = folder_changelog_state(row)
    db.query(Diagram).filter(Diagram.folder_id == row.id).update(
        {"folder_id": None}, synchronize_session=False
    )
    db.delete(row)
    record_entity_changelog(
        db,
        entity_type="folder",
        entity_id=folder_id,
        action="deleted",
        before=before,
        after=None,
        user=user,
        request_method=request.method,
        request_path=request.url.path,
    )
    db.commit()
    return {"ok": True}


@router.get("/v1/diagrams")
def list_diagrams(
    q: str | None = None,
    folder_id: int | None = None,
    visibility: str | None = None,
    diagram_type: str | None = None,
    tags: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    qry = _diagram_query_for_user(db, user)
    if folder_id is not None:
        qry = qry.filter(Diagram.folder_id == int(folder_id))
    if visibility:
        qry = qry.filter(Diagram.visibility == _normalize_visibility(visibility))
    if diagram_type:
        qry = qry.filter(Diagram.diagram_type == _normalize_diagram_type(diagram_type))
    selected_tags = [
        t.strip().lower() for t in re.split(r"[,\n]", tags or "") if t.strip()
    ]
    for tag in selected_tags:
        qry = qry.filter(
            func.lower(func.cast(Diagram.tags, String)).like(
                _tag_json_text_like_pattern(tag), escape="\\"
            )
        )
    if q:
        needle = f"%{q.strip()}%"
        qry = qry.filter(
            or_(
                Diagram.name.ilike(needle),
                Diagram.description.ilike(needle),
                func.cast(Diagram.tags, String).ilike(needle),
            )
        )
    total = qry.order_by(None).count()
    rows = (
        qry.order_by(Diagram.updated_at.desc(), Diagram.name.asc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [_diagram_summary(db, row) for row in rows],
    }


@router.get("/v1/diagram-tags")
def diagram_tag_cloud(
    user: User = Depends(get_request_user), db: Session = Depends(get_db)
):
    rows = _diagram_query_for_user(db, user).all()
    counts, labels = _diagram_tag_counts(rows)
    tag_rows = {row.name_lower: row for row in db.query(DiagramTag).all()}
    items = []
    for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        row = tag_rows.get(key)
        items.append(
            {
                "tag": row.name if row else labels[key],
                "name": row.name if row else labels[key],
                "count": count,
                "color": row.color if row else "#6f42c1",
            }
        )
    return {"items": items[:100]}


@router.get("/v1/tags")
def list_tags(user: User = Depends(get_request_user), db: Session = Depends(get_db)):
    visible_rows = _diagram_query_for_user(db, user).all()
    counts, _ = _diagram_tag_counts(visible_rows)
    rows = db.query(DiagramTag).order_by(DiagramTag.name_lower.asc()).all()
    return {"items": [_tag_to_dict(row, counts.get(row.name_lower, 0)) for row in rows]}


@router.post("/v1/tags")
def create_tag(
    payload: DiagramTagCreatePayload,
    request: Request,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    _require_admin_role(db, user)
    name = _clean_tag_name(payload.name)
    key = name.lower()
    if db.query(DiagramTag).filter(DiagramTag.name_lower == key).one_or_none():
        raise HTTPException(
            status_code=409, detail="A tag with that name already exists"
        )
    row = DiagramTag(
        name=name,
        name_lower=key,
        color=_normalise_tag_colour(payload.color),
    )
    db.add(row)
    db.flush()
    record_entity_changelog(
        db,
        entity_type="diagram_tag",
        entity_id=row.id,
        action="created",
        before=None,
        after=_tag_to_dict(row),
        user=user,
        request_method=request.method,
        request_path=request.url.path,
    )
    db.commit()
    db.refresh(row)
    return _tag_to_dict(row)


@router.patch("/v1/tags/{tag_id}")
def update_tag(
    tag_id: int,
    payload: DiagramTagUpdatePayload,
    request: Request,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    _require_admin_role(db, user)
    row = db.query(DiagramTag).filter(DiagramTag.id == int(tag_id)).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Tag not found")
    before = _tag_to_dict(row)
    if payload.name is not None:
        new_name = _clean_tag_name(payload.name)
        new_key = new_name.lower()
        existing = (
            db.query(DiagramTag).filter(DiagramTag.name_lower == new_key).one_or_none()
        )
        if existing and existing.id != row.id:
            raise HTTPException(
                status_code=409, detail="A tag with that name already exists"
            )
        if new_key != row.name_lower:
            _replace_tag_on_diagrams(db, row.name, new_name)
            row.name = new_name
            row.name_lower = new_key
    if "color" in payload.model_fields_set:
        row.color = _normalise_tag_colour(payload.color)
    db.add(row)
    db.flush()
    record_entity_changelog(
        db,
        entity_type="diagram_tag",
        entity_id=row.id,
        action="updated",
        before=before,
        after=_tag_to_dict(row),
        user=user,
        request_method=request.method,
        request_path=request.url.path,
    )
    db.commit()
    db.refresh(row)
    return _tag_to_dict(row)


@router.get("/v1/users/search")
def search_users(
    q: str = "",
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    _ = user
    needle = f"%{str(q or '').strip()}%"
    qry = db.query(User).filter(User.is_active.is_(True))
    if q:
        qry = qry.filter(or_(User.username.ilike(needle), User.email.ilike(needle)))
    rows = qry.order_by(User.username.asc()).limit(20).all()
    return {
        "items": [
            {"id": row.id, "username": row.username, "email": row.email} for row in rows
        ]
    }


@router.get("/v1/diagram-ai/status")
def get_diagram_ai_status(_: User = Depends(get_request_user)):
    return diagram_ai_status()


def _ai_rate_limit_id(user: User) -> str:
    return f"diagram_ai:user:{int(user.id)}"


def _validate_ai_generated_code(diagram_type: str, code: str) -> str:
    value = str(code or "").strip()
    if not value:
        raise HTTPException(
            status_code=502, detail="The AI provider returned empty diagram code"
        )
    if diagram_type == "flowchart":
        if not re.match(r"^\s*(?:flowchart|graph)\b", value, flags=re.I):
            # MIDENA can render a bare edge list by prefixing a directive client-side,
            # but saved AI output should be a complete, portable Mermaid document.
            value = f"flowchart LR\n{value}"
        return _validate_flowchart_text(value)
    if diagram_type == "sequence":
        looks_like_sequence = bool(
            re.search(
                r"(?im)^\s*(sequenceDiagram|participant|actor|title|note\s+(?:left|right|over)|loop|alt|opt|par|critical|break|rect|end)\b",
                value,
            )
            or re.search(r"[-<]+>{1,2}|-->{1,2}|-->>|->>|--x|-x", value)
        )
        if not looks_like_sequence:
            raise HTTPException(
                status_code=502,
                detail="The AI provider returned text that does not look like sequence diagram code",
            )
        return _validate_sequence_text(value)
    raise HTTPException(
        status_code=400,
        detail="AI generation is only available for sequence diagrams and flowcharts",
    )


async def _generate_ai_diagram_code(
    payload: DiagramAIGeneratePayload,
    user: User,
    db: Session,
    *,
    diagram: Diagram | None = None,
):
    _require_perm(db, user, PERM_DIAGRAM_WRITE, "Diagram write")
    diagram_type = _normalize_diagram_type(payload.diagram_type)
    if diagram_type == "bpmn":
        raise HTTPException(
            status_code=400,
            detail="AI generation is available for sequence diagrams and flowcharts",
        )
    if not diagram_ai_status().get("enabled"):
        raise HTTPException(
            status_code=503,
            detail="AI diagram generation is not configured. Set MIDENA_AI_API_KEY and MIDENA_AI_MODEL.",
        )
    if diagram is not None:
        _ensure_lock_allows_write(db, diagram, user)

    limit_id = _ai_rate_limit_id(user)
    allowed, info = check_rate_limit(
        db,
        limit_id,
        max_attempts=max(1, int(settings.ai_rate_limit_attempts or 30)),
        window_seconds=max(60, int(settings.ai_rate_limit_window_seconds or 3600)),
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"AI generation rate limit exceeded. Try again in {info.get('retry_after', 0)} seconds.",
        )
    record_rate_limit_attempt(db, limit_id)

    messages = [m.model_dump() for m in (payload.messages or [])]
    if payload.prompt and str(payload.prompt).strip():
        messages.append({"role": "user", "content": str(payload.prompt).strip()})
    if not messages:
        raise HTTPException(status_code=400, detail="Prompt is required")

    current_source = payload.current_source
    if not current_source and diagram is not None:
        current_type = _normalize_diagram_type(diagram.diagram_type or diagram_type)
        if current_type == diagram_type:
            current_source = _version_source(
                _current_version(db, diagram), current_type
            )

    try:
        code = await generate_diagram_code(
            diagram_type=diagram_type, messages=messages, current_source=current_source
        )
    except DiagramAIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    code = _validate_ai_generated_code(diagram_type, code)
    return {"diagram_type": diagram_type, "code": code, "status": diagram_ai_status()}


@router.post("/v1/diagram-ai/generate")
async def generate_new_diagram_ai_code(
    payload: DiagramAIGeneratePayload,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    return await _generate_ai_diagram_code(payload, user, db)


@router.post("/v1/diagrams/{diagram_ref}/ai/generate")
async def generate_existing_diagram_ai_code(
    diagram_ref: str,
    payload: DiagramAIGeneratePayload,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    diagram = _get_diagram(db, diagram_ref, user, require_write=True)
    return await _generate_ai_diagram_code(payload, user, db, diagram=diagram)


@router.post("/v1/diagrams")
def create_diagram(
    payload: DiagramCreatePayload,
    request: Request,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    _require_perm(db, user, PERM_DIAGRAM_WRITE, "Diagram write")
    _get_folder(db, payload.folder_id)
    diagram_type, source_text, svg_xml = _source_for_create(payload)
    visibility = _normalize_visibility(payload.visibility)
    _ensure_diagram_tags(db, list(payload.tags or []))
    diagram = Diagram(
        name=payload.name.strip(),
        slug=_slugify(payload.name),
        description=(payload.description or "").strip() or None,
        folder_id=payload.folder_id,
        diagram_type=diagram_type,
        visibility=visibility,
        public_token=_new_public_token(),
        tags=list(payload.tags or []),
        header_text=(payload.header_text or None),
        footer_text=(payload.footer_text or None),
        created_by_user_id=user.id,
        updated_by_user_id=user.id,
    )
    db.add(diagram)
    db.flush()
    ver = DiagramVersion(
        diagram_id=diagram.id,
        version_number=1,
        diagram_type=diagram_type,
        source_text=source_text,
        bpmn_xml=source_text,
        **_version_text_columns(diagram_type, source_text),
        svg_xml=svg_xml,
        change_summary="Initial version",
        created_by_user_id=user.id,
    )
    db.add(ver)
    db.flush()
    diagram.current_version_id = ver.id
    db.add(diagram)
    db.flush()
    record_entity_changelog(
        db,
        entity_type="diagram",
        entity_id=diagram.id,
        action="created",
        before=None,
        after=diagram_changelog_state(diagram),
        user=user,
        request_method=request.method,
        request_path=request.url.path,
    )
    record_entity_changelog(
        db,
        entity_type="diagram_version",
        entity_id=ver.id,
        action="created",
        before=None,
        after=_version_to_dict(ver),
        user=user,
        request_method=request.method,
        request_path=request.url.path,
    )
    db.commit()
    db.refresh(diagram)
    return _diagram_detail(db, diagram, user=user)


@router.post("/v1/diagrams/{diagram_ref}/clone")
def clone_diagram(
    diagram_ref: str,
    request: Request,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    _require_perm(db, user, PERM_DIAGRAM_WRITE, "Diagram write")
    source = _get_diagram(db, diagram_ref, user)
    source_version = (
        db.query(DiagramVersion)
        .filter(DiagramVersion.diagram_id == source.id)
        .order_by(DiagramVersion.version_number.desc())
        .first()
    )
    if not source_version:
        raise HTTPException(status_code=400, detail="Diagram has no version to clone")
    _get_folder(db, source.folder_id)
    _ensure_diagram_tags(db, list(source.tags or []))

    clone = Diagram(
        name=f"{source.name} (copy)",
        slug=_slugify(f"{source.name} copy"),
        description=source.description,
        folder_id=source.folder_id,
        diagram_type=source_version.diagram_type or source.diagram_type or "bpmn",
        visibility=_diagram_visibility(source),
        public_token=_new_public_token(),
        tags=list(source.tags or []),
        header_text=source.header_text,
        footer_text=source.footer_text,
        created_by_user_id=user.id,
        updated_by_user_id=user.id,
    )
    db.add(clone)
    db.flush()

    clone_version_type = source_version.diagram_type or source.diagram_type or "bpmn"
    clone_source_text = _version_source(source_version, clone_version_type)
    clone_version = DiagramVersion(
        diagram_id=clone.id,
        version_number=1,
        diagram_type=clone_version_type,
        source_text=clone_source_text,
        bpmn_xml=clone_source_text,
        **_version_text_columns(clone_version_type, clone_source_text),
        svg_xml=source_version.svg_xml,
        change_summary=f"Cloned from {source.name}",
        created_by_user_id=user.id,
    )
    db.add(clone_version)
    db.flush()
    clone.current_version_id = clone_version.id

    for link in source.links or []:
        db.add(
            DiagramEntityLink(
                diagram_id=clone.id,
                element_id=link.element_id,
                entity_type=link.entity_type,
                entity_ref=link.entity_ref,
                label=link.label,
                url=link.url,
                metadata_json=dict(link.metadata_json or {}),
                created_by_user_id=user.id,
            )
        )
    for metadata_link in source.metadata_links or []:
        db.add(
            DiagramMetadataLink(
                diagram_id=clone.id,
                label=metadata_link.label,
                url=metadata_link.url,
                notes=metadata_link.notes,
                created_by_user_id=user.id,
            )
        )
    for share in source.shares or []:
        if int(share.user_id) == int(user.id):
            continue
        db.add(
            DiagramShare(
                diagram_id=clone.id,
                user_id=share.user_id,
                role=share.role,
                created_by_user_id=user.id,
            )
        )

    db.add(clone)
    db.flush()
    record_entity_changelog(
        db,
        entity_type="diagram",
        entity_id=clone.id,
        action="created",
        before=None,
        after=diagram_changelog_state(clone),
        user=user,
        request_method=request.method,
        request_path=request.url.path,
    )
    record_entity_changelog(
        db,
        entity_type="diagram_version",
        entity_id=clone_version.id,
        action="created",
        before=None,
        after=_version_to_dict(clone_version),
        user=user,
        request_method=request.method,
        request_path=request.url.path,
    )
    db.commit()
    db.refresh(clone)
    return _diagram_detail(db, clone, user=user)


@router.get("/v1/diagrams/{diagram_ref}")
def get_diagram(
    diagram_ref: str,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    return _diagram_detail(db, _get_diagram(db, diagram_ref, user), user=user)


@router.patch("/v1/diagrams/{diagram_ref}")
def update_diagram(
    diagram_ref: str,
    payload: DiagramUpdatePayload,
    request: Request,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    diagram = _get_diagram(db, diagram_ref, user, require_write=True)
    _ensure_lock_allows_write(db, diagram, user)
    before = diagram_changelog_state(diagram)
    if payload.name is not None:
        diagram.name = payload.name.strip()
        diagram.slug = _slugify(diagram.name)
    if payload.description is not None:
        diagram.description = payload.description.strip() or None
    if "folder_id" in payload.model_fields_set:
        _get_folder(db, payload.folder_id)
        diagram.folder_id = payload.folder_id
    if "visibility" in payload.model_fields_set:
        diagram.visibility = _normalize_visibility(payload.visibility)
        if diagram.visibility == "public" and not diagram.public_token:
            diagram.public_token = _new_public_token()
    if payload.tags is not None:
        diagram.tags = list(payload.tags or [])
        _ensure_diagram_tags(db, diagram.tags)
    if "header_text" in payload.model_fields_set:
        diagram.header_text = payload.header_text
    if "footer_text" in payload.model_fields_set:
        diagram.footer_text = payload.footer_text
    diagram.updated_by_user_id = user.id
    db.add(diagram)
    db.flush()
    record_entity_changelog(
        db,
        entity_type="diagram",
        entity_id=diagram.id,
        action="updated",
        before=before,
        after=diagram_changelog_state(diagram),
        user=user,
        request_method=request.method,
        request_path=request.url.path,
    )
    db.commit()
    db.refresh(diagram)
    return _diagram_detail(db, diagram, user=user)


@router.delete("/v1/diagrams/{diagram_ref}")
def delete_diagram(
    diagram_ref: str,
    request: Request,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    diagram = _get_diagram(db, diagram_ref, user)
    if not _can_delete_diagram(db, diagram, user):
        raise HTTPException(
            status_code=403,
            detail="Only the diagram owner or an admin can delete this diagram",
        )
    before = diagram_changelog_state(diagram)
    did = int(diagram.id)
    db.delete(diagram)
    record_entity_changelog(
        db,
        entity_type="diagram",
        entity_id=did,
        action="deleted",
        before=before,
        after=None,
        user=user,
        request_method=request.method,
        request_path=request.url.path,
    )
    db.commit()
    return {"ok": True}


@router.get("/v1/diagrams/{diagram_ref}/versions")
def list_versions(
    diagram_ref: str,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    diagram = _get_diagram(db, diagram_ref, user)
    rows = (
        db.query(DiagramVersion)
        .filter(DiagramVersion.diagram_id == diagram.id)
        .order_by(DiagramVersion.version_number.desc())
        .all()
    )
    return {"items": [_version_to_dict(row) for row in rows]}


@router.get("/v1/diagram-versions/{version_id}")
def get_version(
    version_id: int,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    ver = (
        db.query(DiagramVersion)
        .filter(DiagramVersion.id == int(version_id))
        .one_or_none()
    )
    if not ver:
        raise HTTPException(status_code=404, detail="Version not found")
    _get_diagram(db, str(ver.diagram.uuid), user)
    return _version_to_dict(ver, include_xml=True)


@router.post("/v1/diagrams/{diagram_ref}/save")
def save_diagram(
    diagram_ref: str,
    payload: DiagramSavePayload,
    request: Request,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    diagram = _get_diagram(db, diagram_ref, user, require_write=True)
    _ensure_lock_allows_write(db, diagram, user)
    diagram_type, source_text, svg_xml = _source_for_save(
        payload, getattr(diagram, "diagram_type", "bpmn") or "bpmn"
    )
    before = diagram_changelog_state(diagram)
    max_version = (
        db.query(func.max(DiagramVersion.version_number))
        .filter(DiagramVersion.diagram_id == diagram.id)
        .scalar()
        or 0
    )
    ver = DiagramVersion(
        diagram_id=diagram.id,
        version_number=int(max_version) + 1,
        diagram_type=diagram_type,
        source_text=source_text,
        bpmn_xml=source_text,
        **_version_text_columns(diagram_type, source_text),
        svg_xml=svg_xml,
        change_summary=(payload.change_summary or "").strip() or None,
        created_by_user_id=user.id,
    )
    db.add(ver)
    db.flush()
    diagram.current_version_id = ver.id
    diagram.diagram_type = diagram_type
    diagram.updated_by_user_id = user.id
    diagram.updated_at = datetime.utcnow()
    db.add(diagram)
    db.flush()
    record_entity_changelog(
        db,
        entity_type="diagram_version",
        entity_id=ver.id,
        action="created",
        before=None,
        after=_version_to_dict(ver),
        user=user,
        request_method=request.method,
        request_path=request.url.path,
    )
    record_entity_changelog(
        db,
        entity_type="diagram",
        entity_id=diagram.id,
        action="updated",
        before=before,
        after=diagram_changelog_state(diagram),
        user=user,
        request_method=request.method,
        request_path=request.url.path,
    )
    db.commit()
    db.refresh(ver)
    return _version_to_dict(ver, include_xml=False)


@router.post("/v1/diagrams/{diagram_ref}/lock")
def lock_diagram(
    diagram_ref: str,
    payload: DiagramLockPayload,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    diagram = _get_diagram(db, diagram_ref, user, require_write=True)
    now = datetime.utcnow()
    ttl = int(payload.ttl_seconds or 900)
    lock = _active_lock(db, diagram)
    if lock and lock.user_id != user.id:
        raise HTTPException(status_code=423, detail="Diagram is locked by another user")
    if not lock:
        lock = DiagramLock(diagram_id=diagram.id, user_id=user.id)
    lock.locked_at = lock.locked_at or now
    lock.heartbeat_at = now
    lock.expires_at = now + timedelta(seconds=ttl)
    lock.note = (payload.note or "").strip() or None
    db.add(lock)
    db.commit()
    return {
        "ok": True,
        "diagram_id": diagram.id,
        "locked_by_user_id": user.id,
        "expires_at": lock.expires_at,
    }


@router.delete("/v1/diagrams/{diagram_ref}/lock")
def unlock_diagram(
    diagram_ref: str,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    diagram = _get_diagram(db, diagram_ref, user)
    lock = _active_lock(db, diagram)
    if not lock:
        return {"ok": True, "already_unlocked": True}
    if lock.user_id != user.id and _effective_role(db, user) != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only the locking user or an admin can unlock this diagram",
        )
    db.delete(lock)
    db.commit()
    return {"ok": True}


@router.get("/v1/diagrams/{diagram_ref}/comments")
def list_comments(
    diagram_ref: str,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    diagram = _get_diagram(db, diagram_ref, user)
    rows = (
        db.query(DiagramComment, User)
        .outerjoin(User, User.id == DiagramComment.user_id)
        .filter(DiagramComment.diagram_id == diagram.id)
        .order_by(DiagramComment.created_at.asc())
        .all()
    )
    return {
        "items": [
            {
                "id": c.id,
                "diagram_id": c.diagram_id,
                "element_id": c.element_id,
                "body": c.body,
                "is_resolved": c.is_resolved,
                "created_at": c.created_at,
                "updated_at": c.updated_at,
                "user_id": c.user_id,
                "username": getattr(u, "username", None),
            }
            for c, u in rows
        ]
    }


@router.post("/v1/diagrams/{diagram_ref}/comments")
def create_comment(
    diagram_ref: str,
    payload: DiagramCommentCreatePayload,
    request: Request,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    diagram = _get_diagram(db, diagram_ref, user)
    _require_perm(db, user, PERM_DIAGRAM_COMMENT, "Diagram comment")
    row = DiagramComment(
        diagram_id=diagram.id,
        user_id=user.id,
        element_id=(payload.element_id or "").strip() or None,
        body=payload.body.strip(),
    )
    db.add(row)
    db.flush()
    record_entity_changelog(
        db,
        entity_type="diagram_comment",
        entity_id=row.id,
        action="created",
        before=None,
        after={
            "id": row.id,
            "diagram_id": diagram.id,
            "element_id": row.element_id,
            "body": row.body,
        },
        user=user,
        request_method=request.method,
        request_path=request.url.path,
    )
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "diagram_id": row.diagram_id,
        "element_id": row.element_id,
        "body": row.body,
        "is_resolved": row.is_resolved,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "user_id": row.user_id,
        "username": user.username,
    }


@router.patch("/v1/comments/{comment_id}")
def update_comment(
    comment_id: int,
    payload: DiagramCommentUpdatePayload,
    request: Request,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(DiagramComment)
        .filter(DiagramComment.id == int(comment_id))
        .one_or_none()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Comment not found")
    _get_diagram(db, str(row.diagram.uuid), user)
    if row.user_id != user.id and _effective_role(db, user) != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only the comment author or an admin can edit this comment",
        )
    before = {
        "id": row.id,
        "diagram_id": row.diagram_id,
        "element_id": row.element_id,
        "body": row.body,
        "is_resolved": row.is_resolved,
    }
    if payload.body is not None:
        row.body = payload.body.strip()
    if payload.is_resolved is not None:
        row.is_resolved = bool(payload.is_resolved)
    db.add(row)
    db.flush()
    after = {
        "id": row.id,
        "diagram_id": row.diagram_id,
        "element_id": row.element_id,
        "body": row.body,
        "is_resolved": row.is_resolved,
    }
    record_entity_changelog(
        db,
        entity_type="diagram_comment",
        entity_id=row.id,
        action="updated",
        before=before,
        after=after,
        user=user,
        request_method=request.method,
        request_path=request.url.path,
    )
    db.commit()
    return after


@router.delete("/v1/comments/{comment_id}")
def delete_comment(
    comment_id: int,
    request: Request,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(DiagramComment)
        .filter(DiagramComment.id == int(comment_id))
        .one_or_none()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Comment not found")
    _get_diagram(db, str(row.diagram.uuid), user)
    if row.user_id != user.id and _effective_role(db, user) != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only the comment author or an admin can delete this comment",
        )
    before = {
        "id": row.id,
        "diagram_id": row.diagram_id,
        "element_id": row.element_id,
        "body": row.body,
        "is_resolved": row.is_resolved,
    }
    db.delete(row)
    record_entity_changelog(
        db,
        entity_type="diagram_comment",
        entity_id=int(comment_id),
        action="deleted",
        before=before,
        after=None,
        user=user,
        request_method=request.method,
        request_path=request.url.path,
    )
    db.commit()
    return {"ok": True}


@router.get("/v1/diagrams/{diagram_ref}/entity-links")
def list_entity_links(
    diagram_ref: str,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    diagram = _get_diagram(db, diagram_ref, user)
    return {"items": _entity_links_for_diagram(db, diagram.id)}


@router.post("/v1/diagrams/{diagram_ref}/entity-links")
def create_entity_link(
    diagram_ref: str,
    payload: DiagramEntityLinkPayload,
    request: Request,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    diagram = _get_diagram(db, diagram_ref, user, require_write=True)
    label = payload.label.strip()
    row = DiagramEntityLink(
        diagram_id=diagram.id,
        element_id=payload.element_id.strip(),
        entity_type=(payload.entity_type or "link").strip().lower() or "link",
        entity_ref=(payload.entity_ref or str(uuid.uuid4())).strip(),
        label=label,
        url=payload.url,
        metadata_json=payload.metadata or {},
        created_by_user_id=user.id,
    )
    db.add(row)
    db.flush()
    record_entity_changelog(
        db,
        entity_type="diagram_entity_link",
        entity_id=row.id,
        action="created",
        before=None,
        after={
            "id": row.id,
            "diagram_id": diagram.id,
            "element_id": row.element_id,
            "entity_type": row.entity_type,
            "entity_ref": row.entity_ref,
            "url": row.url,
        },
        user=user,
        request_method=request.method,
        request_path=request.url.path,
    )
    db.commit()
    db.refresh(row)
    return _entity_link_to_dict(row)


@router.delete("/v1/entity-links/{link_id}")
def delete_entity_link(
    link_id: int,
    request: Request,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(DiagramEntityLink)
        .filter(DiagramEntityLink.id == int(link_id))
        .one_or_none()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Entity link not found")
    _get_diagram(db, str(row.diagram.uuid), user, require_write=True)
    before = {
        "id": row.id,
        "diagram_id": row.diagram_id,
        "element_id": row.element_id,
        "entity_type": row.entity_type,
        "entity_ref": row.entity_ref,
        "url": row.url,
    }
    db.delete(row)
    record_entity_changelog(
        db,
        entity_type="diagram_entity_link",
        entity_id=int(link_id),
        action="deleted",
        before=before,
        after=None,
        user=user,
        request_method=request.method,
        request_path=request.url.path,
    )
    db.commit()
    return {"ok": True}


@router.get("/v1/diagrams/{diagram_ref}/metadata-links")
def list_metadata_links(
    diagram_ref: str,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    diagram = _get_diagram(db, diagram_ref, user)
    return {"items": _metadata_links_for_diagram(db, diagram.id)}


@router.post("/v1/diagrams/{diagram_ref}/metadata-links")
def create_metadata_link(
    diagram_ref: str,
    payload: DiagramMetadataLinkPayload,
    request: Request,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    diagram = _get_diagram(db, diagram_ref, user, require_write=True)
    row = DiagramMetadataLink(
        diagram_id=diagram.id,
        label=payload.label.strip(),
        url=payload.url,
        notes=(payload.notes or "").strip() or None,
        created_by_user_id=user.id,
    )
    db.add(row)
    db.flush()
    record_entity_changelog(
        db,
        entity_type="diagram_metadata_link",
        entity_id=row.id,
        action="created",
        before=None,
        after=_metadata_link_to_dict(row),
        user=user,
        request_method=request.method,
        request_path=request.url.path,
    )
    db.commit()
    db.refresh(row)
    return _metadata_link_to_dict(row)


@router.delete("/v1/metadata-links/{link_id}")
def delete_metadata_link(
    link_id: int,
    request: Request,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(DiagramMetadataLink)
        .filter(DiagramMetadataLink.id == int(link_id))
        .one_or_none()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Metadata link not found")
    _get_diagram(db, str(row.diagram.uuid), user, require_write=True)
    before = _metadata_link_to_dict(row)
    db.delete(row)
    record_entity_changelog(
        db,
        entity_type="diagram_metadata_link",
        entity_id=int(link_id),
        action="deleted",
        before=before,
        after=None,
        user=user,
        request_method=request.method,
        request_path=request.url.path,
    )
    db.commit()
    return {"ok": True}


@router.get("/v1/diagrams/{diagram_ref}/shares")
def list_diagram_shares(
    diagram_ref: str,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    diagram = _get_diagram(db, diagram_ref, user)
    rows = (
        db.query(DiagramShare)
        .filter(DiagramShare.diagram_id == diagram.id)
        .order_by(DiagramShare.updated_at.desc())
        .all()
    )
    return {
        "can_manage": _can_manage_sharing(db, diagram, user),
        "owner_user_id": diagram.created_by_user_id,
        "items": [_share_to_dict(row) for row in rows],
    }


@router.post("/v1/diagrams/{diagram_ref}/shares")
def share_diagram(
    diagram_ref: str,
    payload: DiagramSharePayload,
    request: Request,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    diagram = _get_diagram(db, diagram_ref, user)
    if not _can_manage_sharing(db, diagram, user):
        raise HTTPException(
            status_code=403,
            detail="Only the diagram author or an admin can manage sharing",
        )
    target = _resolve_share_user(db, payload.identifier)
    if target.id == diagram.created_by_user_id:
        raise HTTPException(
            status_code=400, detail="The author already owns this diagram"
        )
    row = (
        db.query(DiagramShare)
        .filter(
            DiagramShare.diagram_id == diagram.id, DiagramShare.user_id == target.id
        )
        .one_or_none()
    )
    if not row:
        row = DiagramShare(
            diagram_id=diagram.id,
            user_id=target.id,
            created_by_user_id=user.id,
        )
    row.role = payload.role
    db.add(row)
    db.flush()
    notify_email = _user_notification_email(db, target)
    if payload.notify and notify_email:
        url = _absolute_url(f"/diagram.html?id={diagram.uuid}", request)
        send_diagram_share_email(
            to_email=notify_email,
            diagram_name=diagram.name,
            shared_by=user.username,
            diagram_url=url,
            role=row.role,
        )
    record_entity_changelog(
        db,
        entity_type="diagram_share",
        entity_id=row.id,
        action="updated",
        before=None,
        after=_share_to_dict(row),
        user=user,
        request_method=request.method,
        request_path=request.url.path,
    )
    db.commit()
    db.refresh(row)
    return _share_to_dict(row)


@router.delete("/v1/diagram-shares/{share_id}")
def delete_diagram_share(
    share_id: int,
    request: Request,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    row = db.query(DiagramShare).filter(DiagramShare.id == int(share_id)).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Share not found")
    diagram = _get_diagram(db, str(row.diagram.uuid), user)
    if not _can_manage_sharing(db, diagram, user):
        raise HTTPException(
            status_code=403,
            detail="Only the diagram author or an admin can manage sharing",
        )
    before = _share_to_dict(row)
    db.delete(row)
    record_entity_changelog(
        db,
        entity_type="diagram_share",
        entity_id=int(share_id),
        action="deleted",
        before=before,
        after=None,
        user=user,
        request_method=request.method,
        request_path=request.url.path,
    )
    db.commit()
    return {"ok": True}


@router.post("/v1/diagrams/{diagram_ref}/export/google-drive")
def export_google_drive(
    diagram_ref: str,
    payload: GoogleDriveExportPayload,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    _require_perm(db, user, PERM_DIAGRAM_EXPORT, "Diagram export")
    _get_diagram(db, diagram_ref, user)
    try:
        return upload_base64_to_drive(
            content_base64=payload.content_base64,
            filename=payload.filename,
            mime_type=payload.mime_type,
            folder_id=payload.folder_id,
        )
    except GoogleDriveExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/v1/diagrams/{diagram_ref}/changelog")
def diagram_changelog(
    diagram_ref: str,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    diagram = _get_diagram(db, diagram_ref, user)
    return list_entity_changelogs(
        db, entity_type="diagram", entity_id=diagram.id, limit=100
    )


@router.get("/v1/public/diagrams/{diagram_uuid}/{public_token}")
def public_diagram_json(
    diagram_uuid: str, public_token: str, db: Session = Depends(get_db)
):
    diagram = _get_public_diagram(db, diagram_uuid, public_token)
    return _diagram_detail(db, diagram)


@router.get(
    "/v1/public/diagrams/{diagram_uuid}/{public_token}/bpmn",
    response_class=PlainTextResponse,
)
def public_diagram_bpmn(
    diagram_uuid: str, public_token: str, db: Session = Depends(get_db)
):
    diagram = _get_public_diagram(db, diagram_uuid, public_token)
    ver = _current_version(db, diagram)
    if (diagram.diagram_type or "bpmn") == "flowchart":
        source = _version_source(ver, "flowchart")
        media = "text/plain"
    elif (diagram.diagram_type or "bpmn") == "sequence":
        source = _version_source(ver, "sequence")
        media = "text/plain"
    else:
        source = _version_source(ver, "bpmn")
        media = "application/xml"
    return PlainTextResponse(source, media_type=media)


@router.get("/v1/public/diagrams/{diagram_uuid}/{public_token}/svg")
def public_diagram_svg(
    diagram_uuid: str, public_token: str, db: Session = Depends(get_db)
):
    diagram = _get_public_diagram(db, diagram_uuid, public_token)
    ver = _current_version(db, diagram)
    if not ver or not ver.svg_xml:
        raise HTTPException(
            status_code=404, detail="No SVG export stored for this diagram"
        )
    return Response(
        ver.svg_xml,
        media_type="image/svg+xml",
        headers={
            "Content-Disposition": f'attachment; filename="{diagram.slug or diagram.uuid}.svg"',
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/v1/diagrams/{diagram_ref}/export/{fmt}")
def export_diagram(
    diagram_ref: str,
    fmt: str,
    user: User = Depends(get_request_user),
    db: Session = Depends(get_db),
):
    _require_perm(db, user, PERM_DIAGRAM_EXPORT, "Diagram export")
    diagram = _get_diagram(db, diagram_ref, user)
    ver = _current_version(db, diagram)
    fmt = str(fmt or "").lower().strip()
    if fmt in {"bpmn", "sequence", "txt"}:
        is_sequence = (diagram.diagram_type or "bpmn") == "sequence"
        is_flowchart = (diagram.diagram_type or "bpmn") == "flowchart"
        if is_flowchart:
            source = _version_source(ver, "flowchart")
            ext = "mmd"
            media = "text/plain"
        elif is_sequence:
            source = _version_source(ver, "sequence")
            ext = "wsd"
            media = "text/plain"
        else:
            source = _version_source(ver, "bpmn")
            ext = "bpmn"
            media = "application/xml"
        return Response(
            source,
            media_type=media,
            headers={
                "Content-Disposition": f'attachment; filename="{diagram.slug or diagram.uuid}.{ext}"'
            },
        )
    if fmt == "svg":
        if not ver or not ver.svg_xml:
            raise HTTPException(
                status_code=404, detail="No SVG export stored for this diagram"
            )
        return Response(
            ver.svg_xml,
            media_type="image/svg+xml",
            headers={
                "Content-Disposition": f'attachment; filename="{diagram.slug or diagram.uuid}.svg"',
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
                "X-Content-Type-Options": "nosniff",
            },
        )
    raise HTTPException(
        status_code=400,
        detail="Server-side export supports bpmn and svg. PNG/JPG/PDF are exported by the browser UI.",
    )
