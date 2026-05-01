#!/usr/bin/env python3
"""Regression tests for timezone display helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from time_utils import attach_local_display_fields


class TimeUtilsTests(unittest.TestCase):
    def test_attach_local_display_fields_converts_naive_utc_db_values(self) -> None:
        tz = ZoneInfo("America/Los_Angeles")
        record = {
            "created_at": "2026-05-01 00:53:12",
            "updated_at": "2026-05-01 00:53:12",
        }

        enriched = attach_local_display_fields(record, tz=tz)

        self.assertEqual(enriched["created_at"], "2026-05-01 00:53:12")
        self.assertEqual(enriched["created_at_local"], "2026-04-30T17:53:12-07:00")
        self.assertEqual(enriched["created_at_local_display"], "2026-04-30 5:53 PM PDT")
        self.assertEqual(enriched["updated_at_timezone"], "America/Los_Angeles")

    def test_attach_local_display_fields_handles_explicit_utc_z_values(self) -> None:
        tz = ZoneInfo("America/Los_Angeles")
        record = {
            "timestamp": "2026-05-01T07:44:00Z",
        }

        enriched = attach_local_display_fields(record, tz=tz)

        self.assertEqual(enriched["timestamp_local"], "2026-05-01T00:44:00-07:00")
        self.assertEqual(enriched["timestamp_local_display"], "2026-05-01 12:44 AM PDT")


if __name__ == "__main__":
    unittest.main()
