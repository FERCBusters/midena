from __future__ import annotations

from datetime import timedelta

from celery import Celery

from app.core.config import settings


def _broker_url() -> str:
    # Compose sets MIDENA_CELERY_BROKER_URL with the Valkey password; this
    # default only serves a local broker that needs none.
    return settings.celery_broker_url.strip() or "redis://redis:6379/0"


celery_app = Celery(
    "midena",
    broker=_broker_url(),
    include=[
        "app.tasks.maintenance",
        "app.tasks.notifications",
    ],
)

celery_app.conf.update(
    timezone=settings.celery_timezone or "UTC",
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    # JSON only: no task argument is ever unpickled.
    accept_content=["json"],
    worker_prefetch_multiplier=1,
    task_acks_late=False,
    # Requests hand work to the broker and return; nothing reads a task's
    # result, so none is stored.
    task_ignore_result=True,
    # A hand-off from a request waits at most this long for the broker; the
    # work stays queued in the database for the beat schedule.
    broker_connection_timeout=3,
    # No task runs without an end. At the soft limit the task is told to
    # stop; at the hard limit its process is replaced.
    task_soft_time_limit=max(1, settings.task_time_limit_seconds - 60),
    task_time_limit=settings.task_time_limit_seconds,
    beat_schedule={
        # Housekeeping: expired login states, SSO e-mail proofs, rate-limit
        # ledger rows and audit rows past retention never accumulate.
        "sweep-expired-rows": {
            "task": "app.tasks.maintenance.sweep_expired_rows",
            "schedule": timedelta(minutes=15),
        },
        # The e-mail outbox drains on a short beat so queued mail never waits
        # longer than minutes even when an interactive kick was missed.
        "deliver-notifications": {
            "task": "app.tasks.notifications.deliver_notifications",
            "schedule": timedelta(minutes=2),
        },
    },
)
