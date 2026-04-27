#!/usr/bin/env python3
"""
Regression tests for reminder parsing and duplicate suppression.

Run:
    python3 tests/test_create_reminder.py
"""

import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from skills.create_reminder import create_single_reminder, parse_time_expression


class CreateReminderTests(unittest.TestCase):
    def test_absolute_month_name_uses_future_month_day(self):
        tz = ZoneInfo("America/Los_Angeles")
        now = datetime(2026, 4, 26, 17, 59, 7, tzinfo=tz)

        with patch("skills.create_reminder.now_local", return_value=now):
            trigger_result, recurrence_rule = parse_time_expression("May 1st at 6pm")

        self.assertIsNone(recurrence_rule)
        self.assertEqual(trigger_result, datetime(2026, 5, 1, 18, 0, tzinfo=tz))

    def test_next_month_on_day_is_supported(self):
        tz = ZoneInfo("America/Los_Angeles")
        now = datetime(2026, 4, 26, 17, 59, 7, tzinfo=tz)

        with patch("skills.create_reminder.now_local", return_value=now):
            trigger_result, recurrence_rule = parse_time_expression("next month on the 1st at 6pm")

        self.assertIsNone(recurrence_rule)
        self.assertEqual(trigger_result, datetime(2026, 5, 1, 18, 0, tzinfo=tz))

    def test_month_name_rolls_forward_to_next_year_when_needed(self):
        tz = ZoneInfo("America/Los_Angeles")
        now = datetime(2026, 12, 20, 9, 0, tzinfo=tz)

        with patch("skills.create_reminder.now_local", return_value=now):
            trigger_result, recurrence_rule = parse_time_expression("January 5th at 9am")

        self.assertIsNone(recurrence_rule)
        self.assertEqual(trigger_result, datetime(2027, 1, 5, 9, 0, tzinfo=tz))

    def test_bounded_daily_weeks_includes_today_when_time_is_upcoming(self):
        tz = ZoneInfo("America/Los_Angeles")
        now = datetime(2026, 4, 3, 16, 0, tzinfo=tz)

        with patch("skills.create_reminder.now_local", return_value=now):
            trigger_result, recurrence_rule = parse_time_expression(
                "every day the next 2 weeks at 5pm"
            )

        self.assertIsNone(recurrence_rule)
        self.assertIsInstance(trigger_result, list)
        self.assertEqual(len(trigger_result), 14)
        self.assertEqual(trigger_result[0], datetime(2026, 4, 3, 17, 0, tzinfo=tz))
        self.assertEqual(trigger_result[-1], datetime(2026, 4, 16, 17, 0, tzinfo=tz))

    def test_duplicate_single_reminder_is_suppressed(self):
        schema = """
            CREATE TABLE reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                trigger_time TEXT NOT NULL,
                status TEXT DEFAULT 'scheduled',
                created_at TEXT NOT NULL,
                triggered_at TEXT,
                acknowledged_at TEXT,
                spoken BOOLEAN DEFAULT 0,
                spoken_at TEXT,
                related_intel_file TEXT,
                callback_url TEXT,
                recurrence_rule TEXT,
                metadata TEXT,
                synced_to_other_db BOOLEAN DEFAULT 0,
                sync_timestamp TEXT
            );
        """

        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            conn = sqlite3.connect(tmp.name)
            conn.executescript(schema)
            conn.commit()
            conn.close()

            tz = ZoneInfo("America/Los_Angeles")
            trigger_time_local = datetime(2026, 4, 3, 17, 0, tzinfo=tz)
            first_now = datetime(2026, 4, 3, 23, 27, 25, tzinfo=timezone.utc)
            second_now = datetime(2026, 4, 3, 23, 27, 37, tzinfo=timezone.utc)

            with patch("skills.create_reminder.get_app_timezone", return_value=tz), \
                 patch("skills.create_reminder.sync_to_google_calendar", return_value=None), \
                 patch("skills.create_reminder.now_utc", side_effect=[first_now, first_now, second_now]):
                first = create_single_reminder(
                    title="clean dogs ears",
                    description="",
                    trigger_time_local=trigger_time_local,
                    recurrence_rule=None,
                    db_path=tmp.name,
                )
                second = create_single_reminder(
                    title="clean dogs ears",
                    description="",
                    trigger_time_local=trigger_time_local,
                    recurrence_rule=None,
                    db_path=tmp.name,
                )

            self.assertFalse(first["duplicate_suppressed"])
            self.assertTrue(second["duplicate_suppressed"])
            self.assertEqual(first["reminder_id"], second["reminder_id"])

            conn = sqlite3.connect(tmp.name)
            count = conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0]
            conn.close()
            self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
