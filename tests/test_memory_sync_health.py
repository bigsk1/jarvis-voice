#!/usr/bin/env python3
"""Tests for bin/check-memory-sync-health.py."""

from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "bin" / "check-memory-sync-health.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("check_memory_sync_health", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _init_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE knowledge_base (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            importance INTEGER DEFAULT 5,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            source TEXT,
            metadata TEXT,
            embedding BLOB,
            long_form TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def _init_user_model(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_model (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL UNIQUE,
            value TEXT NOT NULL,
            value_type TEXT DEFAULT 'scalar',
            confidence REAL DEFAULT 0.5,
            evidence TEXT,
            source TEXT,
            metadata TEXT,
            last_reconciled_at TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


def _insert_row(
    path: Path,
    *,
    category: str,
    key: str,
    value: str,
    importance: int = 5,
    source: str | None = None,
    long_form: str | None = None,
) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        INSERT INTO knowledge_base (category, key, value, importance, source, long_form)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (category, key, value, importance, source, long_form),
    )
    conn.commit()
    conn.close()


def _insert_user_trait(path: Path, key: str, value: str, confidence: float = 0.5) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        INSERT INTO user_model (key, value, value_type, confidence, source)
        VALUES (?, ?, 'scalar', ?, 'test')
        """,
        (key, value, confidence),
    )
    conn.commit()
    conn.close()


class MemorySyncHealthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_script_module()

    def test_reports_missing_local_db_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            intel_dir = root / "jarvis-intel"
            data_dir.mkdir()
            intel_dir.mkdir()

            cloud_db = data_dir / "jarvis_memory.db"
            _init_db(cloud_db)

            report = self.module.build_sync_health_report(root, limit=5)

            self.assertFalse(report["ok"])
            self.assertTrue(report["db_status"]["cloud"]["available"])
            self.assertFalse(report["db_status"]["local"]["available"])
            self.assertEqual(report["db_status"]["local"]["error"], "missing")
            self.assertFalse(report["memories"]["comparable"])

    def test_detects_intel_hash_mismatch_against_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            intel_dir = root / "jarvis-intel"
            data_dir.mkdir()
            intel_dir.mkdir()

            cloud_db = data_dir / "jarvis_memory.db"
            local_db = data_dir / "jarvis_memory_local.db"
            _init_db(cloud_db)
            _init_db(local_db)

            file_path = intel_dir / "user-profile.md"
            file_path.write_text("hello world\n", encoding="utf-8")
            actual_hash = self.module._md5_file(file_path)

            _insert_row(
                cloud_db,
                category="system",
                key="intel_hash_user-profile.md",
                value=actual_hash,
            )
            _insert_row(
                local_db,
                category="system",
                key="intel_hash_user-profile.md",
                value="deadbeef",
            )

            report = self.module.build_sync_health_report(root, limit=5)

            self.assertEqual(len(report["intel"]["mismatches"]), 1)
            mismatch = report["intel"]["mismatches"][0]
            self.assertEqual(mismatch["filename"], "user-profile.md")
            self.assertEqual(mismatch["disk_hash"], actual_hash)
            self.assertEqual(mismatch["local_hash"], "deadbeef")

    def test_detects_cloud_only_memory_and_value_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            intel_dir = root / "jarvis-intel"
            data_dir.mkdir()
            intel_dir.mkdir()

            cloud_db = data_dir / "jarvis_memory.db"
            local_db = data_dir / "jarvis_memory_local.db"
            _init_db(cloud_db)
            _init_db(local_db)

            _insert_row(
                cloud_db,
                category="personal",
                key="birthday",
                value="January 2",
                source="manual",
            )
            _insert_row(
                local_db,
                category="personal",
                key="birthday",
                value="January 1",
                source="manual",
            )
            _insert_row(
                cloud_db,
                category="personal",
                key="favorite_color",
                value="blue",
                source="manual",
            )

            report = self.module.build_sync_health_report(root, limit=5)

            self.assertTrue(report["memories"]["comparable"])
            self.assertEqual(report["memories"]["only_in_cloud_count"], 2)
            self.assertEqual(report["memories"]["only_in_local_count"], 1)
            self.assertEqual(report["memories"]["value_conflict_count"], 1)
            conflict = report["memories"]["samples"]["value_conflicts"][0]
            self.assertEqual(conflict["key"], "birthday")
            self.assertIn("January 2", conflict["cloud_values"][0])
            self.assertIn("January 1", conflict["local_values"][0])

    def test_detects_user_model_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            intel_dir = root / "jarvis-intel"
            data_dir.mkdir()
            intel_dir.mkdir()

            cloud_db = data_dir / "jarvis_memory.db"
            local_db = data_dir / "jarvis_memory_local.db"
            _init_db(cloud_db)
            _init_db(local_db)
            _init_user_model(cloud_db)
            _init_user_model(local_db)
            _insert_user_trait(cloud_db, "verbosity", "0.25", 0.8)
            _insert_user_trait(local_db, "verbosity", "0.75", 0.8)

            report = self.module.build_sync_health_report(root, limit=5)

            self.assertFalse(report["ok"])
            self.assertEqual(report["user_model"]["value_conflict_count"], 1)
            conflict = report["user_model"]["samples"]["value_conflicts"][0]
            self.assertEqual(conflict["key"], "verbosity")
            self.assertEqual(conflict["cloud_value"], "0.25")
            self.assertEqual(conflict["local_value"], "0.75")


if __name__ == "__main__":
    unittest.main()
