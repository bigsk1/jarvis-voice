#!/usr/bin/env python3
"""Regression tests for reminder and alert TTS delivery accounting."""

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

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


@pytest.mark.parametrize(
    "recurrence_rule",
    ["YEARLY", "MONTHLY:nope", "MONTHLY:0", "WEEKLY:nope", "WEEKLY:7"],
)
def test_invalid_recurring_rule_falls_back_to_triggered(
    tmp_path, monkeypatch, recurrence_rule
):
    db_path = tmp_path / "reminders.db"
    original_trigger = "2026-08-18T12:00:00+00:00"
    fixed_now = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
    conn = sqlite3.connect(db_path)
    conn.execute(REMINDERS_SCHEMA)
    conn.execute(
        """
        INSERT INTO reminders (id, title, trigger_time, status, recurrence_rule)
        VALUES (1, 'Legacy recurrence', ?, 'scheduled', ?)
        """,
        (original_trigger, recurrence_rule),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(reminder_scheduler, "get_app_timezone", lambda: timezone.utc)
    monkeypatch.setattr(reminder_scheduler, "now_utc", lambda: fixed_now)

    updated = reminder_scheduler.mark_reminder_triggered(
        str(db_path),
        1,
        recurrence_rule=recurrence_rule,
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


@pytest.mark.parametrize(
    "recurrence_rule",
    ["MONTHLY:nope", "MONTHLY:0", "WEEKLY:nope", "WEEKLY:7"],
)
def test_speak_reminder_tolerates_malformed_recurrence(
    tmp_path, monkeypatch, recurrence_rule
):
    _write_script(tmp_path / "bin" / "say.sh", 0)
    monkeypatch.setattr(
        reminder_scheduler, "get_config_value", lambda _key, default=None: default
    )

    ok = reminder_scheduler.speak_reminder(
        {
            "id": 9,
            "title": "Legacy reminder",
            "description": "",
            "recurrence_rule": recurrence_rule,
        },
        "cloud",
        tmp_path,
    )

    assert ok is True


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


@pytest.mark.parametrize("speech_ok", [True, False])
def test_follow_up_marks_alert_spoken_only_after_success(tmp_path, monkeypatch, speech_ok):
    db_path = tmp_path / "alerts.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE alerts (
                id INTEGER PRIMARY KEY, title TEXT, severity TEXT, status TEXT,
                created_at TEXT, updated_at TEXT, spoken INTEGER DEFAULT 0,
                spoken_at TEXT, follow_up_count INTEGER DEFAULT 0, last_follow_up TEXT
            )
        """)
        conn.execute("""
            INSERT INTO alerts (id, title, severity, status, created_at)
            VALUES (1, 'Scheduled task failed', 'medium', 'pending', '2026-10-29T10:00:00')
        """)

    class FixedDateTime(datetime):
        current = datetime(2026, 10, 29, 11, 0)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    def stop_after_one_check(_seconds):
        raise KeyboardInterrupt

    speak = Mock(return_value=speech_ok)
    monkeypatch.setattr(follow_up_daemon, "datetime", FixedDateTime)
    monkeypatch.setattr(follow_up_daemon, "load_config", lambda: None)
    monkeypatch.setattr(follow_up_daemon, "get_active_config_mode", lambda: "cloud")
    monkeypatch.setattr(follow_up_daemon, "MemoryDB", lambda: Mock(db_path=str(db_path)))
    monkeypatch.setattr(follow_up_daemon, "ServiceLogger", lambda _name: Mock())
    monkeypatch.setattr(follow_up_daemon, "speak_follow_up", speak)
    monkeypatch.setattr(follow_up_daemon.time, "sleep", stop_after_one_check)

    follow_up_daemon.main()

    speak.assert_called_once()
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("""
            SELECT spoken, spoken_at, follow_up_count, last_follow_up, status
            FROM alerts WHERE id = 1
        """).fetchone()
    timestamp = "2026-10-29T11:00:00" if speech_ok else None
    assert row == (int(speech_ok), timestamp, int(speech_ok), timestamp, "pending")

    if speech_ok:
        # A later successful reminder updates delivery history, not the first speech time.
        FixedDateTime.current = datetime(2026, 10, 29, 12, 0)
        speak.reset_mock()
        follow_up_daemon.main()

        speak.assert_called_once()
        with sqlite3.connect(db_path) as conn:
            row = conn.execute("""
                SELECT spoken, spoken_at, follow_up_count, last_follow_up, status
                FROM alerts WHERE id = 1
            """).fetchone()
        assert row == (1, "2026-10-29T11:00:00", 2, "2026-10-29T12:00:00", "pending")
