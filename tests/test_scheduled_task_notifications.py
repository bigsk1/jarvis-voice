#!/usr/bin/env python3
"""
Regression tests for scheduled task notification helpers.

Run:
    python3 tests/test_scheduled_task_notifications.py
"""

import json
import subprocess
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

    def test_notification_timeout_is_reported_and_later_channels_continue(self):
        task = {
            "id": 12,
            "name": "Daily summary",
            "task_type": "query",
            "mode": "cloud",
            "task_payload": json.dumps({"query": "Summarize today"}),
            "metadata": json.dumps({
                "notifications": {
                    "contact_name": "boss",
                    "webhook_name": "notify_slack",
                    "email_on_success": True,
                    "webhook_on_success": True,
                }
            }),
        }

        with patch.object(runner, "_notification_allowed", return_value=True):
            with patch.object(
                runner,
                "_run_skill_script",
                side_effect=[
                    subprocess.TimeoutExpired("send_email.py", 60),
                    {"ok": True},
                ],
            ):
                results = runner._maybe_send_notifications(
                    task,
                    status="success",
                    summary="Done",
                    error=None,
                    scheduled_for="2026-07-06 12:00:00",
                    next_run="2026-07-07 12:00:00",
                )

        self.assertEqual([item["channel"] for item in results], ["email", "webhook"])
        self.assertFalse(results[0]["result"]["ok"])
        self.assertIn("timed out", results[0]["result"]["error"].lower())
        self.assertTrue(results[1]["result"]["ok"])


if __name__ == "__main__":
    unittest.main()
