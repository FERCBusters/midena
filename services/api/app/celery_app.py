from __future__ import annotations

from celery import Celery

from app.core.config import settings


def _broker_url() -> str:
    explicit = str(getattr(settings, "celery_broker_url", "") or "").strip()
    return explicit or "redis://redis:6379/0"


def _result_backend() -> str:
    explicit = str(getattr(settings, "celery_result_backend", "") or "").strip()
    return explicit or "redis://redis:6379/1"


celery_app = Celery(
    "midena", broker=_broker_url(), backend=_result_backend(), include=[]
)
celery_app.conf.update(
    timezone=str(getattr(settings, "celery_timezone", "UTC") or "UTC"),
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    worker_prefetch_multiplier=1,
    task_acks_late=False,
)
