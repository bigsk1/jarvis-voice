"""Regression coverage for mode-owned scheduled tasks."""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest

from api.managers.scheduled_task_manager import ScheduledTaskManager
from api.models.scheduled_task import ScheduledTaskCreate, ScheduledTaskType


def _manager(path, mode: str) -> ScheduledTaskManager:
    manager = object.__new__(ScheduledTaskManager)
    manager.mode = mode
    manager.db = SimpleNamespace(db_path=str(path))
    manager._ensure_tables()
    return manager


def _insert_task(manager: ScheduledTaskManager, *, name: str, mode: str) -> int:
    conn = sqlite3.connect(manager.db.db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO scheduled_tasks (
            name, task_type, task_payload, schedule_type, schedule_expr,
            timezone, mode, next_run_at
        ) VALUES (?, 'query', ?, 'daily', ?, 'America/Los_Angeles', ?,
                  '2099-01-01T17:00:00')
        """,
        (
            name,
            json.dumps({"query": name}),
            json.dumps({"hour": 9, "minute": 0}),
            mode,
        ),
    )
    task_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return task_id


def test_manager_only_lists_gets_and_deletes_its_own_mode(tmp_path):
    path = tmp_path / "shared-legacy.db"
    cloud = _manager(path, "cloud")
    local = _manager(path, "local")
    cloud_id = _insert_task(cloud, name="Cloud task", mode="cloud")
    local_id = _insert_task(local, name="Local task", mode="local")

    assert [task["id"] for task in cloud.list_tasks()] == [cloud_id]
    assert [task["id"] for task in local.list_tasks()] == [local_id]
    assert cloud.get_task(local_id) is None
    assert local.get_task(cloud_id) is None

    assert cloud.delete_task(local_id) is False
    assert local.get_task(local_id)["name"] == "Local task"


def test_create_defaults_to_manager_mode_and_rejects_cross_mode_row(tmp_path):
    local = _manager(tmp_path / "local.db", "local")

    task_id = local.create_task(
        name="Local default",
        task_type="query",
        query="status",
        when="tomorrow at 9am",
    )
    assert local.get_task(task_id)["mode"] == "local"

    with pytest.raises(ValueError, match="belongs to local mode"):
        local.create_task(
            name="Wrong database",
            task_type="query",
            query="status",
            when="tomorrow at 9am",
            mode="cloud",
        )

    with pytest.raises(ValueError, match="cannot move a task to cloud"):
        local.update_task(task_id, mode="cloud")


def test_api_create_mode_defaults_to_active_manager_mode():
    request = ScheduledTaskCreate(
        name="Mode default",
        task_type=ScheduledTaskType.QUERY,
        query="status",
        when="tomorrow at 9am",
    )

    assert request.mode is None
