#!/usr/bin/env python3
"""
Regression tests for AlertManager dedupe behavior.

Run:
    python3 tests/test_alert_manager.py
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from api.managers.alert_manager import AlertManager


ALERTS_SCHEMA = """
CREATE TABLE alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    severity TEXT CHECK(severity IN ('low', 'medium', 'high', 'critical')) DEFAULT 'medium',
    source TEXT NOT NULL,
    status TEXT CHECK(status IN ('pending', 'acknowledged', 'auto_resolved', 'canceled')) DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT,
    acknowledged_at TEXT,
    resolved_at TEXT,
    spoken BOOLEAN DEFAULT 0,
    spoken_at TEXT,
    follow_up_count INTEGER DEFAULT 0,
    last_follow_up TEXT,
    auto_resolve_url TEXT,
    auto_resolve_check_interval INTEGER DEFAULT 300,
    last_check_at TEXT,
    metadata TEXT,
    related_intel_file TEXT,
    synced_to_other_db BOOLEAN DEFAULT 0,
    sync_timestamp TEXT
)
"""


class AlertManagerDedupeTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "alerts.db")
        conn = sqlite3.connect(self.db_path)
        conn.execute(ALERTS_SCHEMA)
        conn.commit()
        conn.close()

        self.manager = AlertManager(mode="cloud")
        self.manager.db = SimpleNamespace(db_path=self.db_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_dedupe_key_suppresses_same_condition(self):
        first_id = self.manager.create_alert(
            title="Cold watch",
            source="weather_watch",
            severity="high",
            metadata={"dedupe_key": "weather_watch:cold:2026-04-03:Portland, Oregon"},
            speak_immediately=False,
        )
        second_id = self.manager.create_alert(
            title="Cold watch",
            source="weather_watch",
            severity="high",
            metadata={"dedupe_key": "weather_watch:cold:2026-04-03:Portland, Oregon"},
            speak_immediately=False,
        )

        self.assertGreater(first_id, 0)
        self.assertEqual(second_id, -first_id)

    def test_different_condition_keys_can_exist_same_day(self):
        cold_id = self.manager.create_alert(
            title="Cold watch",
            source="weather_watch",
            severity="high",
            metadata={"dedupe_key": "weather_watch:cold:2026-04-03:Portland, Oregon"},
            speak_immediately=False,
        )
        wind_id = self.manager.create_alert(
            title="Wind advisory",
            source="weather_watch",
            severity="high",
            metadata={"dedupe_key": "weather_watch:wind:2026-04-03:Portland, Oregon"},
            speak_immediately=False,
        )

        self.assertGreater(cold_id, 0)
        self.assertGreater(wind_id, 0)
        self.assertNotEqual(cold_id, wind_id)

    def test_weather_watch_speech_sanitizes_iso_dates(self):
        spoken = self.manager._sanitize_weather_watch_speech(
            "Forecast low 34F tonight meets the cold watch threshold of 34F for Portland, Oregon. "
            "Fri 2026-04-03 high 61F with partly cloudy. Sat 2026-04-04 low 40F, high 70F, condition overcast."
        )

        self.assertNotIn("2026-04-03", spoken)
        self.assertNotIn("2026-04-04", spoken)
        self.assertIn("Fri high 61F", spoken)
        self.assertIn("Sat low 40F", spoken)

    def test_weather_watch_speech_normalizes_degree_symbols(self):
        spoken = self.manager._sanitize_weather_watch_speech(
            "Forecast low 34°F tonight. Backup note: 10°C tomorrow morning."
        )

        self.assertIn("34 degrees", spoken)
        self.assertIn("10 degrees Celsius", spoken)
        self.assertNotIn("°F", spoken)
        self.assertNotIn("°C", spoken)


if __name__ == "__main__":
    unittest.main()
