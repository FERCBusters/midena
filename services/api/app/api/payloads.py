from __future__ import annotations

from typing import Any
import re

from pydantic import BaseModel, Field, field_validator

from app.security.url_safety import validate_safe_href

# -----------------------------------------------------------------------------
# Auth / admin
# -----------------------------------------------------------------------------


class LoginPayload(BaseModel):
    username: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=8, max_length=200)


class ChangePasswordPayload(BaseModel):
    current_password: str = Field(min_length=8, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)
    confirm_password: str = Field(min_length=8, max_length=200)


class PasswordResetRequestPayload(BaseModel):
    identifier: str = Field(min_length=1, max_length=255)


class PasswordResetConfirmPayload(BaseModel):
    token: str = Field(min_length=10, max_length=512)
    new_password: str = Field(min_length=8, max_length=200)
    confirm_password: str = Field(min_length=8, max_length=200)


class AdminUserCreatePayload(BaseModel):
    username: str = Field(min_length=1, max_length=160)
    email: str | None = Field(default=None, max_length=255)
    password: str = Field(min_length=8, max_length=200)
    role: str = Field(min_length=1, max_length=50)


class AdminUserUpdatePayload(BaseModel):
    role: str | None = Field(default=None, min_length=1, max_length=50)
    is_active: bool | None = None
    email: str | None = Field(default=None, max_length=255)


class AdminGroupCreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=50)


class AdminGroupUpdatePayload(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=50)


class AdminUserAccessUpdatePayload(BaseModel):
    group_ids: list[int] | None = None
    permission_ids: list[int] | None = None


class AdminGroupPermissionsUpdatePayload(BaseModel):
    permission_ids: list[int] | None = None


# -----------------------------------------------------------------------------
# Account / preferences
# -----------------------------------------------------------------------------


class UserPreferencesUpdatePayload(BaseModel):
    node_colors: dict | None = None
    default_start_page: str | None = None
    sticky_enabled: bool | None = None
    auto_apply_enabled: bool | None = None
    diagram_source_collapsed_by_default: bool | None = None
    diagram_sidebar_collapsed_by_default: bool | None = None


class UserShortcutCreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=4000)

    @field_validator("url", mode="before")
    @classmethod
    def _validate_url(cls, v):
        s = str(v or "").strip()
        if not s:
            return s
        return validate_safe_href(s, allow_relative=True)


class MeProfileUpdatePayload(BaseModel):
    email: str | None = Field(default=None, max_length=255)


class UserEmailCreatePayload(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    is_primary: bool = False


# -----------------------------------------------------------------------------
# MIDENA folders / diagrams
# -----------------------------------------------------------------------------


def _clean_tags(values: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
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
    return validate_safe_href(s, allow_relative=False)


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
    parent_id: int | None = Field(default=None, ge=1)
    description: str | None = Field(default=None, max_length=4000)
    sort_order: int | None = 0


class FolderUpdatePayload(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    parent_id: int | None = Field(default=None, ge=1)
    description: str | None = Field(default=None, max_length=4000)
    sort_order: int | None = None


class DiagramCreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=8000)
    folder_id: int | None = Field(default=None, ge=1)
    visibility: str = "private"
    tags: list[str] | None = None
    diagram_type: str = "bpmn"
    bpmn_xml: str | None = Field(default=None, max_length=5_000_000)
    sequence_text: str | None = Field(default=None, max_length=5_000_000)
    flowchart_text: str | None = Field(default=None, max_length=5_000_000)
    source_text: str | None = Field(default=None, max_length=5_000_000)
    svg_xml: str | None = Field(default=None, max_length=5_000_000)
    header_text: str | None = Field(default=None, max_length=4000)
    footer_text: str | None = Field(default=None, max_length=4000)

    @field_validator("tags", mode="before")
    @classmethod
    def _normalise_tags(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return _clean_tags([x for x in re.split(r"[,\n]", v)])
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
    folder_id: int | None = Field(default=None, ge=1)
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
            return _clean_tags([x for x in re.split(r"[,\n]", v)])
        return _clean_tags(list(v or []))

    @field_validator("visibility", mode="before")
    @classmethod
    def _normalise_visibility_value(cls, v):
        return _normalise_visibility(v)


class DiagramSavePayload(BaseModel):
    diagram_type: str | None = None
    bpmn_xml: str | None = Field(default=None, max_length=5_000_000)
    sequence_text: str | None = Field(default=None, max_length=5_000_000)
    flowchart_text: str | None = Field(default=None, max_length=5_000_000)
    source_text: str | None = Field(default=None, max_length=5_000_000)
    svg_xml: str | None = Field(default=None, max_length=5_000_000)
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
    current_source: str | None = Field(default=None, max_length=5_000_000)

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


class DiagramCommentUpdatePayload(BaseModel):
    body: str | None = Field(default=None, min_length=1, max_length=4000)
    is_resolved: bool | None = None


class DiagramEntityLinkPayload(BaseModel):
    element_id: str = Field(min_length=1, max_length=255)
    label: str = Field(min_length=1, max_length=512)
    url: str = Field(min_length=1, max_length=4000)
    entity_type: str | None = Field(default=None, max_length=80)
    entity_ref: str | None = Field(default=None, max_length=512)
    metadata: dict[str, Any] | None = None

    @field_validator("url", mode="before")
    @classmethod
    def _validate_url(cls, v):
        if v is None:
            return None
        s = str(v or "").strip()
        if not s:
            return None
        return validate_safe_href(s, allow_relative=True)


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
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1, max_length=25_000_000)
    folder_id: str | None = Field(default=None, max_length=512)


class GlobalDiagramChromePayload(BaseModel):
    header_text: str | None = Field(default=None, max_length=4000)
    footer_text: str | None = Field(default=None, max_length=4000)
    theme_settings: dict[str, Any] | None = None
