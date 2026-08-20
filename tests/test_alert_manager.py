#!/usr/bin/env python3
"""
Regression tests for AlertManager dedupe behavior.

Run:
    python3 tests/test_alert_manager.py
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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

    @staticmethod
    def _price_config(*, threshold: float = 8, cooldown_hours: float = 24) -> dict:
        return {
            "settings": {"cooldown_hours": cooldown_hours},
            "watchlist": {
                "crypto": [{
                    "symbol": "BTC",
                    "conditions": [{"type": "percent_change_24h", "value": threshold}],
                }],
                "stocks": [],
            },
        }

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

    def test_acknowledged_price_condition_is_suppressed_during_cooldown(self):
        metadata = {
            "symbol": "BTC",
            "price": 71_000,
            "change_24h": 11,
            "type": "percent_change",
        }
        with patch(
            "api.managers.alert_manager.load_price_alert_config",
            return_value=self._price_config(),
        ):
            first_id = self.manager.create_alert(
                title="Bitcoin moved 11 percent",
                source="price_monitor",
                metadata=metadata,
                speak_immediately=False,
            )
            self.manager.acknowledge_alert(first_id)
            repeated_id = self.manager.create_alert(
                title="Bitcoin moved 11.2 percent",
                source="price_monitor",
                metadata=metadata,
                speak_immediately=False,
            )

        self.assertEqual(repeated_id, -first_id)
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT metadata FROM alerts WHERE source = 'price_monitor'"
        ).fetchall()
        conn.close()
        self.assertEqual(len(rows), 1)
        self.assertIn('"price_condition_key": "BTC:percent_change:up:8"', rows[0][0])

    def test_price_threshold_edit_bypasses_acknowledgement_cooldown(self):
        config = self._price_config(threshold=8)
        metadata = {
            "symbol": "BTC",
            "price": 71_000,
            "change_24h": 11,
            "type": "percent_change",
        }
        with patch(
            "api.managers.alert_manager.load_price_alert_config",
            side_effect=lambda: config,
        ):
            first_id = self.manager.create_alert(
                title="Bitcoin moved 11 percent",
                source="price_monitor",
                metadata=metadata,
                speak_immediately=False,
            )
            self.manager.acknowledge_alert(first_id)
            config["watchlist"]["crypto"][0]["conditions"][0]["value"] = 12
            changed_id = self.manager.create_alert(
                title="Bitcoin moved 12 percent",
                source="price_monitor",
                metadata=metadata,
                speak_immediately=False,
            )

        self.assertGreater(changed_id, 0)
        self.assertNotEqual(changed_id, first_id)

    def test_opposite_percentage_direction_bypasses_acknowledgement_cooldown(self):
        with patch(
            "api.managers.alert_manager.load_price_alert_config",
            return_value=self._price_config(),
        ):
            first_id = self.manager.create_alert(
                title="Bitcoin moved 11 percent up",
                source="price_monitor",
                metadata={
                    "symbol": "BTC",
                    "change_24h": 11,
                    "type": "percent_change",
                },
                speak_immediately=False,
            )
            self.manager.acknowledge_alert(first_id)
            changed_id = self.manager.create_alert(
                title="Bitcoin moved 11 percent down",
                source="price_monitor",
                metadata={
                    "symbol": "BTC",
                    "change_24h": -11,
                    "type": "percent_change",
                },
                speak_immediately=False,
            )

        self.assertGreater(changed_id, 0)
        self.assertNotEqual(changed_id, first_id)

    def test_price_condition_can_alert_again_after_cooldown(self):
        metadata = {
            "symbol": "BTC",
            "price": 71_000,
            "change_24h": 11,
            "type": "percent_change",
        }
        with patch(
            "api.managers.alert_manager.load_price_alert_config",
            return_value=self._price_config(),
        ):
            first_id = self.manager.create_alert(
                title="Bitcoin moved 11 percent",
                source="price_monitor",
                metadata=metadata,
                speak_immediately=False,
            )
            self.manager.acknowledge_alert(first_id)
            expired_at = (datetime.now() - timedelta(hours=25)).isoformat()
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "UPDATE alerts SET acknowledged_at = ? WHERE id = ?",
                (expired_at, first_id),
            )
            conn.commit()
            conn.close()
            next_id = self.manager.create_alert(
                title="Bitcoin moved 11 percent again",
                source="price_monitor",
                metadata=metadata,
                speak_immediately=False,
            )

        self.assertGreater(next_id, 0)
        self.assertNotEqual(next_id, first_id)

    def test_recent_legacy_percentage_alert_is_suppressed(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            """
            INSERT INTO alerts (
                title, source, status, created_at, acknowledged_at, metadata
            ) VALUES (?, 'price_monitor', 'acknowledged', ?, ?, ?)
            """,
            (
                "Bitcoin moved 11 percent",
                datetime.now().isoformat(),
                datetime.now().isoformat(),
                json.dumps({"symbol": "BTC", "type": "percent_change"}),
            ),
        )
        existing_id = cursor.lastrowid
        conn.commit()
        conn.close()

        with patch(
            "api.managers.alert_manager.load_price_alert_config",
            return_value=self._price_config(),
        ):
            repeated_id = self.manager.create_alert(
                title="Bitcoin moved 11.2 percent",
                source="price_monitor",
                metadata={"symbol": "BTC", "type": "percent_change"},
                speak_immediately=False,
            )

        self.assertEqual(repeated_id, -existing_id)

    def test_bulk_acknowledgement_stamps_legacy_price_condition(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            """
            INSERT INTO alerts (title, source, status, created_at, metadata)
            VALUES (?, 'price_monitor', 'pending', ?, ?)
            """,
            (
                "Bitcoin moved 11 percent up",
                datetime.now().isoformat(),
                json.dumps({
                    "symbol": "BTC",
                    "type": "percent_change",
                    "change_24h": 11,
                }),
            ),
        )
        existing_id = cursor.lastrowid
        conn.commit()
        conn.close()

        config = self._price_config(threshold=8)
        with patch(
            "api.managers.alert_manager.load_price_alert_config",
            side_effect=lambda: config,
        ):
            count = self.manager.acknowledge_all(status="pending")
            config["watchlist"]["crypto"][0]["conditions"][0]["value"] = 12
            changed_id = self.manager.create_alert(
                title="Bitcoin moved 12 percent up",
                source="price_monitor",
                metadata={
                    "symbol": "BTC",
                    "type": "percent_change",
                    "change_24h": 12,
                },
                speak_immediately=False,
            )

        self.assertEqual(count, 1)
        self.assertGreater(changed_id, 0)
        self.assertNotEqual(changed_id, existing_id)
        conn = sqlite3.connect(self.db_path)
        metadata_json = conn.execute(
            "SELECT metadata FROM alerts WHERE id = ?",
            (existing_id,),
        ).fetchone()[0]
        conn.close()
        self.assertIn(
            '"price_condition_key": "BTC:percent_change:up:8"',
            metadata_json,
        )

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

    def test_list_alerts_supports_filtered_pagination_and_search(self):
        alert_ids = []
        for index in range(5):
            alert_ids.append(self.manager.create_alert(
                title=f"Camera event {index}",
                source="unifi-protect",
                description=f"Person detected at zone {index}",
                severity="high",
                speak_immediately=False,
            ))
        self.manager.acknowledge_alert(alert_ids[3])

        first_page = self.manager.list_alerts(status="pending", limit=2, offset=0)
        second_page = self.manager.list_alerts(status="pending", limit=2, offset=2)
        search_results = self.manager.list_alerts(search="zone 1", limit=10)

        self.assertEqual([item["id"] for item in first_page], [alert_ids[4], alert_ids[2]])
        self.assertEqual([item["id"] for item in second_page], [alert_ids[1], alert_ids[0]])
        self.assertEqual([item["id"] for item in search_results], [alert_ids[1]])

    def test_alert_speech_failure_leaves_alert_unspoken(self):
        alert_id = self.manager.create_alert(
            title="Person at front door",
            source="unifi-protect",
            severity="high",
            speak_immediately=False,
        )
        self.manager._speak = lambda *_args, **_kwargs: False

        spoken = self.manager._speak_alert(
            alert_id,
            "Person at front door",
            "high",
            source="unifi-protect",
        )

        conn = sqlite3.connect(self.db_path)
        row = conn.execute("SELECT spoken, spoken_at FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        conn.close()

        self.assertFalse(spoken)
        self.assertEqual(row[0], 0)
        self.assertIsNone(row[1])

    def test_alert_speech_success_marks_alert_spoken(self):
        alert_id = self.manager.create_alert(
            title="Person at front door",
            source="unifi-protect",
            severity="high",
            speak_immediately=False,
        )
        self.manager._speak = lambda *_args, **_kwargs: True

        spoken = self.manager._speak_alert(
            alert_id,
            "Person at front door",
            "high",
            source="unifi-protect",
        )

        conn = sqlite3.connect(self.db_path)
        row = conn.execute("SELECT spoken, spoken_at FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        conn.close()

        self.assertTrue(spoken)
        self.assertEqual(row[0], 1)
        self.assertIsNotNone(row[1])


if __name__ == "__main__":
    unittest.main()
