"""Regression coverage for reactivating explicitly rescheduled reminders."""

import sqlite3
from types import SimpleNamespace

from api.managers.reminder_manager import ReminderManager


def _manager_for(db_path):
    manager = ReminderManager.__new__(ReminderManager)
    manager.db = SimpleNamespace(db_path=str(db_path))
    return manager


def test_update_can_reactivate_triggered_reminder(tmp_path):
    db_path = tmp_path / "reminders.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE reminders (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            trigger_time TEXT NOT NULL,
            status TEXT,
            triggered_at TEXT,
            acknowledged_at TEXT,
            spoken INTEGER DEFAULT 0,
            spoken_at TEXT,
            related_intel_file TEXT,
            callback_url TEXT,
            recurrence_rule TEXT,
            metadata TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO reminders (
            id, title, trigger_time, status, triggered_at,
            acknowledged_at, spoken, spoken_at
        ) VALUES (1, 'Calendar event', '2026-07-07T14:00:00Z',
                  'triggered', 'old-trigger', 'old-ack', 1, 'old-spoken')
        """
    )
    conn.commit()
    conn.close()

    manager = _manager_for(db_path)

    assert manager.update_reminder(
        reminder_id=1,
        title="Calendar event",
        trigger_time="2026-07-07T16:00:00Z",
        reactivate=True,
    ) is True

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        """
        SELECT trigger_time, status, triggered_at, acknowledged_at, spoken, spoken_at
        FROM reminders WHERE id = 1
        """
    ).fetchone()
    conn.close()

    assert row == ("2026-07-07T16:00:00Z", "scheduled", None, None, 0, None)


def test_acknowledge_does_not_revive_canceled_reminder(tmp_path):
    db_path = tmp_path / "reminders.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE reminders (
            id INTEGER PRIMARY KEY,
            trigger_time TEXT NOT NULL,
            status TEXT,
            acknowledged_at TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO reminders (id, trigger_time, status)
        VALUES (1, '2026-07-07T14:00:00Z', 'canceled')
        """
    )
    conn.commit()
    conn.close()

    manager = _manager_for(db_path)

    assert manager.acknowledge_reminder(1) is False

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT status, acknowledged_at FROM reminders WHERE id = 1"
    ).fetchone()
    conn.close()

    assert row == ("canceled", None)


def test_acknowledge_triggered_reminder_still_succeeds(tmp_path):
    db_path = tmp_path / "reminders.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE reminders (
            id INTEGER PRIMARY KEY,
            trigger_time TEXT NOT NULL,
            status TEXT,
            acknowledged_at TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO reminders (id, trigger_time, status)
        VALUES (1, '2026-07-07T14:00:00Z', 'triggered')
        """
    )
    conn.commit()
    conn.close()

    manager = _manager_for(db_path)

    assert manager.acknowledge_reminder(1) is True

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT status, acknowledged_at FROM reminders WHERE id = 1"
    ).fetchone()
    conn.close()

    assert row[0] == "acknowledged"
    assert row[1] is not None
