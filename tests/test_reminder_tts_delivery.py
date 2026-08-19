#!/usr/bin/env python3
"""Regression tests for reminder and alert TTS delivery accounting."""

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services import follow_up_daemon, reminder_scheduler  # noqa: E402


REMINDERS_SCHEMA = """
CREATE TABLE reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    trigger_time TEXT NOT NULL,
    status TEXT DEFAULT 'scheduled',
    triggered_at TEXT,
    spoken INTEGER DEFAULT 0,
    spoken_at TEXT,
    recurrence_rule TEXT
)
"""


def _write_script(path: Path, exit_code: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/bash\nexit {exit_code}\n")
    path.chmod(0o755)


def test_speak_reminder_reports_script_failure(tmp_path, monkeypatch):
    _write_script(tmp_path / "bin" / "say.sh", 1)
    monkeypatch.setattr(reminder_scheduler, "get_config_value", lambda _key, default=None: default)

    ok = reminder_scheduler.speak_reminder(
        {"id": 7, "title": "Check backup", "description": ""},
        "cloud",
        tmp_path,
    )

    assert ok is False


def test_speak_reminder_reports_script_success(tmp_path, monkeypatch):
    _write_script(tmp_path / "bin" / "say.sh", 0)
    monkeypatch.setattr(reminder_scheduler, "get_config_value", lambda _key, default=None: default)

    ok = reminder_scheduler.speak_reminder(
        {"id": 8, "title": "Check backup", "description": ""},
        "cloud",
        tmp_path,
    )

    assert ok is True


def test_failed_reminder_speech_marks_triggered_but_unspoken(tmp_path):
    db_path = tmp_path / "reminders.db"
    conn = sqlite3.connect(db_path)
    conn.execute(REMINDERS_SCHEMA)
    conn.execute(
        "INSERT INTO reminders (id, title, trigger_time, status) VALUES (1, 'Check backup', '2026-07-10T12:00:00+00:00', 'scheduled')"
    )
    conn.commit()
    conn.close()

    reminder_scheduler.mark_reminder_triggered(str(db_path), 1, spoken=False)

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT status, triggered_at, spoken, spoken_at FROM reminders WHERE id = 1"
    ).fetchone()
    conn.close()

    assert row[0] == "triggered"
    assert row[1] is not None
    assert row[2] == 0
    assert row[3] is None


def test_failed_recurring_reminder_speech_does_not_advance_recurrence(tmp_path):
    db_path = tmp_path / "reminders.db"
    original_trigger = "2026-07-10T12:00:00+00:00"
    conn = sqlite3.connect(db_path)
    conn.execute(REMINDERS_SCHEMA)
    conn.execute(
        """
        INSERT INTO reminders (id, title, trigger_time, status, recurrence_rule)
        VALUES (1, 'Daily standup', ?, 'scheduled', 'DAILY')
        """,
        (original_trigger,),
    )
    conn.commit()
    conn.close()

    reminder_scheduler.mark_reminder_triggered(
        str(db_path),
        1,
        recurrence_rule="DAILY",
        current_trigger=original_trigger,
        spoken=False,
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT status, trigger_time, spoken, spoken_at FROM reminders WHERE id = 1"
    ).fetchone()
    conn.close()

    assert row[0] == "triggered"
    assert row[1] == original_trigger
    assert row[2] == 0
    assert row[3] is None


def test_unknown_recurring_rule_falls_back_to_triggered(tmp_path, monkeypatch):
    db_path = tmp_path / "reminders.db"
    original_trigger = "2026-08-18T12:00:00+00:00"
    fixed_now = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
    conn = sqlite3.connect(db_path)
    conn.execute(REMINDERS_SCHEMA)
    conn.execute(
        """
        INSERT INTO reminders (id, title, trigger_time, status, recurrence_rule)
        VALUES (1, 'Legacy recurrence', ?, 'scheduled', 'YEARLY')
        """,
        (original_trigger,),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(reminder_scheduler, "get_app_timezone", lambda: timezone.utc)
    monkeypatch.setattr(reminder_scheduler, "now_utc", lambda: fixed_now)

    updated = reminder_scheduler.mark_reminder_triggered(
        str(db_path),
        1,
        recurrence_rule="YEARLY",
        current_trigger=original_trigger,
        spoken=True,
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        """
        SELECT status, trigger_time, triggered_at, spoken, spoken_at
        FROM reminders WHERE id = 1
        """
    ).fetchone()
    conn.close()

    assert updated is True
    assert row == (
        "triggered",
        original_trigger,
        fixed_now.isoformat(),
        1,
        fixed_now.isoformat(),
    )


def test_overdue_weekly_reminder_fast_forwards_to_next_future_occurrence(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "reminders.db"
    original_trigger = "2026-04-09T22:00:00+00:00"
    fixed_now = datetime(2026, 8, 7, 18, 36, tzinfo=timezone.utc)
    conn = sqlite3.connect(db_path)
    conn.execute(REMINDERS_SCHEMA)
    conn.execute(
        """
        INSERT INTO reminders (id, title, trigger_time, status, recurrence_rule)
        VALUES (1, 'Take medication', ?, 'scheduled', 'WEEKLY:3')
        """,
        (original_trigger,),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(reminder_scheduler, "get_app_timezone", lambda: timezone.utc)
    monkeypatch.setattr(reminder_scheduler, "now_utc", lambda: fixed_now)

    reminder_scheduler.mark_reminder_triggered(
        str(db_path),
        1,
        recurrence_rule="WEEKLY:3",
        current_trigger=original_trigger,
        spoken=True,
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT status, trigger_time, spoken FROM reminders WHERE id = 1"
    ).fetchone()
    conn.close()

    assert row == ("scheduled", "2026-08-13T22:00:00", 1)


def test_recurring_reschedule_does_not_overwrite_state_changed_during_playback(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "reminders.db"
    original_trigger = "2026-08-06T22:00:00+00:00"
    conn = sqlite3.connect(db_path)
    conn.execute(REMINDERS_SCHEMA)
    conn.execute(
        """
        INSERT INTO reminders (id, title, trigger_time, status, recurrence_rule)
        VALUES (1, 'Take medication', ?, 'canceled', 'WEEKLY:3')
        """,
        (original_trigger,),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(reminder_scheduler, "get_app_timezone", lambda: timezone.utc)
    monkeypatch.setattr(
        reminder_scheduler,
        "now_utc",
        lambda: datetime(2026, 8, 7, 18, 36, tzinfo=timezone.utc),
    )

    updated = reminder_scheduler.mark_reminder_triggered(
        str(db_path),
        1,
        recurrence_rule="WEEKLY:3",
        current_trigger=original_trigger,
        spoken=True,
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT status, trigger_time, spoken FROM reminders WHERE id = 1"
    ).fetchone()
    conn.close()

    assert updated is False
    assert row == ("canceled", original_trigger, 0)


def test_speak_follow_up_reports_script_failure(tmp_path, monkeypatch):
    _write_script(tmp_path / "bin" / "say-status.sh", 1)
    monkeypatch.setattr(follow_up_daemon, "get_config_value", lambda _key, default=None: default)

    ok = follow_up_daemon.speak_follow_up(
        {"id": 9, "title": "Person at front door", "severity": "high", "follow_up_count": 0},
        "cloud",
        tmp_path,
    )

    assert ok is False
