"""Mailer, redaction, hub, tasks and maintenance sweeps (no network)."""

from __future__ import annotations

from datetime import timedelta

from app.core.config import settings
from app.core.datetime_utils import utc_now_naive

from tests.conftest import db as db_fixture  # noqa: F401
from tests.conftest import make_user

# ----------------------------------------------------------------- mailer --


class _FakeSMTP:
    def __init__(self, *a, **kw):
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo(self):
        pass

    def starttls(self, context=None):
        pass

    def login(self, u, p):
        pass

    def send_message(self, msg):
        self.sent.append(msg)


def _capture(monkeypatch, *, use_ssl=False):
    from app.services import mailer

    fake = _FakeSMTP()
    if use_ssl:
        monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", lambda *a, **kw: fake)
    else:
        monkeypatch.setattr(mailer.smtplib, "SMTP", lambda *a, **kw: fake)
    saved = (
        settings.smtp_host,
        settings.smtp_port,
        settings.smtp_from_email,
        settings.smtp_from_name,
    )
    settings.smtp_host = "smtp.example.com"
    settings.smtp_port = 587
    settings.smtp_from_email = "noreply@example.com"
    settings.smtp_from_name = "MIDENA"
    return fake, saved


def test_subject_newlines_are_stripped(monkeypatch):
    from app.services import mailer

    fake, saved = _capture(monkeypatch)
    try:
        mailer.send_email(
            to_email="a@example.com",
            subject="line one\nline two\rline three",
            body="body",
        )
        msg = fake.sent[0]
        subject_text = str(msg["Subject"])
        assert "\n" not in subject_text and "\r" not in subject_text
    finally:
        (
            settings.smtp_host,
            settings.smtp_port,
            settings.smtp_from_email,
            settings.smtp_from_name,
        ) = (
            saved[0],
            saved[1],
            saved[2],
            saved[3],
        )


def test_mailer_skips_without_configuration(monkeypatch):
    from app.services import mailer

    saved = (settings.smtp_host, settings.smtp_from_email)
    settings.smtp_host = ""
    settings.smtp_from_email = ""
    try:
        mailer.send_email(to_email="a@example.com", subject="s", body="b")
    finally:
        settings.smtp_host, settings.smtp_from_email = saved


