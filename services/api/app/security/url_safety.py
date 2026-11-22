"""Validation of addresses users store as links and pages navigate to.

The server-side half of the rule app.js's safeHref applies in the browser:
the two refuse the same things, so a value the API stores is one every page
links to as written.
"""

from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

_DISALLOWED_SCHEMES_RE = re.compile(r"^(?:javascript|data|vbscript):", re.IGNORECASE)
_BAD_ROUTE_CHARS = {ord("\\")} | set(range(0x00, 0x20)) | {0x7F}


def validate_safe_href(url: str, *, allow_relative: bool = True) -> str:
    """Validate a user-controlled URL before storing it for UI use.

    This is *not* an SSRF validator; it exists to prevent click-based XSS via
    javascript:/data: URLs and links that leave the site unexpectedly.
    Backslashes and control characters are refused anywhere: a browser reads
    "/\\host" as "//host", another site.

    Returns a normalized string (trimmed). Raises ValueError on invalid input.
    """

    raw = str(url or "").strip()
    if not raw:
        return ""
    if len(raw) > 2048:
        raise ValueError("URL too long")
    if "\\" in raw or any(ord(ch) in _BAD_ROUTE_CHARS for ch in raw):
        raise ValueError("URL contains a backslash or control character")

    if _DISALLOWED_SCHEMES_RE.match(raw):
        raise ValueError("Disallowed URL scheme")

    # Disallow protocol-relative URLs like //evil.example
    if raw.startswith("//"):
        raise ValueError("Protocol-relative URLs are not allowed")

    # Allow same-origin relative URLs.
    if allow_relative and raw.startswith("/"):
        return raw

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise ValueError("Only http/https URLs are allowed")

    # No credentials in URL
    if parsed.username or parsed.password:
        raise ValueError("Credentials in URL are not allowed")

    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ValueError("URL host is required")

    return raw


def safe_relative_route_path(value: str | None) -> str | None:
    """Return a safe same-origin relative path for redirects and stored links.

    Rejects protocol-relative URLs (``//evil``), absolute URLs, backslashes
    and control characters, any of which browsers treat as a different
    authority. ``None`` means the caller must fall back to a fixed route.
    """

    raw = (value or "").strip()
    if not raw:
        return None
    if not raw.startswith("/") or raw.startswith("//"):
        return None
    if "://" in raw:
        return None
    if any(ord(ch) in _BAD_ROUTE_CHARS for ch in raw):
        return None
    # A browser resolves dot segments before it navigates, so "/.//host"
    # arrives as "//host": no route here is written with one, encoded or not.
    path = raw.split("?", 1)[0].split("#", 1)[0]
    if any(unquote(segment) in {".", ".."} for segment in path.split("/")):
        return None
    return raw
