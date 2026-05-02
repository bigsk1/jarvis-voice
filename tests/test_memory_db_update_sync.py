#!/usr/bin/env python3
"""Regression tests for mirrored updates in lib.memory_db.MemoryDB."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lib.memory_db import MemoryDB


class MemoryDBUpdateSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cloud_path = Path(self.temp_dir.name) / "jarvis_memory.db"
        self.local_path = Path(self.temp_dir.name) / "jarvis_memory_local.db"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_update_memory_updates_matching_sibling_row(self) -> None:
        cloud_db = MemoryDB(str(self.cloud_path))
        local_db = MemoryDB(str(self.local_path))
        try:
            cloud_id = cloud_db.remember(
                "personal", "user_birthday", "January 1st", generate_embedding=False
            )
            local_db.remember(
                "personal", "user_birthday", "January 1st", generate_embedding=False
            )
            self.assertTrue(cloud_db.update_memory(cloud_id, value="January 2nd", importance=9))
        finally:
            cloud_db.close()
            local_db.close()

        cloud_db = MemoryDB(str(self.cloud_path))
        local_db = MemoryDB(str(self.local_path))
        try:
            self.assertEqual(cloud_db.get_all_memories()[0]["value"], "January 2nd")
            self.assertEqual(cloud_db.get_all_memories()[0]["importance"], 9)
            self.assertEqual(local_db.get_all_memories()[0]["value"], "January 2nd")
            self.assertEqual(local_db.get_all_memories()[0]["importance"], 9)
        finally:
            cloud_db.close()
            local_db.close()

    def test_update_memory_skips_missing_sibling_db(self) -> None:
        cloud_db = MemoryDB(str(self.cloud_path))
        try:
            cloud_id = cloud_db.remember(
                "personal", "user_birthday", "January 1st", generate_embedding=False
            )
            self.assertFalse(self.local_path.exists())
            self.assertTrue(cloud_db.update_memory(cloud_id, value="January 2nd"))
            self.assertFalse(self.local_path.exists())
        finally:
            cloud_db.close()


if __name__ == "__main__":
    unittest.main()