def test_all_mailer_helpers_queue_into_the_outbox(monkeypatch, db):
    """Every mailer composer now queues an outbox row in the caller's
    transaction; the transport stays the worker's job (deliver_pending)."""
    from app.db.models import Notification
    from app.db.session import SessionLocal
    from app.services import mailer

    saved = (
        settings.smtp_host,
        settings.smtp_port,
        settings.smtp_from_email,
        settings.smtp_from_name,
    )
    settings.smtp_host = "smtp.example.com"
    settings.smtp_port = 587
    settings.smtp_from_email = "noreply@example.com"
    settings.smtp_from_name = "MIDENA"
    try:
        with SessionLocal() as s:
            mailer.send_diagram_share_email(
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

    finally:
        (
            settings.smtp_host,
            settings.smtp_port,
            settings.smtp_from_email,
            settings.smtp_from_name,
        ) = saved


def test_outbox_delivers_pending_rows_and_records_failure(monkeypatch, db):

    from app.db.models import Notification
    from app.db.session import SessionLocal
    from app.services import notifications

    saved = (settings.smtp_host, settings.smtp_from_email)
    settings.smtp_host = "smtp.example.com"
    settings.smtp_from_email = "noreply@example.com"
    try:
        with SessionLocal() as s:
            row = notifications.queue_email(
                s, user_id=None, recipient="to@example.com", subject="s", body="b"
            )
            s.commit()
            assert row is not None and row.status == "pending"

            deliveries = []

            def fake_send_email(*, to_email, subject, body):
                deliveries.append(to_email)

            monkeypatch.setattr("app.services.mailer.send_email", fake_send_email)
            row_id = row.id
            assert notifications.deliver_pending(limit=2) == 1
            with SessionLocal() as s2:
                spent = s2.get(Notification, row_id)
                assert spent.status == "sent"
                assert spent.body == ""
                assert spent.sent_at is not None

            # A failing transport keeps the row pending with a backoff stamp
            # (only the exception class is recorded).
            with SessionLocal() as s3:
                failure = notifications.queue_email(
                    s3,
                    user_id=None,
                    recipient="fail@example.com",
                    subject="f",
                    body="b",
                )
                s3.commit()
                failure_id = failure.id

            def broken_send(*, to_email, subject, body):
                raise OSError("no network here")

            monkeypatch.setattr("app.services.mailer.send_email", broken_send)
            assert notifications.deliver_pending(limit=2) == 0
            with SessionLocal() as s4:
                failed_row = s4.get(Notification, failure_id)
                assert failed_row.status == "pending"
                assert failed_row.attempts == 1
                assert failed_row.last_error == "OSError"
                assert failed_row.next_attempt_at > utc_now_naive()
    finally:
        settings.smtp_host, settings.smtp_from_email = saved


def test_redact_query_string_hides_sensitive_values():
    from app.security.redaction import redact_query_string

    out = redact_query_string("state=abc&csrf=TOKEN&q=1")
    assert "TOKEN" not in out
    assert "abc=1" not in out or "q=1" in out


# -------------------------------------------------------------------- hub --


def test_hub_connect_capacity_and_send():
    import asyncio

    from app.db.models import User  # noqa: F401

    _run = asyncio.run
    _run(_hub_scenarios())


async def _hub_scenarios():
    from app.realtime.notifications import NotificationHub

    class FakeWS:  # noqa: F811
        def __init__(self):
            self.frames = []
            self.accepted = False
            self.closed = None

        async def accept(self):
            self.accepted = True

        async def send_json(self, payload):
            self.frames.append(payload)

        async def close(self, code=None):
            self.closed = code

    h = NotificationHub()
    ws1, ws2 = FakeWS(), FakeWS()
    assert await h.connect_if_capacity(1, ws1, 1) is True
    assert await h.connect_if_capacity(1, ws2, 1) is False
    assert await h.connect_if_capacity(1, ws2, 1) is False and ws2.closed == 4429
    await h.send_to_user(1, {"a": 1})
    assert ws1.frames == [{"a": 1}]
    await h.disconnect(1, ws1)
    await h.send_to_user(1, {"a": 2})
    await h.broadcast(set(), {"x": 1})


# ------------------------------------------------------- tasks / sweeper --


def test_sweep_removes_expired_rows(db):
    from app.db.models import (
        AuditLog,
        OidcLoginState,
        RateLimitEntry,
        SsoEmailChallenge,
    )
    from app.tasks.maintenance import sweep_expired_rows

    past = utc_now_naive() - timedelta(days=1)
    old_audit = utc_now_naive() - timedelta(days=400)
    owner = make_user("SweepOwner", "Test-passphrase-1!", role="viewer")
    db.add(OidcLoginState(state="s", nonce="n", code_verifier="v", expires_at=past))
    db.add(
        SsoEmailChallenge(
            token_hash="1" * 64,
            user_id=int(owner.id),
            email="x@y.test",
            expires_at=past,
            mfa_version=0,
            password_digest="2" * 64,
        )
    )
    db.add(
        RateLimitEntry(identifier="old", timestamp=utc_now_naive() - timedelta(hours=5))
    )
    db.add(
        AuditLog(
            ts=old_audit,
            method="GET",
            path="/v1/x",
            status_code=200,
            duration_ms=1,
        )
    )
    db.commit()
    result = sweep_expired_rows()
    assert result["ok"] is True
    assert db.query(OidcLoginState).count() == 0
    assert db.query(SsoEmailChallenge).count() == 0
    assert db.query(RateLimitEntry).count() == 0
    assert db.query(AuditLog).count() == 0
