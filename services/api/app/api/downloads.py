"""Attachment names and media types for every file the API serves.

Ported from KEEN's ``app/storage/filenames.py``. Every route that streams a
stored or computed file sets its type and name through these functions;
tests/test_downloads.py refuses any other non-constant media type.
"""

from __future__ import annotations

from urllib.parse import quote

# Media types a browser only displays or saves. A download keeps its type only
# when it is one of these. Any other type, SVG and XML included, is served as
# application/octet-stream: with nosniff, a browser then never treats the file
# as a same-origin document, script or style sheet. (KEEN's rule.)
PASSIVE_DOWNLOAD_TYPES = frozenset(
    {
        "application/json",
        "application/pdf",
        "image/jpeg",
        "image/png",
        "text/plain",
    }
)


def attachment_media_type(content_type: str | None) -> str:
    base = (content_type or "").split(";", 1)[0].strip().lower()
    return base if base in PASSIVE_DOWNLOAD_TYPES else "application/octet-stream"


def content_disposition_attachment(filename: str) -> str:
    """RFC 6266/5987 Content-Disposition: a plain ASCII name and the full
    name in the encoded ``filename*`` form."""
    safe = "".join(ch for ch in filename if ord(ch) >= 32 and ord(ch) != 127)
    safe = (
        safe.replace('"', "").replace("\\", "_").replace("/", "_")[:255] or "download"
    )
    fallback = safe.encode("ascii", "replace").decode("ascii")
    return (
        f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(safe, safe='')}"
    )
