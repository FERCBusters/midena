"""Celery contract: every scheduled task must be registered with the worker.

A beat schedule entry whose task module is missing from ``include`` is
silently discarded by the worker ("Received unregistered task") and the
housekeeping it performs never runs. This test pins every scheduled task
name to the registry the worker builds after importing the include list.
"""

from __future__ import annotations

import pytest


def test_beat_schedule_tasks_are_registered() -> None:
    celery_app = pytest.importorskip("app.celery_app").celery_app
    # Importing the include modules is what a worker does at startup; go
    # through the configured list rather than importing by hand, so a new
    # task module that forgets to join the include list is caught here.
    for module in celery_app.conf.include:
        pytest.importorskip(module)

    registered = set(celery_app.tasks.keys())
    scheduled = {entry["task"] for entry in celery_app.conf.beat_schedule.values()}
    missing = sorted(scheduled - registered)
    assert not missing, (
        "beat schedules tasks the worker would discard as unregistered; "
        f"missing from the app registry: {missing}"
    )


def test_requests_never_wait_long_on_the_broker():
    # Nothing reads task results, so a hand-off touches only the broker, and
    # for at most a few seconds; queued work waits for the beat dispatchers.
    from app.celery_app import celery_app

    assert celery_app.conf.task_ignore_result is True
    assert celery_app.conf.broker_connection_timeout <= 3


def test_no_task_runs_without_an_end():
    """Every task has a hard limit and, a minute before it, a soft one the
    task can answer."""
    from app.celery_app import celery_app
    from app.core.config import settings

    conf = celery_app.conf
    assert conf.task_time_limit == settings.task_time_limit_seconds == 900
    assert conf.task_soft_time_limit == 840
    celery_app.loader.import_default_modules()
    tasks = {
        name: task
        for name, task in celery_app.tasks.items()
        if name.startswith("app.tasks.")
    }
    assert set(tasks) == {
        "app.tasks.maintenance.sweep_expired_rows",
        "app.tasks.notifications.deliver_notifications",
    }
    for name, task in tasks.items():
        hard = task.time_limit or conf.task_time_limit
        soft = task.soft_time_limit or conf.task_soft_time_limit
        assert hard == 900, name
        assert soft == hard - 60, name
