from __future__ import annotations

import base64
import io
import json
from typing import Any

from app.core.config import settings


class GoogleDriveExportError(RuntimeError):
    """Raised when Google Drive export is not configured or fails."""


def _service_account_info() -> dict[str, Any]:
    raw = (settings.google_drive_service_account_json or "").strip()
    file_path = (settings.google_drive_service_account_file or "").strip()
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GoogleDriveExportError(
                "MIDENA_GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON is not valid JSON"
            ) from exc
    if file_path:
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except OSError as exc:
            raise GoogleDriveExportError(
                "MIDENA_GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE could not be read"
            ) from exc
        except json.JSONDecodeError as exc:
            raise GoogleDriveExportError(
                "MIDENA_GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE is not valid JSON"
            ) from exc
    raise GoogleDriveExportError(
        "Google Drive export is not configured. Set a service account JSON value or file."
    )


def upload_base64_to_drive(
    *,
    content_base64: str,
    filename: str,
    mime_type: str,
    folder_id: str | None = None,
) -> dict[str, str | None]:
    """Upload a browser-generated export to Google Drive using a service account.

    The import is intentionally lazy so deployments that do not use Google Drive
    do not need these optional packages until the feature is enabled.
    """

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseUpload
    except Exception as exc:  # pragma: no cover - environment dependent
        raise GoogleDriveExportError(
            "Google Drive export packages are not installed. Install google-api-python-client and google-auth."
        ) from exc

    try:
        content = base64.b64decode(content_base64, validate=True)
    except Exception as exc:
        raise GoogleDriveExportError("Export content was not valid base64") from exc

    scopes = ["https://www.googleapis.com/auth/drive.file"]
    creds = service_account.Credentials.from_service_account_info(
        _service_account_info(), scopes=scopes
    )
    delegated_user = (settings.google_drive_delegated_user or "").strip()
    if delegated_user:
        creds = creds.with_subject(delegated_user)

    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    target_folder = (folder_id or settings.google_drive_default_folder_id or "").strip()
    metadata: dict[str, Any] = {"name": filename}
    if target_folder:
        metadata["parents"] = [target_folder]

    media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime_type, resumable=False)
    created = (
        service.files()
        .create(
            body=metadata,
            media_body=media,
            fields="id,name,webViewLink,webContentLink",
            supportsAllDrives=True,
        )
        .execute()
    )
    return {
        "id": created.get("id"),
        "name": created.get("name"),
        "webViewLink": created.get("webViewLink"),
        "webContentLink": created.get("webContentLink"),
    }
