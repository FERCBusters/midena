from __future__ import annotations

from urllib.parse import urlsplit

from mosp.config import MospSettings
from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict


class Settings(MospSettings):
    """MIDENA's settings: mosp's (mosp.config.MospSettings) and MIDENA's own."""

    model_config = SettingsConfigDict(
        env_prefix="MIDENA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # MIDENA's names and defaults for settings mosp defines.
    session_cookie_name: str = Field(default="midena_session")
    session_ttl_seconds: int = Field(default=60 * 60 * 12)
    csrf_cookie_name: str = Field(default="midena_csrf")
    smtp_from_name: str = Field(default="MIDENA")
    audit_log_retention_days: int = Field(default=90, ge=0, le=36500)

    app_title: str = Field(default="MIDENA")

    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8080)

    # ---------------------------------------------------------------------
    # Background jobs (Celery)
    # ---------------------------------------------------------------------
    celery_broker_url: str = Field(default="")
    celery_result_backend: str = Field(default="")
    celery_timezone: str = Field(default="UTC")
    # How long a worker task may run before it is stopped.
    task_time_limit_seconds: int = Field(default=900, ge=120)

    # ---------------------------------------------------------------------
    # Installation feature switches
    # ---------------------------------------------------------------------
    # Each switch turns an optional product area off entirely: its routes
    # answer 404 and the UI hides its controls. Authentication, account
    # security, administration and private diagram editing stay on. These
    # settings are a ceiling: administrators can turn a feature off on the
    # Administration page, never on beyond what the deployment allows.
    feature_public_diagrams: bool = Field(default=True)
    feature_ai_generation: bool = Field(default=True)
    feature_google_drive_export: bool = Field(default=True)

    # ---------------------------------------------------------------------
    # Google Drive export (Workspace service account)
    # ---------------------------------------------------------------------
    google_drive_service_account_json: str = Field(default="", repr=False)
    google_drive_service_account_file: str = Field(default="")
    google_drive_delegated_user: str = Field(default="")
    # Exports land in this folder. Browsers never choose a Drive folder: the
    # service account's credentials could otherwise write anywhere they reach.
    google_drive_folder_id: str = Field(default="")
    google_drive_timeout_seconds: int = Field(default=60, ge=5, le=300)
    # Exports each account may send to Drive per hour.
    google_drive_exports_per_hour: int = Field(default=30, ge=1, le=1000)

    # ---------------------------------------------------------------------
    # AI-assisted Mermaid generation (OpenAI-compatible /chat/completions)
    # ---------------------------------------------------------------------
    # The API key stays server-side; the browser only talks to MIDENA.
    ai_api_base_url: str = Field(default="https://api.regolo.ai/v1")
    ai_api_key: str = Field(default="", repr=False)
    ai_model: str = Field(default="")
    ai_temperature: float = Field(default=0.2, ge=0.0, le=1.0)
    ai_max_tokens: int = Field(default=2500, ge=256, le=12000)
    ai_timeout_seconds: int = Field(default=45, ge=5, le=120)
    # Requests each account may make per window.
    ai_rate_limit_attempts: int = Field(default=30, ge=1, le=10000)
    ai_rate_limit_window_seconds: int = Field(default=3600, ge=60, le=86400)

    @field_validator("ai_api_base_url")
    @classmethod
    def _validate_ai_base_url(cls, value: str) -> str:
        """The API key travels to this address, so it must be HTTPS (plain
        HTTP only on localhost, for development) and carry no credentials."""
        text = value.strip().rstrip("/")
        if not text:
            return ""
        parts = urlsplit(text)
        host = (parts.hostname or "").lower()
        local = host in {"localhost", "127.0.0.1", "::1"}
        if (
            parts.scheme not in {"https", "http"}
            or (parts.scheme == "http" and not local)
            or not host
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
        ):
            raise ValueError(
                "MIDENA_AI_API_BASE_URL must be an https:// address without "
                "credentials, query or fragment"
            )
        return text


settings = Settings()
