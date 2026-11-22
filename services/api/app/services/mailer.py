from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services import notifications as outbox


def smtp_configured() -> bool:
    return bool((settings.smtp_host or "").strip()) and bool(
        (settings.smtp_from_email or "").strip()
    )


def single_line(text: str | None) -> str:
    """Header text on one line.

    A message header refuses every character str.splitlines() breaks at (CR,
    LF, VT, FF, the separators FS, GS and RS, NEL, and the Unicode line and
    paragraph separators), and a refused subject fails the mail on every
    attempt, so a name that carries one is flattened here.
    """
    return " ".join(str(text or "").splitlines()) if text else ""


def send_email(*, to_email: str, subject: str, body: str) -> None:
    """Transport used by the notification worker; raises on failure.

    The rest of the application never sends directly: it queues a
    notification row (see app/services/notifications.py), so delivery is
    observable and retried out of band.
    """
    _deliver_email(to_email=to_email, subject=subject, body=body)


def queue_email(
    db: Session,
    *,
    user_id: int | None,
    recipient: str,
    subject: str,
    body: str,
) -> None:
    """Queue through the caller's transaction-aware outbox."""
    if not smtp_configured() or not (recipient or "").strip():
        return
    outbox.queue_email(
        db, user_id=user_id, recipient=recipient, subject=subject, body=body
    )


def _deliver_email(*, to_email: str, subject: str, body: str) -> None:
    if not smtp_configured():
        return

    host = (settings.smtp_host or "").strip()
    port = int(getattr(settings, "smtp_port", 587) or 587)
    user = (settings.smtp_username or "").strip() or None
    pwd = (settings.smtp_password or "").strip() or None
    use_tls = bool(getattr(settings, "smtp_use_tls", True))
    use_ssl = bool(getattr(settings, "smtp_use_ssl", False))
    timeout = int(getattr(settings, "smtp_timeout_seconds", 20) or 20)

    from_email = (settings.smtp_from_email or "").strip()
    from_name = (settings.smtp_from_name or "MIDENA").strip() or "MIDENA"

    to_addr = (to_email or "").strip()
    if not to_addr:
        return

    msg = EmailMessage()
    # Subject text often carries user-controlled names; strip CR/LF so the
    # header line stays one line whatever a display name contains.
    msg["Subject"] = single_line(subject)
    msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
    msg["To"] = to_addr
    msg.set_content(body)

    context = ssl.create_default_context()
    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=timeout, context=context) as s:
            if user and pwd:
                s.login(user, pwd)
            s.send_message(msg)
        return

    with smtplib.SMTP(host, port, timeout=timeout) as s:
        s.ehlo()
        if use_tls:
            s.starttls(context=context)
            s.ehlo()
        if user and pwd:
            s.login(user, pwd)
        s.send_message(msg)


def send_diagram_share_email(
    *,
    db: Session,
    user_id: int | None,
    to_email: str,
    diagram_name: str,
    shared_by: str,
    diagram_url: str | None,
    role: str,
) -> None:
    """Queue a diagram sharing notice in the caller's transaction.

    The link exists only when MIDENA_PUBLIC_BASE_URL is set: it is never
    derived from a request's Host header, which a client chooses.
    """
    from_name = (settings.smtp_from_name or "MIDENA").strip() or "MIDENA"
    body = (
        "Hello,\n\n"
        f"{single_line(shared_by)} shared the MIDENA diagram "
        f"'{single_line(diagram_name)}' with you as a {role}.\n\n"
    )
    if diagram_url:
        body += f"Open the diagram: {diagram_url}\n\n"
    body += "You are receiving this because you have an account on this MIDENA.\n"
    queue_email(
        db,
        user_id=user_id,
        recipient=to_email,
        subject=f"{from_name}: a diagram was shared with you",
        body=body,
    )
