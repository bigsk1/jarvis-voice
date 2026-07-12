#!/usr/bin/env python3
"""
Regression tests for create_alert tool behavior.

Run:
    python3 tests/test_create_alert.py
"""

import json
import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from skills import create_alert


class CreateAlertToolTests(unittest.TestCase):
    def test_create_alert_success(self):
        stdout = StringIO()

        class FakeManager:
            def create_alert(self, **kwargs):
                self.kwargs = kwargs
                return 42

            def get_alert(self, alert_id):
                return {"id": alert_id, "title": "Frost risk", "severity": "high", "source": "crop_frost_watch"}

        fake_manager = FakeManager()

        with patch("skills.create_alert.AlertManager", return_value=fake_manager), \
             patch.object(sys, "argv", ["create_alert.py", json.dumps({
                 "title": "Frost risk",
                 "source": "crop_frost_watch",
                 "severity": "high"
             })]), \
             patch("sys.stdout", stdout):
            create_alert.main()

        result = json.loads(stdout.getvalue())
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["alert_id"], 42)
        self.assertFalse(result["data"]["duplicate_suppressed"])
        self.assertEqual(fake_manager.kwargs["severity"], "high")

    def test_duplicate_alert_returns_success_with_flag(self):
        stdout = StringIO()

        class FakeManager:
            def create_alert(self, **kwargs):
                self.kwargs = kwargs
                return -12

            def get_alert(self, alert_id):
                return {"id": alert_id, "title": "Frost risk", "severity": "high", "source": "crop_frost_watch"}

        fake_manager = FakeManager()

        with patch("skills.create_alert.AlertManager", return_value=fake_manager), \
             patch.object(sys, "argv", ["create_alert.py", json.dumps({
                 "title": "Frost risk",
                 "source": "crop_frost_watch"
             })]), \
             patch("sys.stdout", stdout):
            create_alert.main()

        result = json.loads(stdout.getvalue())
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["alert_id"], 12)
        self.assertTrue(result["data"]["duplicate_suppressed"])
        self.assertEqual(result["data"]["severity"], "high")
        self.assertEqual(fake_manager.kwargs["severity"], "high")


if __name__ == "__main__":
    unittest.main()
