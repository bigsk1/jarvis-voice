#!/usr/bin/env python3
"""Regression coverage for mode-local alert and reminder tables."""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

MEMORY_SCRIPT_PATH = PROJECT_ROOT / "lib" / "memory_db.py"
SYNC_SCRIPT_PATH = PROJECT_ROOT / "bin" / "sync-memory-db.py"
MIGRATION_SCRIPT_PATH = PROJECT_ROOT / "bin" / "migrate-proactive-db.py"


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


MemoryDB = _load_script("memory_db", MEMORY_SCRIPT_PATH).MemoryDB


def _insert_proactive_rows(
    path: Path,
    *,
    row_id: int,
    label: str,
) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            INSERT INTO alerts (id, title, severity, source, status, created_at)
            VALUES (?, ?, 'high', ?, 'pending', '2026-08-19T12:00:00')
            """,
            (row_id, f"{label} alert", label.lower()),
        )
        conn.execute(
            """
            INSERT INTO reminders (id, title, trigger_time, status, created_at)
            VALUES (?, ?, '2099-01-01T12:00:00', 'scheduled', '2026-08-19T12:00:00')
            """,
            (row_id, f"{label} reminder"),
        )
        conn.commit()
    finally:
        conn.close()


def test_memory_sync_keeps_alerts_and_reminders_mode_local(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    cloud_path = data_dir / "jarvis_memory.db"
    local_path = data_dir / "jarvis_memory_local.db"

    MemoryDB(str(cloud_path)).close()
    MemoryDB(str(local_path)).close()

    migration = _load_script("migrate_proactive_db", MIGRATION_SCRIPT_PATH)
    migration.migrate_database(cloud_path)
    migration.migrate_database(local_path)

    _insert_proactive_rows(cloud_path, row_id=101, label="Cloud")
    _insert_proactive_rows(local_path, row_id=201, label="Local")

    sync = _load_script("sync_memory_db_proactive", SYNC_SCRIPT_PATH)
    assert sync.sync_databases(
        source_mode="cloud",
        target_mode="local",
        verbose=False,
        project_root=tmp_path,
    )
    assert sync.sync_databases(
        source_mode="local",
        target_mode="cloud",
        verbose=False,
        project_root=tmp_path,
    )

    conn = sqlite3.connect(local_path)
    try:
        assert conn.execute(
            "SELECT id, title, source FROM alerts ORDER BY id"
        ).fetchall() == [(201, "Local alert", "local")]
        assert conn.execute(
            "SELECT id, title, status FROM reminders ORDER BY id"
        ).fetchall() == [(201, "Local reminder", "scheduled")]
    finally:
        conn.close()

    conn = sqlite3.connect(cloud_path)
    try:
        assert conn.execute(
            "SELECT id, title, source FROM alerts ORDER BY id"
        ).fetchall() == [(101, "Cloud alert", "cloud")]
        assert conn.execute(
            "SELECT id, title, status FROM reminders ORDER BY id"
        ).fetchall() == [(101, "Cloud reminder", "scheduled")]
    finally:
        conn.close()
