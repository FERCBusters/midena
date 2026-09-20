from __future__ import annotations

import copy
import re
from typing import Any

DEFAULT_DIAGRAM_THEME: dict[str, dict[str, Any]] = {
    "bpmn": {
        "fill_color": "#ffffff",
        "stroke_color": "#344054",
        "text_color": "#1f2937",
        "connector_color": "#667085",
        "border_width": 1.5,
        "connector_width": 1.8,
        "font_family": "Arial, sans-serif",
        "font_size": 14,
    },
    "flowchart": {
        "fill_color": "#ffffff",
        "stroke_color": "#2563eb",
        "text_color": "#111827",
        "connector_color": "#64748b",
        "border_width": 1.5,
        "connector_width": 1.8,
        "font_family": "Arial, sans-serif",
        "font_size": 14,
    },
    "sequence": {
        "fill_color": "#ffffff",
        "stroke_color": "#2563eb",
        "text_color": "#111827",
        "connector_color": "#475467",
        "border_width": 1.5,
        "connector_width": 1.8,
        "font_family": "Arial, sans-serif",
        "font_size": 14,
    },
}

_COLOR_FIELDS = {"fill_color", "stroke_color", "text_color", "connector_color"}
_NUMBER_FIELDS = {
    "border_width": (0.5, 8.0),
    "connector_width": (0.5, 8.0),
    "font_size": (8.0, 28.0),
}
_FONT_RE = re.compile(r"^[A-Za-z0-9 ,.'\"_-]{1,120}$")
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _clean_colour(value: Any, fallback: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    if not _HEX_RE.match(raw):
        return fallback
    return raw.lower()


def _clean_number(value: Any, fallback: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if number < minimum:
        return minimum
    if number > maximum:
        return maximum
    return round(number, 2)


def _clean_font(value: Any, fallback: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    if not _FONT_RE.match(raw):
        return fallback
    return raw


def normalise_diagram_theme(value: Any) -> dict[str, dict[str, Any]]:
    """Return a safe global diagram theme with defaults for every diagram type."""
    incoming = value if isinstance(value, dict) else {}
    out = copy.deepcopy(DEFAULT_DIAGRAM_THEME)
    for diagram_type, defaults in DEFAULT_DIAGRAM_THEME.items():
        type_in = incoming.get(diagram_type)
        if not isinstance(type_in, dict):
            continue
        for field in _COLOR_FIELDS:
            out[diagram_type][field] = _clean_colour(
                type_in.get(field), defaults[field]
            )
        for field, (minimum, maximum) in _NUMBER_FIELDS.items():
            out[diagram_type][field] = _clean_number(
                type_in.get(field), defaults[field], minimum, maximum
            )
        out[diagram_type]["font_family"] = _clean_font(
            type_in.get("font_family"), defaults["font_family"]
        )
    return out
