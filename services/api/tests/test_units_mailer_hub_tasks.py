"""MIDENA's mail outbox and maintenance sweep (no network).

The transport, redaction and notification hub are mosp's, and mosp's suite
covers them.
"""

from __future__ import annotations

from datetime import timedelta

from app.db.models import AuditLog, DiagramLock, Notification
from app.db.session import SessionLocal
from app.services import notifications
from app.tasks.maintenance import sweep_expired_rows
from mosp.core.datetime_utils import utc_now_naive

from tests.conftest import auth_client
from tests.conftest import db as db_fixture  # noqa: F401
from tests.support import make_diagram


def _mail_configured(monkeypatch):
    monkeypatch.setattr(notifications, "smtp_configured", lambda: True)


def test_a_share_notice_is_queued_on_one_line(monkeypatch, db):
    """The share notice is queued in the caller's transaction; sending it is
    the worker's job (deliver_pending)."""
    _mail_configured(monkeypatch)
    with SessionLocal() as s:
        notifications.send_diagram_share_email(
            db=s,
            user_id=None,
            to_email="u4@example.com",
            diagram_name="Flow\r\nBcc: x@evil",
            shared_by="owner",
            diagram_url=None,
            role="viewer",
        )
        s.commit()
        rows = s.query(Notification).all()
        assert len(rows) == 1
        assert rows[0].subject == "MIDENA: a diagram was shared with you"
        assert "Flow Bcc: x@evil" in rows[0].body
        assert rows[0].status == "pending"


def test_nothing_is_queued_without_mail_settings(monkeypatch, db):
    monkeypatch.setattr(notifications, "smtp_configured", lambda: False)
    with SessionLocal() as s:
        assert (
            notifications.queue_email(
                s, user_id=None, recipient="to@example.com", subject="s", body="b"
            )
            is None
        )
        s.commit()
        assert s.query(Notification).count() == 0
    assert notifications.deliver_pending(limit=2) == 0


def test_outbox_delivers_pending_rows_and_records_failure(monkeypatch, db):
    _mail_configured(monkeypatch)
    with SessionLocal() as s:
        row = notifications.queue_email(
            s, user_id=None, recipient="to@example.com", subject="s", body="b"
        )
        s.commit()
        assert row is not None and row.status == "pending"
        row_id = row.id

    deliveries = []

    def fake_send_email(*, to_email, subject, body):
        deliveries.append(to_email)

    monkeypatch.setattr(notifications, "send_email", fake_send_email)
    assert notifications.deliver_pending(limit=2) == 1
    assert deliveries == ["to@example.com"]
    with SessionLocal() as s:
        spent = s.get(Notification, row_id)
        assert spent.status == "sent"
        assert spent.body == ""
        assert spent.sent_at is not None

    # A failing transport keeps the row pending with a backoff stamp (only the
    # exception class is recorded).
    with SessionLocal() as s:
        failure = notifications.queue_email(
            s, user_id=None, recipient="fail@example.com", subject="f", body="b"
        )
        s.commit()
        failure_id = failure.id

    def broken_send(*, to_email, subject, body):
        raise OSError("no network here")

    monkeypatch.setattr(notifications, "send_email", broken_send)
    assert notifications.deliver_pending(limit=2) == 0
    with SessionLocal() as s:
        failed_row = s.get(Notification, failure_id)
        assert failed_row.status == "pending"
        assert failed_row.attempts == 1
        assert failed_row.last_error == "OSError"
        assert failed_row.next_attempt_at > utc_now_naive()


def test_sweep_removes_expired_rows(client):
    owner, user = auth_client(role="contributor")
    diagram = make_diagram(owner)
    now = utc_now_naive()
    with SessionLocal() as s:
        s.add(
            DiagramLock(
                diagram_id=diagram["id"],
                user_id=user.id,
                expires_at=now - timedelta(seconds=1),
            )
        )
        s.add(
            AuditLog(
                ts=now - timedelta(days=400),
                method="GET",
                path="/v1/x",
                status_code=200,
                duration_ms=1,
            )
        )
        s.commit()
    result = sweep_expired_rows.run()
    assert (result["diagram_locks"], result["audit_logs"]) == (1, 1)
    with SessionLocal() as s:
        assert s.query(DiagramLock).count() == 0
        # The sign-in that made the owner's session is recent and stays.
        assert all(row.ts > now - timedelta(days=1) for row in s.query(AuditLog))
