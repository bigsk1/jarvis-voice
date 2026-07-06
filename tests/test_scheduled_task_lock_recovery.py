"""Regression coverage for scheduled-task runner crash recovery."""

from __future__ import annotations

import os
import sqlite3
from types import SimpleNamespace

from api.managers.scheduled_task_manager import ScheduledTaskManager
from services import scheduled_task_runner as runner


def _manager(tmp_path) -> ScheduledTaskManager:
    manager = object.__new__(ScheduledTaskManager)
    manager.mode = "cloud"
    manager.db = SimpleNamespace(db_path=str(tmp_path / "scheduled.db"))
    manager._ensure_tables()
    return manager


def _insert_locked_task(manager: ScheduledTaskManager, owner: str) -> tuple[int, int]:
    conn = sqlite3.connect(manager.db.db_path)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO scheduled_tasks (
            name, enabled, task_type, schedule_type, schedule_expr, mode,
            next_run_at, lock_owner, lock_acquired_at, last_status
        ) VALUES (?, 1, 'query', 'once', '{}', 'cloud', ?, ?, ?, 'running')
    """, ("Crash recovery", "2000-01-01 00:00:00", owner, "2000-01-01T00:00:00"))
    task_id = cursor.lastrowid
    cursor.execute("""
        INSERT INTO scheduled_task_runs (task_id, started_at, status)
        VALUES (?, ?, 'running')
    """, (task_id, "2000-01-01T00:00:00"))
    run_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return task_id, run_id


def test_recovery_releases_dead_owner_and_finishes_interrupted_run(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    task_id, run_id = _insert_locked_task(manager, "cloud:999999:oldsession")
    monkeypatch.setattr(
        runner.os,
        "kill",
        lambda _pid, _signal: (_ for _ in ()).throw(ProcessLookupError()),
    )
    assert manager.get_due_tasks() == []

    recovered = runner._recover_abandoned_locks(
        manager,
        "cloud",
        "cloud:12345:newsession",
    )

    assert recovered == [task_id]
    task = manager.get_task(task_id)
    assert task["lock_owner"] is None
    assert task["lock_acquired_at"] is None
    assert task["last_status"] == "failure"
    assert "cloud:999999:oldsession" in task["last_error"]
    assert [item["id"] for item in manager.get_due_tasks()] == [task_id]
    run = manager.list_runs(task_id)[0]
    assert run["id"] == run_id
    assert run["status"] == "failure"
    assert run["finished_at"] is not None


def test_recovery_keeps_lock_owned_by_live_runner(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    task_id, _run_id = _insert_locked_task(manager, "cloud:4242:activesession")
    checked = []

    def process_exists(pid, signal):
        checked.append((pid, signal))

    monkeypatch.setattr(runner.os, "kill", process_exists)

    recovered = runner._recover_abandoned_locks(
        manager,
        "cloud",
        "cloud:12345:newsession",
    )

    assert recovered == []
    assert checked == [(4242, 0)]
    assert manager.get_task(task_id)["lock_owner"] == "cloud:4242:activesession"


def test_recovery_handles_reused_current_pid_after_container_restart(tmp_path):
    manager = _manager(tmp_path)
    owner = f"cloud:{os.getpid()}:previous-session"
    task_id, _run_id = _insert_locked_task(manager, owner)

    recovered = runner._recover_abandoned_locks(
        manager,
        "cloud",
        f"cloud:{os.getpid()}:current-session",
    )

    assert recovered == [task_id]
    assert manager.get_task(task_id)["lock_owner"] is None
