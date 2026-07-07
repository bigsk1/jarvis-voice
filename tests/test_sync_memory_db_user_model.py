#!/usr/bin/env python3
"""Regression tests for user_model sync in bin/sync-memory-db.py."""

from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib.memory_db import MemoryDB


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "bin" / "sync-memory-db.py"


def _load_sync_module():
    spec = importlib.util.spec_from_file_location("sync_memory_db", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SyncMemoryDbUserModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_sync_module()

    def test_sync_creates_and_copies_user_model_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            data_dir.mkdir()
            cloud_path = data_dir / "jarvis_memory.db"
            local_path = data_dir / "jarvis_memory_local.db"

            cloud_db = MemoryDB(str(cloud_path))
            try:
                cloud_db.upsert_user_model_trait(
                    "technical_depth",
                    0.8,
                    confidence=0.75,
                    evidence=[{"type": "feedback", "id": 42}],
                    source="test",
                )
            finally:
                cloud_db.close()

            self.assertTrue(
                self.module.sync_databases(
                    source_mode="cloud",
                    target_mode="local",
                    verbose=False,
                    project_root=root,
                )
            )

            conn = sqlite3.connect(local_path)
            conn.row_factory = sqlite3.Row
            try:
                columns = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(user_model)").fetchall()
                }
                self.assertIn("confidence", columns)
                row = conn.execute(
                    "SELECT key, value, confidence, source FROM user_model WHERE key = ?",
                    ("technical_depth",),
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row["value"], "0.8")
                self.assertEqual(row["confidence"], 0.75)
                self.assertEqual(row["source"], "test")
            finally:
                conn.close()

    def test_sync_preserves_same_intel_identity_from_different_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            data_dir.mkdir()
            cloud_path = data_dir / "jarvis_memory.db"
            local_path = data_dir / "jarvis_memory_local.db"

            cloud_db = MemoryDB(str(cloud_path))
            local_db = MemoryDB(str(local_path))
            try:
                for source, value in (
                    ("intel/site_a.md", "10.0.0.1"),
                    ("intel/site_b.md", "192.168.1.1"),
                ):
                    cloud_db.remember(
                        "network",
                        "Servers - IP",
                        value,
                        source=source,
                        generate_embedding=False,
                        dedupe_by_source=True,
                    )
                # Legacy target state has only the last globally deduplicated row.
                local_db.remember(
                    "network",
                    "Servers - IP",
                    "192.168.1.1",
                    source="intel/site_b.md",
                    generate_embedding=False,
                )
            finally:
                cloud_db.close()
                local_db.close()

            with patch("embeddings.get_embedding", return_value=[1.0, 0.0, 0.0]):
                self.assertTrue(
                    self.module.sync_databases(
                        source_mode="cloud",
                        target_mode="local",
                        verbose=False,
                        project_root=root,
                    )
                )

            conn = sqlite3.connect(local_path)
            try:
                rows = conn.execute(
                    """
                    SELECT source FROM knowledge_base
                    WHERE category = 'network' AND key = 'Servers - IP'
                    ORDER BY source
                    """
                ).fetchall()
                self.assertEqual(
                    [row[0] for row in rows],
                    ["intel/site_a.md", "intel/site_b.md"],
                )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
