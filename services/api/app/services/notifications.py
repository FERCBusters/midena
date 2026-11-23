"""Transactional e-mail outbox (KEEN's design, ported).

Senders queue a row inside their own transaction; the worker drains pending
rows with exponential backoff and records the outcome on the row, so a broken
SMTP configuration is visible rather than silently swallowed. A sent
message's body is cleared afterwards: verification links are one-time
secrets and never linger in the database.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from myf.core.datetime_utils import utc_now_naive
from myf.services.mailer import send_email, smtp_configured
from sqlalchemy.orm import Session

from app.db.models import Notification

log = logging.getLogger(__name__)

_MAX_ATTEMPTS = 8
# Bodies of delivered or permanently failed rows never outlive a month.
_RETENTION_DAYS = 30


def _now() -> datetime:
    return utc_now_naive()


def queue_email(
    db: Session,
    *,
    user_id: uuid.UUID | None,
    recipient: str,
    subject: str,
    body: str,
) -> Notification | None:
    """Queue an e-mail in the caller's transaction; the worker sends it."""
    if not smtp_configured():
        return None
    recipient = (recipient or "").strip()
    if not recipient:
        return None
    row = Notification(
        user_id=user_id,
        recipient=recipient,
        subject=(subject or "").strip()[:500],
        body=str(body or ""),
        status="pending",
        next_attempt_at=_now(),
    )
    db.add(row)
    return row


def deliver_pending(limit: int = 10) -> int:
    """Drain the outbox: one SMTP send per pending row, backoff on failure."""

    from app.db.session import SessionLocal

    if not smtp_configured():
        return 0
    sent = 0
    for _ in range(max(1, int(limit or 10))):
        with SessionLocal() as db:
            row = (
                db.query(Notification)
                .filter(
                    Notification.status == "pending",
                    Notification.next_attempt_at <= _now(),
                )
                .order_by(Notification.created_at)
                .with_for_update(skip_locked=True)
                .first()
            )
            if row is None:
                break
            row.attempts += 1
            try:
                send_email(to_email=row.recipient, subject=row.subject, body=row.body)
            except Exception as error:
                # Exception strings can carry SMTP credentials or addresses;
                # retain only the exception class name.
                row.last_error = type(error).__name__[:100]
                row.status = "failed" if row.attempts >= _MAX_ATTEMPTS else "pending"
                if row.status == "failed":
                    # Nothing will send it now; a link in it is not kept.
                    row.body = ""
                row.next_attempt_at = _now() + timedelta(
                    seconds=min(3600, 60 * 2 ** (row.attempts - 1))
                )
                log.warning(
                    "Notification %s delivery failed; attempt=%s status=%s",
                    row.id,
                    row.attempts,
                    row.status,
                )
            else:
                row.status = "sent"
                row.sent_at = _now()
                row.last_error = None
                row.body = ""
                sent += 1
            db.commit()
        if sent >= max(1, int(limit or 10)):
            break
    # Bound retention of spent rows regardless of outcome.
    with SessionLocal() as db:
        db.query(Notification).filter(
            Notification.status.in_(["sent", "failed"]),
            Notification.created_at < _now() - timedelta(days=_RETENTION_DAYS),
        ).delete(synchronize_session=False)
        db.commit()
    return sent


def notification_snapshot(
    db: Session, *, user_id: uuid.UUID, limit: int = 20
) -> list[dict[str, Any]]:
    """The user's own outbox history: what was mailed to them and when.

    Bodies are never returned; a queued row that has already been sent
    carries no body by design, and rows still pending keep their body only
    server-side.
    """
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .limit(max(1, int(limit or 20)))
        .all()
    )
    return [
        {
            "id": str(row.id),
            "subject": row.subject,
            "recipient": row.recipient,
            "status": row.status,
            "attempts": row.attempts,
            "last_error": row.last_error,
            "created_at": row.created_at,
            "sent_at": row.sent_at,
        }
        for row in rows
    ]


def single_line(text: str | None) -> str:
    """Header text on one line.

    A message header refuses every character str.splitlines() breaks at (CR,
    LF, VT, FF, the separators FS, GS and RS, NEL, and the Unicode line and
    paragraph separators), and a refused subject fails the mail on every
    attempt, so a name that carries one is flattened here.
    """
    return " ".join(str(text or "").splitlines()) if text else ""


def send_diagram_share_email(
    *,
    db: Session,
    user_id: uuid.UUID | None,
    to_email: str,
    diagram_name: str,
    shared_by: str,
    diagram_url: str | None,
    role: str,
) -> None:
    """Queue a diagram sharing notice in the caller's transaction.

    The link comes from MIDENA_PUBLIC_BASE_URL, never from a request's Host
    header, which a client chooses.
    """
    from myf.services.mailer import sender_name

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
        subject=f"{sender_name()}: a diagram was shared with you",
        body=body,
    )
