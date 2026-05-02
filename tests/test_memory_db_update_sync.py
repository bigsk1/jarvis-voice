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

    def test_forget_removes_matching_sibling_row(self) -> None:
        cloud_db = MemoryDB(str(self.cloud_path))
        local_db = MemoryDB(str(self.local_path))
        try:
            cloud_id = cloud_db.remember(
                "personal", "user_birthday", "January 1st", generate_embedding=False
            )
            local_db.remember(
                "personal", "user_birthday", "January 1st", generate_embedding=False
            )
            self.assertTrue(cloud_db.forget(cloud_id))
        finally:
            cloud_db.close()
            local_db.close()

        cloud_db = MemoryDB(str(self.cloud_path))
        local_db = MemoryDB(str(self.local_path))
        try:
            self.assertEqual(cloud_db.get_all_memories(), [])
            self.assertEqual(local_db.get_all_memories(), [])
        finally:
            cloud_db.close()
            local_db.close()

    def test_forget_skips_missing_sibling_db(self) -> None:
        cloud_db = MemoryDB(str(self.cloud_path))
        try:
            cloud_id = cloud_db.remember(
                "personal", "user_birthday", "January 1st", generate_embedding=False
            )
            self.assertFalse(self.local_path.exists())
            self.assertTrue(cloud_db.forget(cloud_id))
            self.assertEqual(cloud_db.get_all_memories(), [])
            self.assertFalse(self.local_path.exists())
        finally:
            cloud_db.close()

    def test_forget_without_mirror_preserves_sibling_same_category_key(self) -> None:
        """Dedupe-style: two rows share category+key on cloud; sibling has one keeper row."""
        cloud_db = MemoryDB(str(self.cloud_path))
        local_db = MemoryDB(str(self.local_path))
        try:
            cloud_db.conn.execute(
                """
                INSERT INTO knowledge_base (category, key, value, importance, source)
                VALUES ('personal', 'dup_key', 'copy A', 5, 'test')
                """
            )
            cloud_db.conn.execute(
                """
                INSERT INTO knowledge_base (category, key, value, importance, source)
                VALUES ('personal', 'dup_key', 'copy B', 5, 'test')
                """
            )
            cloud_db.conn.commit()
            rows = cloud_db.conn.execute(
                "SELECT id FROM knowledge_base WHERE category = ? AND key = ? ORDER BY id",
                ("personal", "dup_key"),
            ).fetchall()
            self.assertEqual(len(rows), 2)
            dup_a, dup_b = int(rows[0]["id"]), int(rows[1]["id"])

            local_db.remember(
                "personal", "dup_key", "canonical local", generate_embedding=False
            )
        finally:
            cloud_db.close()
            local_db.close()

        cloud_db = MemoryDB(str(self.cloud_path))
        try:
            self.assertTrue(cloud_db.forget(dup_a, mirror_sibling=False))
            remaining_cloud = cloud_db.get_all_memories()
            self.assertEqual(len(remaining_cloud), 1)
            self.assertEqual(remaining_cloud[0]["id"], dup_b)
        finally:
            cloud_db.close()

        local_db = MemoryDB(str(self.local_path))
        try:
            local_rows = local_db.get_all_memories()
            self.assertEqual(len(local_rows), 1)
            self.assertEqual(local_rows[0]["value"], "canonical local")
        finally:
            local_db.close()


if __name__ == "__main__":
    unittest.main()
