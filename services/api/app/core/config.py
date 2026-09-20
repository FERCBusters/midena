from __future__ import annotations

from pydantic import Field
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

    session_cookie_name: str = Field(default="midena_session")
    session_ttl_seconds: int = Field(default=60 * 60 * 12)
    cookie_secure: bool = Field(default=True)
    cookie_samesite: str = Field(default="lax")
    cookie_domain: str = Field(default="")

    csrf_cookie_name: str = Field(default="midena_csrf")
    csrf_header_name: str = Field(default="X-CSRF-Token")
    csrf_cookie_samesite: str = Field(default="strict")
    trust_proxy_headers: bool = Field(default=False)
    local_auth_enabled: bool = Field(default=True)
    login_redirect_allowed_hosts: str = Field(default="")
    public_base_url: str = Field(default="")

    # Optional first-run admin bootstrap. When username and password are set,
    # startup creates the user if it does not already exist. Existing users are
    # never overwritten.
    bootstrap_admin_username: str = Field(default="")
    bootstrap_admin_password: str = Field(default="")
    bootstrap_admin_email: str = Field(default="")

    # Generic OpenID Connect provider
    oidc_sso_enabled: bool = Field(default=False)
    oidc_provider_label: str = Field(default="OpenID Connect")
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
    oidc_auto_provision: bool = Field(default=False)
    oidc_auto_provision_role: str = Field(default="viewer")
    oidc_auto_link_existing: bool = Field(default=True)
    oidc_allowed_email_domains: str = Field(default="")
    oidc_username_claims: str = Field(default="preferred_username,email")

    # Google OIDC
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
    google_auto_provision: bool = Field(default=False)
    google_auto_provision_role: str = Field(default="viewer")
    google_auto_link_existing: bool = Field(default=True)
    google_allowed_email_domains: str = Field(default="")
    google_username_claims: str = Field(default="email")

    # GitHub OAuth
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
    github_auto_provision: bool = Field(default=False)
    github_auto_provision_role: str = Field(default="viewer")
    github_auto_link_existing: bool = Field(default=True)
    github_allowed_email_domains: str = Field(default="")

    trust_remote_user: bool = Field(default=False)
    remote_user_header_name: str = Field(default="REMOTE_USER")
    remote_user_auto_provision: bool = Field(default=False)
    remote_user_auto_provision_role: str = Field(default="viewer")

    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=587)
    smtp_username: str = Field(default="")
    smtp_password: str = Field(default="")
    smtp_use_tls: bool = Field(default=True)
    smtp_use_ssl: bool = Field(default=False)
    smtp_timeout_seconds: int = Field(default=20)
    smtp_from_email: str = Field(default="")
    smtp_from_name: str = Field(default="MIDENA")
    password_reset_token_ttl_minutes: int = Field(default=60)

    # Optional Google Drive export using a Workspace service account.
    google_drive_service_account_json: str = Field(default="")
    google_drive_service_account_file: str = Field(default="")
    google_drive_delegated_user: str = Field(default="")
    google_drive_default_folder_id: str = Field(default="")

    # Optional OpenAI-compatible diagram generation. The API key stays server-side;
    # the browser only talks to MIDENA. Set ai_enabled=false to force-disable it.
    ai_enabled: bool = Field(default=True)
    ai_api_base_url: str = Field(default="https://api.regolo.ai/v1")
    ai_api_key: str = Field(default="")
    ai_model: str = Field(default="")
    ai_temperature: float = Field(default=0.2)
    ai_max_tokens: int = Field(default=2500)
    ai_timeout_seconds: int = Field(default=45)
    ai_rate_limit_attempts: int = Field(default=30)
    ai_rate_limit_window_seconds: int = Field(default=3600)

    celery_broker_url: str = Field(default="")
    celery_result_backend: str = Field(default="")
    celery_timezone: str = Field(default="UTC")


settings = Settings()
