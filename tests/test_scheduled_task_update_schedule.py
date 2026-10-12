"""Keep existing schedule slots when an edit resends an unchanged phrase."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from api.managers.scheduled_task_manager import ScheduledTaskManager


@pytest.fixture
def schedule_clock(monkeypatch):
    clock = SimpleNamespace(now=datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc))

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.now.astimezone(tz) if tz else clock.now.replace(tzinfo=None)

    monkeypatch.setattr("schedule_parser.datetime", FrozenDatetime)
    return clock


@pytest.fixture(params=["cloud", "local"])
def manager(tmp_path, monkeypatch, request):
    manager = object.__new__(ScheduledTaskManager)
    manager.mode = request.param
    manager.db = SimpleNamespace(db_path=str(tmp_path / "scheduled.db"))
    manager._ensure_tables()
    monkeypatch.setattr(
        ScheduledTaskManager,
        "_resolve_workflow_id",
        staticmethod(lambda workflow_id, **_kwargs: workflow_id),
    )
    return manager


def _create_task(manager, *, when="every 30 minutes", task_type="workflow"):
    return manager.create_task(
        name="Test schedule",
        task_type=task_type,
        workflow_id="test_workflow" if task_type == "workflow" else None,
        query="What time is it?",
        when=when,
        timezone_name="America/Los_Angeles",
        max_retries=0,
    )


@pytest.mark.parametrize("task_type", ["workflow", "query"])
def test_notification_edit_keeps_interval_next_run(manager, schedule_clock, task_type):
    task_id = _create_task(manager, task_type=task_type)
    original = manager.get_task(task_id)
    assert original["next_run_at"] == "2026-10-12T12:30:00"
    schedule_clock.now += timedelta(minutes=10)
    metadata = {"notifications": {"alert_on_failure": True, "email_on_success": True}}

    assert manager.update_task(
        task_id,
        when="every 30 minutes",
        timezone="America/Los_Angeles",
        enabled=True,
        max_retries=0,
        metadata=metadata,
    )

    saved = manager.get_task(task_id)
    assert saved["next_run_at"] == original["next_run_at"]
    assert saved["schedule_type"] == original["schedule_type"]
    assert saved["schedule_expr"] == original["schedule_expr"]
    assert saved["task_payload"] == original["task_payload"]
    assert saved["max_retries"] == 0
    assert json.loads(saved["metadata"]) == metadata


def test_changed_phrase_recalculates_interval(manager, schedule_clock):
    task_id = _create_task(manager)
    schedule_clock.now += timedelta(minutes=10)

    assert manager.update_task(
        task_id, when="every 45 minutes", timezone="America/Los_Angeles"
    )

    saved = manager.get_task(task_id)
    assert saved["next_run_at"] == "2026-10-12T12:55:00"
    assert json.loads(saved["schedule_expr"]) == {"value": 45, "unit": "minutes"}
    payload = json.loads(saved["task_payload"])
    assert payload["when_original"] == "every 45 minutes"
    assert payload["schedule_summary"] == "Every 45 minutes"


def test_changed_timezone_with_same_phrase_recalculates_clock_schedule(manager, schedule_clock):
    task_id = _create_task(manager, when="every day at 9am")
    assert manager.get_task(task_id)["next_run_at"] == "2026-10-12T16:00:00"

    assert manager.update_task(task_id, when="every day at 9am", timezone="America/New_York")

    saved = manager.get_task(task_id)
    assert saved["timezone"] == "America/New_York"
    assert saved["next_run_at"] == "2026-10-12T13:00:00"


@pytest.mark.parametrize("completed", [False, True])
def test_reenable_run_once_interval_with_same_phrase_gets_next_run(manager, schedule_clock, completed):
    task_id = _create_task(manager)
    manager.cancel_task(task_id)
    manager.run_now(task_id)
    if completed:
        manager.release_lock_and_update(task_id, status="success", next_run_at=None)
    else:
        assert manager.get_task(task_id)["last_status"] == manager.RUN_ONCE_PENDING_STATUS
    schedule_clock.now += timedelta(minutes=10)

    assert manager.update_task(
        task_id, enabled=True, when="every 30 minutes", timezone="America/Los_Angeles"
    )

    saved = manager.get_task(task_id)
    assert saved["enabled"] == 1
    assert saved["next_run_at"] == "2026-10-12T12:40:00"
    assert saved["last_status"] != manager.RUN_ONCE_PENDING_STATUS


@pytest.mark.parametrize("elapsed_minutes", [10, 32, 40])
def test_reenable_normally_cancelled_interval_keeps_stored_slot(manager, schedule_clock, elapsed_minutes):
    task_id = _create_task(manager)
    stored_next_run = manager.get_task(task_id)["next_run_at"]
    manager.cancel_task(task_id)
    schedule_clock.now += timedelta(minutes=elapsed_minutes)

    assert manager.update_task(
        task_id, enabled=True, when="every 30 minutes", timezone="America/Los_Angeles"
    )

    saved = manager.get_task(task_id)
    assert saved["enabled"] == 1
    assert saved["next_run_at"] == stored_next_run


def test_unchanged_phrase_does_not_overwrite_scheduler_advance(manager, schedule_clock):
    task_id = _create_task(manager)
    original_get_task = manager.get_task

    def read_then_advance(task_id):
        snapshot = original_get_task(task_id)
        manager.release_lock_and_update(
            task_id, status="success", next_run_at="2026-10-12T13:00:00"
        )
        return snapshot

    with patch.object(manager, "get_task", side_effect=read_then_advance):
        assert manager.update_task(
            task_id,
            when="every 30 minutes",
            timezone="America/Los_Angeles",
            metadata={"notifications": {"alert_on_failure": True}},
        )

    assert manager.get_task(task_id)["next_run_at"] == "2026-10-12T13:00:00"


def test_completed_once_is_not_rescheduled_by_notification_edit(manager, schedule_clock):
    task_id = _create_task(manager, when="in 30 minutes")
    manager.cancel_task(task_id)
    manager.run_now(task_id)
    manager.release_lock_and_update(task_id, status="success", next_run_at=None)
    schedule_clock.now += timedelta(hours=1)

    assert manager.update_task(
        task_id,
        when="in 30 minutes",
        timezone="America/Los_Angeles",
        enabled=False,
        metadata={"notifications": {"alert_on_failure": True}},
    )

    saved = manager.get_task(task_id)
    assert saved["enabled"] == 0
    assert saved["next_run_at"] is None
