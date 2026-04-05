#!/usr/bin/env python3
"""
Regression tests for scheduled task notification helpers.

Run:
    python3 tests/test_scheduled_task_notifications.py
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from services import scheduled_task_runner as runner


class ScheduledTaskNotificationTests(unittest.TestCase):
    def test_get_notification_settings_reads_metadata_json(self):
        task = {
            "metadata": json.dumps({
                "notifications": {
                    "contact_name": "boss",
                    "email_on_failure": True,
                    "alert_on_failure": True,
                }
            })
        }

        settings = runner._get_notification_settings(task)
        self.assertEqual(settings["contact_name"], "boss")
        self.assertTrue(settings["email_on_failure"])
        self.assertTrue(settings["alert_on_failure"])

    def test_notification_allowed_suppresses_duplicate_same_slot_within_cooldown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_file = Path(tmpdir) / ".scheduled_task_notification_rate_limit"
            identifier = "12:email:failure:2026-04-05 09:00:00"

            with patch.object(runner, "NOTIFICATION_RATE_LIMIT_FILE", temp_file):
                with patch.object(runner, "get_int", return_value=900):
                    with patch.object(runner.time, "time", return_value=1000.0):
                        self.assertTrue(runner._notification_allowed(identifier))
                    with patch.object(runner.time, "time", return_value=1005.0):
                        self.assertFalse(runner._notification_allowed(identifier))
                    with patch.object(runner.time, "time", return_value=2001.0):
                        self.assertTrue(runner._notification_allowed(identifier))


if __name__ == "__main__":
    unittest.main()
