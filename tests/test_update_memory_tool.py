#!/usr/bin/env python3
"""Regression tests for the ID-only update_memory tool contract."""

from __future__ import annotations

import json
import sys
import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

from skills import update_memory


class UpdateMemoryToolTests(unittest.TestCase):
    def test_updates_the_explicit_memory_id(self):
        db = MagicMock()
        db.update_memory.return_value = True
        stdout = StringIO()

        with patch("skills.update_memory.get_memory_db", return_value=db), patch.object(
            sys,
            "argv",
            [
                "update_memory.py",
                json.dumps({"memory_id": 9105, "new_value": "corrected value"}),
            ],
        ), patch("sys.stdout", stdout):
            result = update_memory.main()

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["memory_id"], 9105)
        db.update_memory.assert_called_once_with(
            memory_id=9105,
            value="corrected value",
            importance=None,
        )
        db.close.assert_called_once_with()

    def test_search_query_shortcut_is_rejected_before_database_access(self):
        stdout = StringIO()

        with patch("skills.update_memory.get_memory_db") as get_memory_db, patch.object(
            sys,
            "argv",
            [
                "update_memory.py",
                json.dumps(
                    {
                        "search_query": "pineapple on pizza",
                        "new_value": "pineapple pizza is disliked",
                    }
                ),
            ],
        ), patch("sys.stdout", stdout):
            result = update_memory.main()

        payload = json.loads(stdout.getvalue())
        self.assertFalse(result["ok"])
        self.assertEqual(payload["error"], "Missing memory_id parameter")
        self.assertEqual(
            payload["data"]["lookup_tools"],
            ["search_memory", "semantic_recall"],
        )
        self.assertIn("didn't update anything", payload["speech"])
        get_memory_db.assert_not_called()

    def test_invalid_memory_id_is_rejected_before_database_access(self):
        stdout = StringIO()

        with patch("skills.update_memory.get_memory_db") as get_memory_db, patch.object(
            sys,
            "argv",
            [
                "update_memory.py",
                json.dumps({"memory_id": "pizza", "new_value": "corrected value"}),
            ],
        ), patch("sys.stdout", stdout):
            result = update_memory.main()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "Invalid memory_id parameter")
        get_memory_db.assert_not_called()


if __name__ == "__main__":
    unittest.main()
