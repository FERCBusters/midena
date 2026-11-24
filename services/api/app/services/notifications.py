"""MIDENA's transactional e-mail outbox.

Senders queue a row inside the transaction of the change it reports; the
worker sends it through MOSP's outbox delivery (mosp.services.outbox), as it
does MOSP's security notices: backoff on failure, each recipient in turn,
and no body kept once a message is sent or given up.
"""

from __future__ import annotations

import uuid
from typing import Any

from mosp.core.datetime_utils import utc_now_naive
from mosp.services import outbox
from mosp.services.mailer import send_email, smtp_configured
from sqlalchemy.orm import Session

from app.db.models import Notification


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
        next_attempt_at=utc_now_naive(),
    )
    db.add(row)
    return row


def deliver_pending(limit: int = 10) -> int:
    """Send waiting notices (mosp.services.outbox)."""
    from app.db.session import SessionLocal

    if not smtp_configured():
        return 0
    return outbox.deliver(
        Notification,
        limit=max(1, int(limit or 10)),
        sessions=SessionLocal,
        send=send_email,
        label="Notification",
    )


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
    from mosp.services.mailer import sender_name

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
