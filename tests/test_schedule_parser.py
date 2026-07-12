#!/usr/bin/env python3
"""
Regression tests for scheduled-task natural language parsing.

Run:
    python3 tests/test_schedule_parser.py
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from schedule_parser import parse_schedule_expression


class ScheduleParserTests(unittest.TestCase):
    def test_everyday_at_time_parses_as_daily(self):
        result = parse_schedule_expression("everyday at 9am", tz_name="America/Los_Angeles")

        self.assertEqual(result["schedule_type"], "daily")
        self.assertEqual(result["schedule_expr"], {"hour": 9, "minute": 0})
        self.assertEqual(result["summary"], "Every day at 9:00 AM")
        self.assertIsNotNone(result["next_run_at"])

    def test_every_day_at_time_still_parses_as_daily(self):
        result = parse_schedule_expression("every day at 9am", tz_name="America/Los_Angeles")

        self.assertEqual(result["schedule_type"], "daily")
        self.assertEqual(result["summary"], "Every day at 9:00 AM")

    def test_now_parses_as_immediate_one_shot(self):
        result = parse_schedule_expression("now", tz_name="America/Los_Angeles")

        self.assertEqual(result["schedule_type"], "once")
        self.assertEqual(result["summary"], "Once immediately")
        self.assertEqual(result["next_run_at"], result["schedule_expr"]["run_at_utc"])


if __name__ == "__main__":
    unittest.main()
