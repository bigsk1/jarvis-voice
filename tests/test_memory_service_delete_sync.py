#!/usr/bin/env python3
"""Regression tests for mirrored deletes in the Memory UI service."""

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-memory"))

from server.services import memory_service as memory_service_module
from server.services.memory_service import MemoryService


class MemoryServiceDeleteSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cloud_path = Path(self.temp_dir.name) / "jarvis_memory.db"
        self.local_path = Path(self.temp_dir.name) / "jarvis_memory_local.db"
        self.original_db_paths = dict(memory_service_module.DB_PATHS)
        memory_service_module.DB_PATHS = {
            "cloud": self.cloud_path,
            "local": self.local_path,
        }

    def tearDown(self):
        memory_service_module.DB_PATHS = self.original_db_paths
        self.temp_dir.cleanup()

    def _create_schema(self, path: Path) -> None:
        service = MemoryService("cloud" if path == self.cloud_path else "local")
        conn = service._get_conn()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_base (
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
        finally:
            conn.close()

    def test_delete_memory_removes_matching_sibling_row(self):
        self._create_schema(self.cloud_path)
        self._create_schema(self.local_path)

        cloud = MemoryService("cloud")
        local = MemoryService("local")
        cloud_id = cloud.create_memory("personal", "user_birthday", "January 1st")
        local.create_memory("personal", "user_birthday", "January 1st")

        self.assertTrue(cloud.delete_memory(cloud_id))
        self.assertEqual(cloud.list_memories(), [])
        self.assertEqual(local.list_memories(), [])

    def test_delete_memory_skips_missing_sibling_db(self):
        self._create_schema(self.cloud_path)

        cloud = MemoryService("cloud")
        cloud_id = cloud.create_memory("personal", "user_birthday", "January 1st")

        self.assertFalse(self.local_path.exists())
        self.assertTrue(cloud.delete_memory(cloud_id))
        self.assertEqual(cloud.list_memories(), [])
        self.assertFalse(self.local_path.exists())

    def test_update_memory_updates_matching_sibling_row(self):
        self._create_schema(self.cloud_path)
        self._create_schema(self.local_path)

        cloud = MemoryService("cloud")
        local = MemoryService("local")
        cloud_id = cloud.create_memory("personal", "user_birthday", "January 1st")
        local.create_memory("personal", "user_birthday", "January 1st")

        self.assertTrue(
            cloud.update_memory(
                cloud_id,
                category="profile",
                key="birthday",
                value="January 2nd",
                importance=9,
                metadata={"verified": True},
            )
        )

        cloud_row = cloud.list_memories()[0]
        local_row = local.list_memories()[0]
        self.assertEqual(cloud_row["category"], "profile")
        self.assertEqual(cloud_row["key"], "birthday")
        self.assertEqual(cloud_row["value"], "January 2nd")
        self.assertEqual(cloud_row["importance"], 9)
        self.assertEqual(local_row["category"], "profile")
        self.assertEqual(local_row["key"], "birthday")
        self.assertEqual(local_row["value"], "January 2nd")
        self.assertEqual(local_row["importance"], 9)
        self.assertEqual(local_row["metadata"], {"verified": True})

    def test_update_memory_skips_missing_sibling_db(self):
        self._create_schema(self.cloud_path)

        cloud = MemoryService("cloud")
        cloud_id = cloud.create_memory("personal", "user_birthday", "January 1st")

        self.assertFalse(self.local_path.exists())
        self.assertTrue(cloud.update_memory(cloud_id, value="January 2nd"))
        self.assertEqual(cloud.list_memories()[0]["value"], "January 2nd")
        self.assertFalse(self.local_path.exists())


if __name__ == "__main__":
    unittest.main()
