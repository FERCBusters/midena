from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MIDENA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_title: str = Field(default="MIDENA")

    database_url: str = Field(default="")

    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8080)

    # session/cookie
    session_cookie_name: str = Field(default="midena_session")
    session_ttl_seconds: int = Field(default=60 * 60 * 12)
    cookie_secure: bool = Field(default=True)
    cookie_samesite: str = Field(default="lax")
    cookie_domain: str = Field(default="")

    # CSRF
    csrf_cookie_name: str = Field(default="midena_csrf")
    csrf_header_name: str = Field(default="X-CSRF-Token")
    csrf_cookie_samesite: str = Field(default="strict")

    # Reverse-proxy headers (X-Forwarded-Proto, X-Forwarded-For).
    # Enable only when the app is behind a trusted proxy/ingress that strips
    # client-supplied forwarded headers.
    trust_proxy_headers: bool = Field(default=False)

    # Comma-separated CIDR networks whose hosts may form the trusted side of a
    # forwarded client address chain (X-Forwarded-For / X-Real-IP). Client
    # addresses for rate limits, audit records and identity headers are
    # resolved by walking the forwarded list from the socket peer right-to-left
    # only while each hop is inside these networks; everything else is treated
    # as untrusted. docker-compose.yml sets exactly its midena-ui address
    # and network gateway.
    trusted_proxy_cidrs: str = Field(default="127.0.0.1,::1")

    # Hard ceiling on how long a session may live however recently it was used.
    session_absolute_ttl_seconds: int = Field(default=60 * 60 * 24 * 30)

    # Request-audit retention in days; the beat sweeper deletes older rows.
    audit_log_retention_days: int = Field(default=90, ge=0, le=36500)

    # Native (local) username/password login
    local_auth_enabled: bool = Field(default=True)

    # Optional first administrator, created only while the database holds no
    # account at all (KEEN's rule); remove the values after first sign-in.
    bootstrap_admin_username: str = Field(default="")
    bootstrap_admin_password: str = Field(default="", repr=False)
    bootstrap_admin_email: str = Field(default="")

    # ---------------------------------------------------------------------
    # Local second factor (TOTP, security keys/passkeys, recovery codes)
    # ---------------------------------------------------------------------
    # Which accounts must present a second factor on local sign-in:
    # "optional", "admins" or "all".
    mfa_policy: str = Field(default="optional")
    # Persistent Fernet key (base64, 32 url-safe base64-encoded bytes) used to
    # encrypt at-rest TOTP secrets, e.g. `openssl rand -base64 32`. Without a
    # valid key TOTP enrolment and verification answer 503, and existing
    # secrets cannot be decrypted, so enrolment stays refused.
    mfa_encryption_key: str = Field(default="", repr=False)

    @field_validator("mfa_policy")
    @classmethod
    def _validate_mfa_policy(cls, value: str) -> str:
        if value not in {"optional", "admins", "all"}:
            raise ValueError("MFA policy must be optional, admins or all")
        return value

    # Characters a new local password needs, as in KEEN. NIST SP 800-63B-4
    # asks for 15 where a password can be an account's only factor, and allows
    # as few as eight where every account also uses a second factor.
    password_min_length: int = Field(default=15, ge=8, le=128)

    @model_validator(mode="after")
    def _validate_password_min_length(self) -> "Settings":
        if self.password_min_length < 15 and self.mfa_policy != "all":
            raise ValueError(
                "MIDENA_PASSWORD_MIN_LENGTH below 15 requires MIDENA_MFA_POLICY=all"
            )
        return self

    # ---------------------------------------------------------------------
    # Post-login redirect allowlist
    # ---------------------------------------------------------------------
    # Comma-separated list of hostnames that the UI is allowed to redirect to
    # after successful login when a `?next=` parameter is present.
    #
    # Security note:
    #   - Same-origin relative paths are always permitted.
    #   - Absolute URLs are only permitted when their hostname is in this list.
    #   - Leave empty to disallow all cross-origin redirects.
    login_redirect_allowed_hosts: str = Field(default="")

    # Public base URL: the origin for links in emails and for second-factor
    # ceremonies. It is never derived from a request, so without it no mail
    # carries a link.
    public_base_url: str = Field(default="")

    # ---------------------------------------------------------------------
    # Generic OpenID Connect provider
    # ---------------------------------------------------------------------
    oidc_sso_enabled: bool = Field(default=False)
    oidc_provider_label: str = Field(default="OpenID Connect")

    # Explicit endpoints are recommended and avoid discovery at runtime.
    oidc_discovery_url: str = Field(default="")
    oidc_authorization_endpoint: str = Field(default="")
    oidc_token_endpoint: str = Field(default="")
    oidc_jwks_uri: str = Field(default="")
    oidc_issuer: str = Field(default="")
    oidc_userinfo_endpoint: str = Field(default="")
    oidc_client_id: str = Field(default="")
    oidc_client_secret: str = Field(default="")
    oidc_scopes: str = Field(default="openid email profile")
    oidc_redirect_uri: str = Field(default="")
    oidc_end_session_endpoint: str = Field(default="")
    oidc_post_logout_redirect_uri: str = Field(default="")
    oidc_id_token_leeway_seconds: int = Field(default=60)
    # ID token signing algorithms accepted from the generic provider; the
    # token header cannot widen this list, and only asymmetric ones apply.
    oidc_allowed_algs: str = Field(default="RS256")
    oidc_auto_link_existing: bool = Field(default=True)
    oidc_allowed_email_domains: str = Field(default="")

    # Google OIDC. Defaults are suitable for consumer Google and any Google
    # Workspace domain; do not set a hosted-domain restriction unless you want
    # to intentionally limit access to specific domains.
    google_sso_enabled: bool = Field(default=False)
    google_provider_label: str = Field(default="Google")
    google_authorization_endpoint: str = Field(
        default="https://accounts.google.com/o/oauth2/v2/auth"
    )
    google_token_endpoint: str = Field(default="https://oauth2.googleapis.com/token")
    google_jwks_uri: str = Field(default="https://www.googleapis.com/oauth2/v3/certs")
    google_issuer: str = Field(
        default="https://accounts.google.com,accounts.google.com"
    )
    google_userinfo_endpoint: str = Field(
        default="https://openidconnect.googleapis.com/v1/userinfo"
    )
    google_client_id: str = Field(default="")
    google_client_secret: str = Field(default="")
    google_scopes: str = Field(default="openid email profile")
    google_redirect_uri: str = Field(default="")
    google_end_session_endpoint: str = Field(default="")
    google_post_logout_redirect_uri: str = Field(default="")
    google_auto_link_existing: bool = Field(default=True)
    google_allowed_email_domains: str = Field(default="")

    # GitHub OAuth. MIDENA uses /user for the stable numeric account id and
    # /user/emails to resolve a verified primary email when possible.
    github_sso_enabled: bool = Field(default=False)
    github_provider_label: str = Field(default="GitHub")
    github_authorization_endpoint: str = Field(
        default="https://github.com/login/oauth/authorize"
    )
    github_token_endpoint: str = Field(
        default="https://github.com/login/oauth/access_token"
    )
    github_user_endpoint: str = Field(default="https://api.github.com/user")
    github_emails_endpoint: str = Field(default="https://api.github.com/user/emails")
    github_issuer: str = Field(default="https://github.com/login/oauth")
    github_client_id: str = Field(default="")
    github_client_secret: str = Field(default="")
    github_scopes: str = Field(default="read:user user:email")
    github_redirect_uri: str = Field(default="")
    github_auto_link_existing: bool = Field(default=True)
    github_allowed_email_domains: str = Field(default="")

    # Optional trusted remote user (for Vouch / SSO proxy mode)
    trust_remote_user: bool = Field(default=False)
    remote_user_header_name: str = Field(default="REMOTE_USER")
    # The authenticating proxies whose identity header MIDENA accepts, as
    # comma-separated addresses or CIDRs. A separate list from
    # MIDENA_TRUSTED_PROXY_CIDRS: a hop trusted to forward client addresses
    # is not thereby trusted to name the signed-in account. Required while
    # MIDENA_TRUST_REMOTE_USER is on; there is no default.
    remote_user_trusted_cidrs: str = Field(default="")

    @field_validator("remote_user_trusted_cidrs")
    @classmethod
    def _validate_remote_user_proxies(cls, value: str) -> str:
        for entry in value.split(","):
            if entry.strip():
                ipaddress.ip_network(entry.strip(), strict=False)
        return value

    @model_validator(mode="after")
    def _validate_remote_user_trust(self) -> "Settings":
        if self.trust_remote_user and not self.remote_user_trusted_cidrs.strip(", "):
            raise ValueError(
                "MIDENA_TRUST_REMOTE_USER requires MIDENA_REMOTE_USER_TRUSTED_CIDRS: "
                "the addresses of the proxies that authenticate users"
            )
        return self

    # ---------------------------------------------------------------------
    # SMTP (account security and notification emails)
    # ---------------------------------------------------------------------
    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=587)
    smtp_username: str = Field(default="")
    smtp_password: str = Field(default="")
    smtp_use_tls: bool = Field(default=True)  # STARTTLS
    smtp_use_ssl: bool = Field(default=False)  # SMTPS (465)
    smtp_timeout_seconds: int = Field(default=20)
    smtp_from_email: str = Field(default="")
    smtp_from_name: str = Field(default="MIDENA")

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
