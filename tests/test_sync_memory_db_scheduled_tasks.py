#!/usr/bin/env python3
"""Regression coverage for mode-owned scheduled-task tables."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

from lib.memory_db import MemoryDB


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "bin" / "sync-memory-db.py"


def _load_sync_module():
    spec = importlib.util.spec_from_file_location("sync_memory_db_schedules", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _create_schedule_tables(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scheduled_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            enabled BOOLEAN DEFAULT 1,
            task_type TEXT NOT NULL,
            task_target TEXT,
            task_payload TEXT,
            schedule_type TEXT NOT NULL,
            schedule_expr TEXT NOT NULL,
            timezone TEXT DEFAULT 'America/Los_Angeles',
            mode TEXT DEFAULT 'cloud',
            allow_overlap BOOLEAN DEFAULT 0,
            max_retries INTEGER DEFAULT 1,
            timeout_seconds INTEGER DEFAULT 300,
            last_run_at TEXT,
            next_run_at TEXT,
            last_status TEXT,
            last_error TEXT,
            last_duration_ms REAL,
            last_result_summary TEXT,
            lock_owner TEXT,
            lock_acquired_at TEXT,
            metadata TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scheduled_task_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            mode TEXT,
            provider TEXT,
            model TEXT,
            workflow_id TEXT,
            tools_used TEXT,
            speech TEXT,
            raw_llm_response TEXT,
            result_data TEXT,
            error TEXT,
            duration_ms REAL,
            completion_guard_applied BOOLEAN DEFAULT 0,
            feedback_collected BOOLEAN DEFAULT 0,
            metadata TEXT
        )
        """
    )
    return conn


def _insert_task(conn: sqlite3.Connection, task_id: int, name: str, mode: str) -> None:
    conn.execute(
        """
        INSERT INTO scheduled_tasks (
            id, name, task_type, task_payload, schedule_type, schedule_expr,
            timezone, mode, next_run_at
        ) VALUES (?, ?, 'query', '{}', 'daily', '{"hour": 9, "minute": 0}',
                  'America/Los_Angeles', ?, '2099-01-01T17:00:00')
        """,
        (task_id, name, mode),
    )
    conn.execute(
        """
        INSERT INTO scheduled_task_runs (id, task_id, started_at, status, mode)
        VALUES (?, ?, '2026-07-28T09:00:00', 'success', ?)
        """,
        (task_id, task_id, mode),
    )
    conn.commit()


def test_memory_sync_does_not_copy_mode_owned_schedules_or_runs(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    cloud_path = data_dir / "jarvis_memory.db"
    local_path = data_dir / "jarvis_memory_local.db"

    MemoryDB(str(cloud_path)).close()
    MemoryDB(str(local_path)).close()

    cloud = _create_schedule_tables(cloud_path)
    local = _create_schedule_tables(local_path)
    try:
        _insert_task(cloud, 11, "Cloud-only task", "cloud")
        _insert_task(local, 21, "Local-only task", "local")
    finally:
        cloud.close()
        local.close()

    module = _load_sync_module()
    assert module.sync_databases(
        source_mode="cloud",
        target_mode="local",
        verbose=False,
        project_root=tmp_path,
    )

    conn = sqlite3.connect(local_path)
    try:
        assert conn.execute(
            "SELECT id, name, mode FROM scheduled_tasks ORDER BY id"
        ).fetchall() == [(21, "Local-only task", "local")]
        assert conn.execute(
            "SELECT id, task_id, mode FROM scheduled_task_runs ORDER BY id"
        ).fetchall() == [(21, 21, "local")]
    finally:
        conn.close()
