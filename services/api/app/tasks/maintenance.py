"""Housekeeping: expired and spent rows must not accumulate without bound.

Expired sign-in states, second-factor challenges and SSO address proofs
(mosp.services.housekeeping), expired diagram locks and audit rows past their
retention (mosp.services.audit_retention) are removed on a beat schedule, so
an attacker's floods or normal traffic cannot grow those tables forever.
Sessions, sign-in throttles and allowances live in Valkey and expire there.
"""

from __future__ import annotations

from celery.utils.log import get_task_logger
from mosp.core.datetime_utils import utc_now_naive
from mosp.services import audit_retention, housekeeping

from app.celery_app import celery_app
from app.db.models import DiagramLock
from app.db.session import SessionLocal

log = get_task_logger(__name__)


@celery_app.task(name="app.tasks.maintenance.sweep_expired_rows")
def sweep_expired_rows() -> dict:
    now = utc_now_naive()
    removed = housekeeping.remove_expired(now)
    with SessionLocal() as db:
        removed["diagram_locks"] = (
            db.query(DiagramLock)
            .filter(DiagramLock.expires_at <= now)
            .delete(synchronize_session=False)
        )
        db.commit()
    removed["audit_logs"], more = audit_retention.remove_expired(now)
    if more:
        # A large backlog is removed over the next runs, a bounded batch at a
        # time.
        log.info("Audit rows past retention remain; the next run continues")
    return removed
