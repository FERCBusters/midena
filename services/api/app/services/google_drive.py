"""Upload a diagram export to the installation's Google Drive folder.

The service account's credentials can write wherever the account (or the
Workspace user it acts as) can, so the browser chooses nothing about where a
file goes or what it is called: every export lands in the one configured
folder (MIDENA_GOOGLE_DRIVE_FOLDER_ID), named after the diagram, with a media
type fixed by its format. Source and SVG exports are built here from the
stored version; PNG, JPEG and PDF are drawn by the browser, so their bytes
must begin as their format does and stay within MAX_EXPORT_BYTES.

Every request to Google goes to a fixed HTTPS address with verified TLS, no
redirects, a time limit, and a bounded answer. The token request signs a JWT
with the service account's key (RFC 7523) through joserfc.
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx2 as httpx
from joserfc import jwt
from joserfc.jwk import RSAKey

from app.core.config import settings

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = (
    "https://www.googleapis.com/upload/drive/v3/files"
    "?uploadType=multipart&supportsAllDrives=true&fields=id,name,webViewLink"
)
SCOPE = "https://www.googleapis.com/auth/drive.file"
# A rendered page or image of a large diagram; the request limit for the
# export route is set from this figure.
MAX_EXPORT_BYTES = 8 * 1024 * 1024
# Google's answers are small JSON documents.
_MAX_ANSWER_BYTES = 64 * 1024
_MAX_KEY_FILE_BYTES = 64 * 1024


@dataclass(frozen=True)
class ExportFormat:
    extension: str
    media_type: str
    magic: tuple[bytes, ...]  # Empty: built by the server, not the browser.


FORMATS: dict[str, ExportFormat] = {
    "png": ExportFormat("png", "image/png", (b"\x89PNG\r\n\x1a\n",)),
    "jpg": ExportFormat("jpg", "image/jpeg", (b"\xff\xd8\xff",)),
    "pdf": ExportFormat("pdf", "application/pdf", (b"%PDF-",)),
    "svg": ExportFormat("svg", "image/svg+xml", ()),
    "source": ExportFormat("txt", "text/plain", ()),
}
BROWSER_FORMATS = frozenset(key for key, fmt in FORMATS.items() if fmt.magic)


class GoogleDriveExportError(RuntimeError):
    """The export could not be made; the message is safe to show."""


def configured() -> bool:
    return bool(
        settings.google_drive_folder_id.strip()
        and (
            settings.google_drive_service_account_json.strip()
            or settings.google_drive_service_account_file.strip()
        )
    )


def _service_account() -> dict[str, Any]:
    raw = settings.google_drive_service_account_json.strip()
    if not raw:
        path = settings.google_drive_service_account_file.strip()
        try:
            with open(path, "rb") as handle:
                data = handle.read(_MAX_KEY_FILE_BYTES + 1)
        except OSError:
            raise GoogleDriveExportError(
                "Google Drive export is not available right now."
            ) from None
        if len(data) > _MAX_KEY_FILE_BYTES:
            raise GoogleDriveExportError(
                "Google Drive export is not available right now."
            )
        raw = data.decode("utf-8", "replace")
    try:
        info = json.loads(raw)
    except ValueError:
        raise GoogleDriveExportError(
            "Google Drive export is not available right now."
        ) from None
    if not (
        isinstance(info, dict)
        and isinstance(info.get("client_email"), str)
        and isinstance(info.get("private_key"), str)
    ):
        raise GoogleDriveExportError("Google Drive export is not available right now.")
    return info


def _bounded_json(response: httpx.Response) -> dict[str, Any]:
    body = b""
    for chunk in response.iter_bytes():
        body += chunk
        if len(body) > _MAX_ANSWER_BYTES:
            raise GoogleDriveExportError("Google Drive gave an unexpected answer.")
    try:
        value = json.loads(body)
    except ValueError:
        raise GoogleDriveExportError(
            "Google Drive gave an unexpected answer."
        ) from None
    if not isinstance(value, dict):
        raise GoogleDriveExportError("Google Drive gave an unexpected answer.")
    return value


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(settings.google_drive_timeout_seconds),
        follow_redirects=False,
        verify=True,
        trust_env=False,
    )


def _access_token(client: httpx.Client) -> str:
    info = _service_account()
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": info["client_email"],
        "scope": SCOPE,
        "aud": TOKEN_URL,
        "iat": now,
        "exp": now + 600,
        "jti": secrets.token_urlsafe(16),
    }
    delegated = settings.google_drive_delegated_user.strip()
    if delegated:
        claims["sub"] = delegated
    header = {"alg": "RS256", "typ": "JWT"}
    if isinstance(info.get("private_key_id"), str):
        header["kid"] = info["private_key_id"]
    try:
        assertion = jwt.encode(
            header, claims, RSAKey.import_key(info["private_key"]), algorithms=["RS256"]
        )
    except Exception:
        raise GoogleDriveExportError(
            "Google Drive export is not available right now."
        ) from None
    with client.stream(
        "POST",
        TOKEN_URL,
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        },
        headers={"Accept": "application/json"},
    ) as response:
        answer = _bounded_json(response)
        ok = response.status_code == 200
    token = answer.get("access_token")
    if not ok or not isinstance(token, str) or not token:
        raise GoogleDriveExportError("Google Drive refused the export.")
    return token


def _web_link(value: Any) -> str | None:
    """Google's link to the file, only when it is an https Google address."""
    if not isinstance(value, str):
        return None
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or host not in {
        "drive.google.com",
        "docs.google.com",
    }:
        return None
    return value


def upload(*, name: str, fmt: ExportFormat, content: bytes) -> dict[str, str | None]:
    """Upload one file to the configured folder; Google's id, name and link."""
    if not configured():
        raise GoogleDriveExportError("Google Drive export is not configured.")
    if len(content) > MAX_EXPORT_BYTES:
        raise GoogleDriveExportError("The export is too large for Google Drive.")
    boundary = secrets.token_hex(16)
    metadata = json.dumps(
        {"name": name, "parents": [settings.google_drive_folder_id.strip()]}
    ).encode()
    body = b"".join(
        [
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode(),
            metadata,
            f"\r\n--{boundary}\r\nContent-Type: {fmt.media_type}\r\n\r\n".encode(),
            content,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    try:
        with _client() as client:
            token = _access_token(client)
            with client.stream(
                "POST",
                UPLOAD_URL,
                content=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": f"multipart/related; boundary={boundary}",
                    "Accept": "application/json",
                },
            ) as response:
                answer = _bounded_json(response)
                ok = response.status_code in (200, 201)
    except httpx.HTTPError:
        raise GoogleDriveExportError("Google Drive could not be reached.") from None
    if not ok or not isinstance(answer.get("id"), str):
        raise GoogleDriveExportError("Google Drive refused the export.")
    return {
        "id": answer["id"][:256],
        "name": str(answer.get("name") or name)[:256],
        "webViewLink": _web_link(answer.get("webViewLink")),
    }
