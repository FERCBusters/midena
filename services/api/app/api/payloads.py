from __future__ import annotations

import re
import uuid
from typing import Annotated, Any, Literal

from myf.security.passwords import MAX_PASSWORD_LENGTH
from myf.security.urls import external_url
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from app.api.deps import DB_INT_MAX

DbIdItem = Annotated[StrictInt, Field(ge=1, le=DB_INT_MAX)]

# -----------------------------------------------------------------------------
# Auth / admin
# -----------------------------------------------------------------------------


class AdminSetPasswordPayload(BaseModel):
    new_password: str = Field(min_length=8, max_length=MAX_PASSWORD_LENGTH)


class AdminUserCreatePayload(BaseModel):
    username: str = Field(min_length=1, max_length=160)
    email: str | None = Field(default=None, max_length=255)
    password: str = Field(min_length=8, max_length=MAX_PASSWORD_LENGTH)
    role: Literal["admin", "normal", "inherit"] = "normal"


class AdminUserUpdatePayload(BaseModel):
    role: Literal["admin", "normal", "inherit"] | None = None
    is_active: bool | None = None
    email: str | None = Field(default=None, max_length=255)


class AdminGroupCreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    role: str | None = Field(default=None, max_length=50)


class AdminGroupUpdatePayload(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    role: str | None = Field(default=None, max_length=50)


# Identifier lists are JSON arrays of integers: a string such as "12" is
# refused rather than read character by character.
class AdminUserAccessUpdatePayload(BaseModel):
    group_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    permission_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)


class AdminGroupPermissionsUpdatePayload(BaseModel):
    permission_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)


# -----------------------------------------------------------------------------
# Account / preferences
# -----------------------------------------------------------------------------


class UserPreferencesUpdatePayload(BaseModel):
    node_colors: dict | None = None
    default_start_page: str | None = Field(default=None, max_length=200)
    sticky_enabled: bool | None = None
    auto_apply_enabled: bool | None = None
    diagram_source_collapsed_by_default: bool | None = None
    diagram_sidebar_collapsed_by_default: bool | None = None
    theme: str | None = Field(default=None, max_length=16)


class UserShortcutCreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=4000)

    @field_validator("url", mode="before")
    @classmethod
    def _validate_url(cls, v):
        s = str(v or "").strip()
        if not s:
            return s
        return external_url(s, allow_relative=True)


# -----------------------------------------------------------------------------
# MIDENA folders / diagrams
# -----------------------------------------------------------------------------

# Diagram source and rendered SVG; the request limit for diagram writes is set
# from these (app.security.request_limits.MAX_DIAGRAM_BODY).
MAX_SOURCE_CHARS = 3_000_000
MAX_SVG_CHARS = 4_000_000
MAX_TAGS = 50
# Element identifiers come from bpmn-js and Mermaid: XML names and Mermaid
# node ids. Pages put them into selectors and markup, so they are held to
# that shape.
_ELEMENT_ID = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,254}")
_MAX_METADATA_KEYS = 50
_MAX_METADATA_VALUE_CHARS = 2000


def _clean_element_id(value: Any) -> Any:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if not _ELEMENT_ID.fullmatch(text):
        raise ValueError("element_id must be letters, digits and _ . : - (at most 255)")
    return text


