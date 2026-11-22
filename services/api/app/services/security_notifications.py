"""Security notices to an account's owner, ported from KEEN.

Each notice is queued through the e-mail outbox in the caller's transaction,
so it commits with the change it reports. Every completed sign-in also
records its client address against the account; the first sign-in from an
address not seen before sends a notice.
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.datetime_utils import utc_now_naive
from app.db.models import User, UserLoginIP
from app.services.mailer import queue_email, smtp_configured
from app.services.notification_recipients import notification_email_for_user

# KEEN's events and wording, naming MIDENA. KEEN's MCP connection has no
# MIDENA counterpart.
TITLES = {
    "sso-email-added": "An SSO email address was verified for your MIDENA account",
    "sso-email-removed": "An SSO email address was removed from your MIDENA account",
    "login-ip": "Sign-in from an unfamiliar IP address",
    "password-changed": "Your MIDENA password was changed",
    "password-reset": "Your MIDENA password was reset by an administrator",
    "factor-enrolled": "An authenticator was added to your MIDENA account",
    "factor-removed": "An authenticator was removed from your MIDENA account",
    "recovery-codes-regenerated": "Your MIDENA recovery codes were replaced",
    "operator-reset": "Your MIDENA two-factor authentication was reset by an operator",
    "verified-recovery": "A recovery code was used for your MIDENA account",
    "verification-ended": (
        "MIDENA ended a two-factor verification after repeated incorrect codes"
    ),
}

UNFAMILIAR_ADDRESS = TITLES["login-ip"]


def _event_detail(event: str) -> str:
    """The paragraph a notice adds about its own event, if any."""
    from app.security.mfa import CODE_ATTEMPTS

    if event == "login-ip":
        return (
            "This address has not previously been recorded for a successful "
            "sign-in to this account. A VPN, mobile connection or changing ISP "
            "address can cause this alert."
        )
    if event == "verification-ended":
        return (
            f"Your password was accepted and {CODE_ATTEMPTS} incorrect "
            "authenticator or recovery codes were entered within an hour, so "
            "MIDENA accepts no code for this account for the next hour; a "
            "security key still signs you in. If this was not you, someone may "
            "know your password: change it and contact your MIDENA administrator."
        )
    if event == "verified-recovery":
        return (
            "Each recovery code works once. Replace your recovery codes under "
            "Account when few remain."
        )
    return ""


def enqueue(db: Session, user: User, event: str, *, ip: str | None) -> bool:
    """Queue a security notice to the account's e-mail, in the caller's
    transaction. Returns True when a notice was queued."""

    title = TITLES[event]
    to = notification_email_for_user(db, user=user)
    if not smtp_configured() or not to:
        return False
    from_name = (settings.smtp_from_name or "MIDENA").strip() or "MIDENA"
    installation = (settings.public_base_url or "").strip().rstrip("/")
    lines = [f"{title}.", "", f"Account: {user.username}"]
    if installation:
        lines.append(f"MIDENA installation: {installation}")
    lines += [
        f"Time (UTC): {utc_now_naive().isoformat(timespec='seconds')}Z",
        f"IP address: {ip or 'Unavailable (operator action or unknown address)'}",
        "",
    ]
    detail = _event_detail(event)
    if detail:
        lines += [detail, ""]
    lines.append(
        "If this was you, no action is needed. If you do not recognise this "
        "activity, open your known MIDENA address directly and contact your "
        "MIDENA administrator. Review your password and authenticators."
    )
    queue_email(
        db,
        user_id=user.id,
        recipient=to,
        subject=f"{from_name} security: {title}",
        body="\n".join(lines) + "\n",
    )
    return True


def record_login(db: Session, user: User, *, ip: str | None) -> bool:
    """Record a completed sign-in's address in the caller's transaction.

    Returns True when a notice was queued: the address is new for the account
    and mail can be sent. The account/address key is unique, so parallel
    sign-ins from one new address queue a single notice.
    """

    address = (ip or "").strip()
    if not address:
        return False
    created = db.execute(
        insert(UserLoginIP)
        .values(user_id=user.id, address=address, first_seen_at=utc_now_naive())
        .on_conflict_do_nothing()
        .returning(UserLoginIP.address)
    ).scalar_one_or_none()
    if created is None:
        return False
    return enqueue(db, user, "login-ip", ip=address)
