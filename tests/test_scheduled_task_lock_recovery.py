"""Regression coverage for scheduled-task runner crash recovery."""

from __future__ import annotations

import os
import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock

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


def test_cleanup_failure_marks_run_failed_and_releases_owned_lock(tmp_path):
    manager = _manager(tmp_path)
    owner = "cloud:4242:current-session"
    task_id, run_id = _insert_locked_task(manager, owner)
    next_run_at = "2026-08-21 12:00:00"

    recovered = manager.fail_run_and_release_lock(
        task_id,
        run_id,
        owner,
        reason="Scheduled task cleanup failed: database is locked",
        duration_ms=125.5,
        summary="Cleanup failed after execution",
        next_run_at=next_run_at,
    )

    assert recovered is True
    task = manager.get_task(task_id)
    assert task["lock_owner"] is None
    assert task["lock_acquired_at"] is None
    assert task["last_status"] == "failure"
    assert task["last_error"] == "Scheduled task cleanup failed: database is locked"
    assert task["last_duration_ms"] == 125.5
    assert task["last_result_summary"] == "Cleanup failed after execution"
    assert task["next_run_at"] == next_run_at

    run = manager.list_runs(task_id)[0]
    assert run["id"] == run_id
    assert run["status"] == "failure"
    assert run["finished_at"] is not None
    assert run["error"] == "Scheduled task cleanup failed: database is locked"


def test_cleanup_failure_does_not_release_another_runners_lock(tmp_path):
    manager = _manager(tmp_path)
    owner = "cloud:4242:current-session"
    task_id, run_id = _insert_locked_task(manager, owner)

    recovered = manager.fail_run_and_release_lock(
        task_id,
        run_id,
        "cloud:9999:different-session",
        reason="stale cleanup attempt",
    )

    assert recovered is False
    task = manager.get_task(task_id)
    assert task["lock_owner"] == owner
    run = manager.list_runs(task_id)[0]
    assert run["status"] == "running"
    assert run["finished_at"] is None


def test_runner_recovers_cleanup_failure_and_continues_batch(monkeypatch):
    first_task = {
        "id": 41,
        "name": "Cleanup failure",
        "mode": "cloud",
        "task_type": "query",
        "task_payload": "{}",
        "timeout_seconds": 30,
        "next_run_at": "2026-08-20 03:00:00",
        "task_target": None,
    }
    second_task = {
        **first_task,
        "id": 42,
        "name": "Later task",
        "next_run_at": "2026-08-20 03:01:00",
    }

    manager = MagicMock()
    manager.db = SimpleNamespace(db_path=":memory:")
    manager.skip_missed_tasks.return_value = []
    manager.get_due_tasks.return_value = [first_task, second_task]
    manager.is_manual_run_once.return_value = False
    manager.acquire_lock.return_value = True
    manager.create_run.side_effect = [101, 102]
    manager.resolve_followup_next_run.side_effect = [
        "2026-08-21 03:00:00",
        None,
    ]

    def finish_run(run_id, **_kwargs):
        if run_id == 101:
            raise sqlite3.OperationalError("database is locked")

    manager.finish_run.side_effect = finish_run
    manager.fail_run_and_release_lock.return_value = True

    logger = MagicMock()
    monkeypatch.setattr(runner, "_load_mode", lambda: "cloud")
    monkeypatch.setattr(runner, "ScheduledTaskManager", lambda mode: manager)
    monkeypatch.setattr(runner, "ServiceLogger", lambda _name: logger)
    monkeypatch.setattr(runner, "get_int", lambda *_args, **_kwargs: 300)
    monkeypatch.setattr(runner, "_recover_abandoned_locks", lambda *_args: [])
    monkeypatch.setattr(
        runner,
        "_run_with_timeout",
        lambda *_args, **_kwargs: {"ok": True, "speech": "done"},
    )
    monkeypatch.setattr(
        runner,
        "_execution_identity",
        lambda _mode: ("test-provider", "test-model"),
    )
    monkeypatch.setattr(
        runner.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    runner.main()

    recovery_call = manager.fail_run_and_release_lock.call_args
    assert recovery_call.args[:2] == (41, 101)
    assert str(recovery_call.args[2]).startswith("cloud:")
    assert recovery_call.kwargs["next_run_at"] == "2026-08-21 03:00:00"
    assert "database is locked" in recovery_call.kwargs["reason"]
    assert manager.finish_run.call_count == 2
    assert manager.finish_run.call_args_list[0].args == (101,)
    assert manager.finish_run.call_args_list[1].args == (102,)
    assert manager.release_lock_and_update.call_count == 1
    assert manager.release_lock_and_update.call_args.args == (42,)