def _clean_metadata(value: Any) -> dict[str, Any]:
    """A flat object of short scalar values."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("metadata must be an object")
    if len(value) > _MAX_METADATA_KEYS:
        raise ValueError(f"metadata holds at most {_MAX_METADATA_KEYS} entries")
    out: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key or len(key) > 80:
            raise ValueError("metadata keys must be 1-80 characters")
        if isinstance(item, str):
            if len(item) > _MAX_METADATA_VALUE_CHARS:
                raise ValueError("metadata values are at most 2000 characters")
        elif item is not None and not isinstance(item, (bool, int, float)):
            raise ValueError("metadata values must be text, numbers or booleans")
        out[key] = item
    return out


def _clean_tags(values: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    if len(values or []) > MAX_TAGS:
        raise ValueError(f"a diagram holds at most {MAX_TAGS} tags")
    for raw in values or []:
        s = str(raw or "").strip()
        if not s:
            continue
        if len(s) > 80:
            raise ValueError("tags must be at most 80 characters")
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _normalise_diagram_type(value: str | None) -> str:
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
        raise ValueError("diagram_type must be bpmn, sequence, or flowchart")
    return aliases[raw]


def _normalise_visibility(value: str | None) -> str:
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
        raise ValueError("visibility must be private, internal, or public")
    return aliases[raw]


def _validate_link_url(value: str | None) -> str | None:
    if value is None:
        return None
    s = str(value or "").strip()
    if not s:
        return None
    return external_url(s)


_TAG_COLOUR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _normalise_tag_name(value: str | None) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("tag name must not be empty")
    if len(name) > 80:
        raise ValueError("tag name must be at most 80 characters")
    return name


def _normalise_tag_colour(value: str | None) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    colour = str(value).strip()
    if not _TAG_COLOUR_RE.match(colour):
        raise ValueError("tag colour must be a #RRGGBB hex colour")
    return colour.lower()


class DiagramTagCreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    color: str | None = Field(default=None, max_length=7)

    @field_validator("name", mode="before")
    @classmethod
    def _clean_name(cls, v):
        return _normalise_tag_name(v)

    @field_validator("color", mode="before")
    @classmethod
    def _clean_colour(cls, v):
        return _normalise_tag_colour(v)


class DiagramTagUpdatePayload(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    color: str | None = Field(default=None, max_length=7)

    @field_validator("name", mode="before")
    @classmethod
    def _clean_name(cls, v):
        return _normalise_tag_name(v) if v is not None else None

    @field_validator("color", mode="before")
    @classmethod
    def _clean_colour(cls, v):
        return _normalise_tag_colour(v)


class FolderCreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parent_id: int | None = Field(default=None, ge=1, le=DB_INT_MAX)
    description: str | None = Field(default=None, max_length=4000)
    sort_order: int = Field(default=0, ge=-1_000_000, le=1_000_000)


class FolderUpdatePayload(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    parent_id: int | None = Field(default=None, ge=1, le=DB_INT_MAX)
    description: str | None = Field(default=None, max_length=4000)
    sort_order: int | None = Field(default=None, ge=-1_000_000, le=1_000_000)


class DiagramCreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=8000)
    folder_id: int | None = Field(default=None, ge=1, le=DB_INT_MAX)
    visibility: str = "private"
    tags: list[str] = Field(default_factory=list)
    diagram_type: str = "bpmn"
    bpmn_xml: str | None = Field(default=None, max_length=MAX_SOURCE_CHARS)
    sequence_text: str | None = Field(default=None, max_length=MAX_SOURCE_CHARS)
    flowchart_text: str | None = Field(default=None, max_length=MAX_SOURCE_CHARS)
    source_text: str | None = Field(default=None, max_length=MAX_SOURCE_CHARS)
    svg_xml: str | None = Field(default=None, max_length=MAX_SVG_CHARS)
    header_text: str | None = Field(default=None, max_length=4000)
    footer_text: str | None = Field(default=None, max_length=4000)

    @field_validator("tags", mode="before")
    @classmethod
    def _normalise_tags(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return _clean_tags(v.replace("\n", ",").split(","))
        return _clean_tags(list(v or []))

    @field_validator("diagram_type", mode="before")
    @classmethod
    def _normalise_type(cls, v):
        return _normalise_diagram_type(v)

    @field_validator("visibility", mode="before")
    @classmethod
    def _normalise_visibility_value(cls, v):
        return _normalise_visibility(v)


class DiagramUpdatePayload(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=8000)
    folder_id: int | None = Field(default=None, ge=1, le=DB_INT_MAX)
    visibility: str | None = None
    tags: list[str] | None = None
    header_text: str | None = Field(default=None, max_length=4000)
    footer_text: str | None = Field(default=None, max_length=4000)

    @field_validator("tags", mode="before")
    @classmethod
    def _normalise_tags(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            return _clean_tags(v.replace("\n", ",").split(","))
        return _clean_tags(list(v or []))

    @field_validator("visibility", mode="before")
    @classmethod
    def _normalise_visibility_value(cls, v):
        return _normalise_visibility(v)


class DiagramSavePayload(BaseModel):
    diagram_type: str | None = None
    bpmn_xml: str | None = Field(default=None, max_length=MAX_SOURCE_CHARS)
    sequence_text: str | None = Field(default=None, max_length=MAX_SOURCE_CHARS)
    flowchart_text: str | None = Field(default=None, max_length=MAX_SOURCE_CHARS)
    source_text: str | None = Field(default=None, max_length=MAX_SOURCE_CHARS)
    svg_xml: str | None = Field(default=None, max_length=MAX_SVG_CHARS)
    change_summary: str | None = Field(default=None, max_length=4000)

    @field_validator("diagram_type", mode="before")
    @classmethod
    def _normalise_type(cls, v):
        return _normalise_diagram_type(v) if v is not None else None


class DiagramAIMessagePayload(BaseModel):
    role: str = Field(min_length=1, max_length=20)
    content: str = Field(min_length=1, max_length=20_000)

    @field_validator("role", mode="before")
    @classmethod
    def _normalise_role(cls, v):
        raw = str(v or "").strip().lower()
        if raw not in {"user", "assistant"}:
            raise ValueError("AI message role must be user or assistant")
        return raw


class DiagramAIGeneratePayload(BaseModel):
    diagram_type: str = Field(default="flowchart")
    messages: list[DiagramAIMessagePayload] = Field(default_factory=list)
    prompt: str | None = Field(default=None, max_length=20_000)
    # Only the first 12,000 characters are sent to the provider.
    current_source: str | None = Field(default=None, max_length=MAX_SOURCE_CHARS)

    @field_validator("diagram_type", mode="before")
    @classmethod
    def _normalise_type(cls, v):
        value = _normalise_diagram_type(v)
        if value == "bpmn":
            raise ValueError(
                "AI generation is available for sequence diagrams and flowcharts"
            )
        return value

    @field_validator("messages")
    @classmethod
    def _limit_messages(cls, v):
        if len(v or []) > 16:
            raise ValueError("AI chat history is limited to 16 messages")
        return v or []


class DiagramLockPayload(BaseModel):
    ttl_seconds: int | None = Field(default=900, ge=60, le=14400)
    note: str | None = Field(default=None, max_length=2000)


class DiagramCommentCreatePayload(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    element_id: str | None = Field(default=None, max_length=255)

    @field_validator("element_id", mode="before")
    @classmethod
    def _element(cls, v):
        return _clean_element_id(v)


class DiagramCommentUpdatePayload(BaseModel):
    body: str | None = Field(default=None, min_length=1, max_length=4000)
    is_resolved: bool | None = None


class DiagramEntityLinkPayload(BaseModel):
    element_id: str = Field(min_length=1, max_length=255)
    label: str = Field(min_length=1, max_length=512)
    url: str = Field(min_length=1, max_length=4000)
    entity_type: str | None = Field(default=None, max_length=80)
    entity_ref: str | None = Field(default=None, max_length=512)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("element_id", mode="before")
    @classmethod
    def _element(cls, v):
        return _clean_element_id(v)

    @field_validator("metadata", mode="before")
    @classmethod
    def _metadata(cls, v):
        return _clean_metadata(v)

    @field_validator("url", mode="before")
    @classmethod
    def _validate_url(cls, v):
        if v is None:
            return None
        s = str(v or "").strip()
        if not s:
            return None
        return external_url(s, allow_relative=True)


class DiagramMetadataLinkPayload(BaseModel):
    label: str = Field(min_length=1, max_length=512)
    url: str = Field(min_length=1, max_length=4000)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("url", mode="before")
    @classmethod
    def _validate_url(cls, v):
        return _validate_link_url(v)


class DiagramSharePayload(BaseModel):
    identifier: str = Field(min_length=1, max_length=255)
    role: str = Field(default="viewer", max_length=32)
    notify: bool = True

    @field_validator("role", mode="before")
    @classmethod
    def _normalise_role(cls, v):
        raw = str(v or "viewer").strip().lower()
        if raw not in {"viewer", "editor"}:
            raise ValueError("share role must be viewer or editor")
        return raw


class GoogleDriveExportPayload(BaseModel):
    """One export to the installation's Drive folder. ``content_base64`` is
    read for the browser-drawn formats (png, jpg, pdf) only; the folder and
    the file's name are never the browser's to choose."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["png", "jpg", "pdf", "svg", "source"]
    # MAX_EXPORT_BYTES (8 MiB) once decoded.
    content_base64: str | None = Field(default=None, max_length=11_200_000)


class GlobalDiagramChromePayload(BaseModel):
    header_text: str | None = Field(default=None, max_length=4000)
    footer_text: str | None = Field(default=None, max_length=4000)
    theme_settings: dict[str, Any] | None = None
