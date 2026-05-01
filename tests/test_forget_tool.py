#!/usr/bin/env python3
"""Regression tests for the forget tool."""

import json
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from lib.memory_db import MemoryDB
from skills import forget


class ForgetToolTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "forget-test.db"

    def tearDown(self):
        self.temp_dir.cleanup()

    def _seed_memories(self) -> tuple[int, int]:
        db = MemoryDB(str(self.db_path))
        try:
            first_id = db.remember("personal", "user_birthday", "January 1st", generate_embedding=False)
            second_id = db.remember("personal", "birthday", "January 1st", generate_embedding=False)
            return first_id, second_id
        finally:
            db.close()

    def test_forget_accepts_multiple_memory_ids_in_one_call(self):
        first_id, second_id = self._seed_memories()
        stdout = StringIO()

        with patch("skills.forget.get_memory_db", return_value=MemoryDB(str(self.db_path))), \
             patch.object(
                 sys,
                 "argv",
                 ["forget.py", json.dumps({"memory_ids": [first_id, second_id]})],
             ), \
             patch("sys.stdout", stdout):
            result = forget.main()

        payload = json.loads(stdout.getvalue())
        self.assertTrue(result["ok"])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["deleted_ids"], [first_id, second_id])
        self.assertEqual(
            payload["data"]["deleted_keys"],
            ["user_birthday", "birthday"],
        )

        db = MemoryDB(str(self.db_path))
        try:
            remaining_ids = [memory["id"] for memory in db.get_all_memories()]
        finally:
            db.close()

        self.assertEqual(remaining_ids, [])


if __name__ == "__main__":
    unittest.main()
