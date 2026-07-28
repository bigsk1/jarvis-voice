"""Regression coverage for run_now on cancelled scheduled tasks."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

from api.managers import scheduled_task_manager as scheduled_task_manager_module
from api.managers.scheduled_task_manager import ScheduledTaskManager


def _manager(tmp_path) -> ScheduledTaskManager:
    manager = object.__new__(ScheduledTaskManager)
    manager.mode = "cloud"
    manager.db = SimpleNamespace(db_path=str(tmp_path / "scheduled.db"))
    manager._ensure_tables()
    return manager


def _insert_daily_task(
    manager: ScheduledTaskManager,
    *,
    enabled: int = 1,
    last_status: str | None = None,
    next_run_at: str | None = "2099-01-01 12:00:00",
) -> int:
    conn = sqlite3.connect(manager.db.db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO scheduled_tasks (
            name, enabled, task_type, task_payload, schedule_type, schedule_expr,
            timezone, mode, next_run_at, last_status
        ) VALUES (?, ?, 'query', ?, 'daily', ?, 'America/Los_Angeles', 'cloud', ?, ?)
        """,
        (
            "Daily Status",
            enabled,
            json.dumps({"query": "status report"}),
            json.dumps({"hour": 9, "minute": 0}),
            next_run_at,
            last_status,
        ),
    )
    task_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return task_id


def test_run_now_on_cancelled_task_queues_without_re_enabling(tmp_path):
    manager = _manager(tmp_path)
    task_id = _insert_daily_task(manager)
    assert manager.cancel_task(task_id)

    assert manager.run_now(task_id)
    task = manager.get_task(task_id)
    assert task["enabled"] == 0
    assert task["last_status"] == ScheduledTaskManager.RUN_ONCE_PENDING_STATUS
    assert task["next_run_at"] is not None
    assert [item["id"] for item in manager.get_due_tasks()] == [task_id]


def test_run_now_on_enabled_task_keeps_schedule_active(tmp_path):
    manager = _manager(tmp_path)
    task_id = _insert_daily_task(manager)

    assert manager.run_now(task_id)
    task = manager.get_task(task_id)
    assert task["enabled"] == 1
    assert task["last_status"] != ScheduledTaskManager.RUN_ONCE_PENDING_STATUS
    assert task["next_run_at"] is not None


def test_run_once_completion_leaves_task_disabled_without_next_run(tmp_path):
    manager = _manager(tmp_path)
    task_id = _insert_daily_task(manager)
    manager.cancel_task(task_id)
    manager.run_now(task_id)
    task = manager.get_task(task_id)
    assert manager.is_manual_run_once(task)

    next_run = manager.resolve_followup_next_run(task, manual_run_once=True)
    assert next_run is None

    manager.release_lock_and_update(
        task_id,
        status="success",
        next_run_at=next_run,
    )
    final = manager.get_task(task_id)
    assert final["enabled"] == 0
    assert final["next_run_at"] is None
    assert final["last_status"] == "success"


def test_cancel_clears_pending_one_shot_run(tmp_path):
    manager = _manager(tmp_path)
    task_id = _insert_daily_task(manager)
    manager.cancel_task(task_id)
    manager.run_now(task_id)
    assert manager.get_task(task_id)["last_status"] == ScheduledTaskManager.RUN_ONCE_PENDING_STATUS

    assert manager.cancel_task(task_id)
    task = manager.get_task(task_id)
    assert task["enabled"] == 0
    assert task["last_status"] == "cancelled"
    assert task["next_run_at"] is None
    assert manager.get_due_tasks() == []


def test_re_enable_after_run_once_recalculates_next_run(tmp_path):
    manager = _manager(tmp_path)
    task_id = _insert_daily_task(manager)
    manager.cancel_task(task_id)
    manager.run_now(task_id)
    manager.release_lock_and_update(task_id, status="success", next_run_at=None)

    assert manager.update_task(task_id, enabled=True)
    task = manager.get_task(task_id)
    assert task["enabled"] == 1
    assert task["next_run_at"] is not None
    assert task["last_status"] == "success"


def test_skip_missed_occurrences_without_replaying_or_touching_other_mode(
    tmp_path,
    monkeypatch,
):
    manager = _manager(tmp_path)
    once_id = _insert_daily_task(manager, next_run_at="2026-07-28T14:00:00")
    recurring_id = _insert_daily_task(manager, next_run_at="2026-07-28T15:00:00")
    recent_id = _insert_daily_task(manager, next_run_at="2026-07-28T15:57:00")
    manual_id = _insert_daily_task(
        manager,
        enabled=0,
        last_status=ScheduledTaskManager.RUN_ONCE_PENDING_STATUS,
        next_run_at="2026-07-28T14:00:00",
    )

    conn = sqlite3.connect(manager.db.db_path)
    conn.execute(
        "UPDATE scheduled_tasks SET schedule_type = 'once' WHERE id = ?",
        (once_id,),
    )
    conn.execute(
        """
        INSERT INTO scheduled_tasks (
            name, enabled, task_type, task_payload, schedule_type, schedule_expr,
            timezone, mode, next_run_at
        ) VALUES ('Other mode', 1, 'query', '{}', 'daily',
                  '{"hour": 9, "minute": 0}', 'America/Los_Angeles', 'local',
                  '2026-07-28T14:00:00')
        """
    )
    other_mode_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()

    fixed_now = datetime(2026, 7, 28, 16, 0, tzinfo=timezone.utc)
    skipped = manager.skip_missed_tasks(
        now_utc_value=fixed_now,
        grace_seconds=300,
    )

    assert {item["task_id"] for item in skipped} == {once_id, recurring_id}
    once = manager.get_task(once_id)
    assert once["enabled"] == 0
    assert once["next_run_at"] is None
    assert once["last_status"] == "missed"

    recurring = manager.get_task(recurring_id)
    assert recurring["enabled"] == 1
    assert recurring["next_run_at"] == "2026-07-29T16:00:00"
    assert recurring["last_status"] == "missed"

    assert manager.get_task(recent_id)["next_run_at"] == "2026-07-28T15:57:00"
    assert manager.get_task(manual_id)["last_status"] == ScheduledTaskManager.RUN_ONCE_PENDING_STATUS
    monkeypatch.setattr(scheduled_task_manager_module, "now_utc", lambda: fixed_now)
    assert {task["id"] for task in manager.get_due_tasks()} == {recent_id, manual_id}

    conn = sqlite3.connect(manager.db.db_path)
    try:
        other = conn.execute(
            "SELECT next_run_at, last_status FROM scheduled_tasks WHERE id = ?",
            (other_mode_id,),
        ).fetchone()
        assert other == ("2026-07-28T14:00:00", None)
        assert conn.execute("SELECT COUNT(*) FROM scheduled_task_runs").fetchone()[0] == 0
    finally:
        conn.close()
