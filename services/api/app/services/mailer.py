from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.core.config import settings


def send_password_reset_email(
    *, to_email: str, reset_url: str, username: str | None = None
) -> None:
    """Send a local-auth password reset email.

    SSO-first deployments can leave SMTP unset; in that case the auth endpoint
    returns a generic success response and logs no secret token.
    """
    if not settings.smtp_host or not settings.smtp_from_email:
        return
    from_name = (settings.smtp_from_name or "MIDENA").strip() or "MIDENA"
    subject = f"{from_name}: password reset"
    greeting = f"Hello {username}," if username else "Hello,"
    body = (
        f"{greeting}\n\n"
        "A password reset was requested for your MIDENA account.\n\n"
        f"Reset your password: {reset_url}\n\n"
        "If you did not request this, ignore this message.\n"
    )
    _send_email(to_email=to_email, subject=subject, body=body)


def send_diagram_share_email(
    *,
    to_email: str,
    diagram_name: str,
    shared_by: str,
    diagram_url: str,
    role: str = "viewer",
) -> None:
    """Send a diagram sharing notification if SMTP is configured."""
    if not settings.smtp_host or not settings.smtp_from_email:
        return
    from_name = (settings.smtp_from_name or "MIDENA").strip() or "MIDENA"
    subject = f"{from_name}: diagram shared with you"
    body = (
        f"Hello,\n\n"
        f"{shared_by} shared the MIDENA diagram '{diagram_name}' with you "
        f"as a {role}.\n\n"
        f"Open the diagram: {diagram_url}\n\n"
        "You are receiving this because you have access to this MIDENA instance.\n"
    )
    _send_email(to_email=to_email, subject=subject, body=body)


def _send_email(*, to_email: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    from_name = (settings.smtp_from_name or "MIDENA").strip() or "MIDENA"
    from_email = settings.smtp_from_email.strip()
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    if settings.smtp_use_ssl:
        smtp = smtplib.SMTP_SSL(
            settings.smtp_host,
            settings.smtp_port,
            timeout=settings.smtp_timeout_seconds,
        )
    else:
        smtp = smtplib.SMTP(
            settings.smtp_host,
            settings.smtp_port,
            timeout=settings.smtp_timeout_seconds,
        )
    with smtp:
        if settings.smtp_use_tls and not settings.smtp_use_ssl:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(msg)
