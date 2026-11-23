"""Where mosp asks MIDENA to take part (mosp.host.hooks).

Every hook left out here keeps mosp's default.
"""

from __future__ import annotations

from mosp.security.regex import scan_pattern

# Most MIDENA writes are small JSON forms.
MAX_BODY = 2 * 1024 * 1024
# A diagram save carries its source and the SVG the browser rendered from it.
MAX_DIAGRAM_BODY = 8 * 1024 * 1024
# A Google Drive export carries one rendered PNG, JPEG or PDF, base64-encoded:
# app.services.google_drive.MAX_EXPORT_BYTES decoded, plus base64's third.
MAX_DRIVE_EXPORT_BODY = 12 * 1024 * 1024

_DIAGRAM_WRITES = scan_pattern(r"/v1/diagrams(?:/[^/]+/save)?")
_DRIVE_EXPORTS = scan_pattern(r"/v1/diagrams/[^/]+/export/google-drive")


def route_policy():
    from app.security.route_policy import MIDENA_POLICY

    return MIDENA_POLICY


def audit_path(path: str) -> str:
    from app.security import route_policy

    return route_policy.audit_path(path)


def origin_required() -> bool:
    # Every browser MIDENA serves sends Origin with its writes; a write
    # without one did not come from MIDENA's pages.
    return True


def body_limit(path: str) -> int:
    if _DIAGRAM_WRITES.fullmatch(path):
        return MAX_DIAGRAM_BODY
    if _DRIVE_EXPORTS.fullmatch(path):
        return MAX_DRIVE_EXPORT_BODY
    return MAX_BODY
