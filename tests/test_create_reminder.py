#!/usr/bin/env python3
"""
Regression tests for reminder parsing and duplicate suppression.

Run:
    python3 tests/test_create_reminder.py
"""

import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from skills.create_reminder import (
    create_single_reminder,
    format_local_time,
    main,
    parse_time_expression,
)


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

    def test_format_local_time_omits_year_within_current_year(self):
        tz = ZoneInfo("America/Los_Angeles")
        dt = datetime(2026, 5, 1, 18, 0, tzinfo=tz)
        now = datetime(2026, 4, 26, 17, 59, 7, tzinfo=tz)

        with patch("skills.create_reminder.get_app_timezone", return_value=tz), \
             patch("skills.create_reminder.now_local", return_value=now):
            self.assertEqual(format_local_time(dt), "Friday, May 01 at 06:00 PM PDT")

    def test_format_local_time_includes_year_when_outside_current_year(self):
        tz = ZoneInfo("America/Los_Angeles")
        dt = datetime(2027, 4, 1, 10, 0, tzinfo=tz)
        now = datetime(2026, 5, 21, 10, 0, tzinfo=tz)

        with patch("skills.create_reminder.get_app_timezone", return_value=tz), \
             patch("skills.create_reminder.now_local", return_value=now):
            self.assertEqual(
                format_local_time(dt),
                "Thursday, April 01, 2027 at 10:00 AM PDT",
            )

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


class ReminderCreationIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.db_path = str(Path(temporary.name) / "reminders.db")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT, description TEXT, trigger_time TEXT, status TEXT,
                    created_at TEXT, spoken INTEGER, spoken_at TEXT, triggered_at TEXT,
                    acknowledged_at TEXT, callback_url TEXT, recurrence_rule TEXT,
                    related_intel_file TEXT, metadata TEXT
                )
            """)
        self.tz = ZoneInfo("America/Los_Angeles")
        self.now = datetime(2026, 10, 15, 10, tzinfo=self.tz)
        patches = {
            "load_config": None,
            "MemoryDB": SimpleNamespace(db_path=self.db_path),
            "get_app_timezone": self.tz,
            "now_local": self.now,
            "now_utc": self.now.astimezone(timezone.utc),
            "get_config_value": None,
        }
        for name, value in patches.items():
            patcher = patch(f"skills.create_reminder.{name}", return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        post_patcher = patch("skills.create_reminder.requests.post")
        self.post = post_patcher.start()
        self.addCleanup(post_patcher.stop)
        self.arguments = {
            "title": "Appointment at 2pm",
            "description": "Don't forget your appointment at 2pm.",
            "when": "tomorrow at noon",
        }

    def run_main(self) -> dict:
        output = io.StringIO()
        with patch("sys.argv", ["create_reminder.py", json.dumps(self.arguments)]), \
             redirect_stdout(output):
            main()
        return json.loads(output.getvalue())

    def saved_rows(self) -> list:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute("SELECT * FROM reminders ORDER BY id").fetchall()

    def test_noon_notification_preserves_later_appointment_without_calendar(self):
        result = self.run_main()

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["trigger_time"], "2026-10-16T19:00:00")
        self.assertIn("12:00 PM", result["speech"])
        self.assertIn("Appointment at 2pm", result["speech"])
        self.assertFalse(result["data"]["gcal_synced"])
        rows = self.saved_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], self.arguments["title"])
        self.assertEqual(rows[0]["description"], self.arguments["description"])
        self.assertEqual(rows[0]["trigger_time"], "2026-10-16T19:00:00")
        self.assertEqual(rows[0]["status"], "scheduled")
        self.post.assert_not_called()

    def test_optional_calendar_sync_happens_once_and_duplicate_reuses_local_reminder(self):
        self.post.return_value.ok = True
        self.post.return_value.json.return_value = {
            "ok": True,
            "gcal_event_id": "test-event",
            "gcal_calendar_id": "test-calendar",
        }
        with patch("skills.create_reminder.get_config_value", return_value="https://example.test/hook"):
            first = self.run_main()
            duplicate = self.run_main()

        self.assertTrue(first["ok"])
        self.assertTrue(first["data"]["gcal_synced"])
        self.assertTrue(duplicate["ok"])
        self.assertTrue(duplicate["data"]["duplicate_suppressed"])
        self.assertEqual(first["data"]["reminder_id"], duplicate["data"]["reminder_id"])
        self.assertIn("already exists", duplicate["speech"])
        rows = self.saved_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0]["metadata"])["gcal_event_id"], "test-event")
        self.post.assert_called_once()
        self.assertEqual(self.post.call_args.kwargs["json"]["reminder"]["trigger_time"],
                         "2026-10-16T19:00:00Z")

    def test_mixed_notification_and_appointment_times_fail_before_database_access(self):
        for when in (
            "October 23rd at noon about my appointment at 2pm",
            "tomorrow at noon about my appointment at 2pm",
            "October 23rd at 2pm with a notification at noon",
            "October 23rd at 14:00 and 16:00",
            "tomorrow at 8:00am and 14:00",
            "next 5 days at 14:00 and 16:00",
            "October 23rd at 2pm (2026-10-23T16:00:00-07:00)",
        ):
            with self.subTest(when=when):
                self.arguments["when"] = when
                output = io.StringIO()
                with patch("sys.argv", ["create_reminder.py", json.dumps(self.arguments)]), \
                     redirect_stdout(output), patch("skills.create_reminder.MemoryDB") as database:
                    with self.assertRaises(SystemExit) as exit_info:
                        main()
                self.assertEqual(exit_info.exception.code, 1)
                result = json.loads(output.getvalue())
                self.assertFalse(result["ok"])
                self.assertEqual(result["error_code"], "invalid_reminder_schedule")
                self.assertIn("No reminder was created", result["error"])
                self.assertNotIn("Send only", result["speech"])
                database.assert_not_called()
                self.assertEqual(len(self.saved_rows()), 0)
                self.post.assert_not_called()

        self.arguments["when"] = "October 23rd at noon"
        result = self.run_main()
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["trigger_time"], "2026-10-23T19:00:00")
        self.assertEqual(len(self.saved_rows()), 1)

    def test_equivalent_noon_expressions_are_one_time(self):
        self.arguments["when"] = "October 23rd at noon (12pm)"
        result = self.run_main()
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["trigger_time"], "2026-10-23T19:00:00")
        self.assertEqual(len(self.saved_rows()), 1)

    def test_database_failure_is_not_mislabeled_as_safe_schedule_rejection(self):
        output = io.StringIO()
        with patch("sys.argv", ["create_reminder.py", json.dumps(self.arguments)]), \
             redirect_stdout(output), \
             patch("skills.create_reminder.MemoryDB", side_effect=ValueError("Database unavailable")):
            with self.assertRaises(SystemExit):
                main()
        result = json.loads(output.getvalue())
        self.assertFalse(result["ok"])
        self.assertNotIn("error_code", result)
        self.assertEqual(result["error"], "Database unavailable")
        self.assertEqual(len(self.saved_rows()), 0)
        self.post.assert_not_called()

    def test_single_clock_minutes_are_preserved(self):
        for when, expected in (
            ("tomorrow at 8:00am", "2026-10-16T15:00:00"),
            ("tomorrow at 2:00pm", "2026-10-16T21:00:00"),
            ("tomorrow at 1:30pm", "2026-10-16T20:30:00"),
            ("tomorrow at 12:15am", "2026-10-16T07:15:00"),
            ("tomorrow at 12:05 p.m.", "2026-10-16T19:05:00"),
            ("October 23rd at 8:25am", "2026-10-23T15:25:00"),
        ):
            with self.subTest(when=when):
                self.arguments["when"] = when
                result = self.run_main()
                self.assertEqual(result["data"]["trigger_time"], expected)
        self.assertEqual(len(self.saved_rows()), 6)
        self.post.assert_not_called()

    def test_equivalent_24_hour_clock_and_iso_offset_are_not_extra_schedules(self):
        for when in (
            "October 23rd at 14:00 (2pm)",
            "October 23rd at 2pm (2026-10-23T14:00:00-07:00)",
            "October 23rd at 2pm (2026-10-23T14:00:00+02:00)",
        ):
            with self.subTest(when=when):
                self.arguments["when"] = when
                result = self.run_main()
                self.assertTrue(result["ok"])
                self.assertEqual(result["data"]["trigger_time"], "2026-10-23T21:00:00")
        self.assertEqual(len(self.saved_rows()), 1)
        self.post.assert_not_called()

    def test_repeated_bounded_schedule_reports_reused_reminders(self):
        self.arguments["when"] = "next 2 days at 8:00am"
        first = self.run_main()
        repeated = self.run_main()
        self.arguments["when"] = "next 3 days at 8:00am"
        extended = self.run_main()

        self.assertEqual(first["data"]["reminders_created"], 2)
        # Keep the legacy occurrence count while exposing actual insert/reuse counts.
        self.assertEqual(repeated["data"]["reminders_created"], 2)
        self.assertEqual(repeated["data"]["newly_created_count"], 0)
        self.assertEqual(repeated["data"]["reminders_reused"], 2)
        self.assertEqual(repeated["data"]["reminders_total"], 2)
        self.assertIn("already exist", repeated["speech"])
        self.assertNotIn("Created", repeated["speech"])
        self.assertEqual(extended["data"]["reminders_created"], 3)
        self.assertEqual(extended["data"]["newly_created_count"], 1)
        self.assertEqual(extended["data"]["reminders_reused"], 2)
        self.assertIn("Created 1 reminder and reused 2", extended["speech"])
        rows = self.saved_rows()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["trigger_time"], "2026-10-16T15:00:00")
        self.post.assert_not_called()

    def test_calendar_sync_failure_keeps_successful_local_reminder(self):
        self.post.side_effect = TimeoutError("mock Calendar timeout")
        with patch("skills.create_reminder.get_config_value", return_value="https://example.test/hook"), \
             patch("sys.stderr", new_callable=io.StringIO):
            result = self.run_main()

        self.assertTrue(result["ok"])
        self.assertFalse(result["data"]["gcal_synced"])
        self.assertNotIn("Also added to Google Calendar", result["speech"])
        rows = self.saved_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["trigger_time"], "2026-10-16T19:00:00")
        self.assertIsNone(rows[0]["metadata"])
        self.post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
