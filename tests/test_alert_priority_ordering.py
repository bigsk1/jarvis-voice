"""Regression tests for alert severity ordering in background daemons."""

import sqlite3

from services import follow_up_daemon, self_healing_daemon

ALERTS_SCHEMA = """
CREATE TABLE alerts (
    id INTEGER PRIMARY KEY,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    follow_up_count INTEGER DEFAULT 0,
    auto_resolve_url TEXT
)
"""


def _create_alert_db(tmp_path, alerts):
    db_path = tmp_path / "alerts.db"
    conn = sqlite3.connect(db_path)
    conn.execute(ALERTS_SCHEMA)
    conn.executemany(
        """
        INSERT INTO alerts (
            id, severity, status, created_at, follow_up_count, auto_resolve_url
        ) VALUES (?, ?, 'pending', ?, 0, ?)
        """,
        alerts,
    )
    conn.commit()
    conn.close()
    return db_path


def test_follow_up_alerts_are_ordered_by_priority(tmp_path):
    created_at = "2026-08-19T08:00:00"
    db_path = _create_alert_db(
        tmp_path,
        [
            (1, "critical", created_at, None),
            (2, "high", created_at, None),
            (3, "medium", created_at, None),
            (4, "low", created_at, None),
        ],
    )

    alerts = follow_up_daemon.get_pending_alerts(str(db_path))

    assert [alert["severity"] for alert in alerts] == [
        "critical",
        "high",
        "medium",
        "low",
    ]


def test_auto_resolve_limit_keeps_critical_alerts_first(tmp_path, monkeypatch):
    monkeypatch.setattr(self_healing_daemon, "MAX_CHECKS_PER_LOOP", 10)
    alerts = [
        (index, "medium", f"2026-08-19T08:00:{index:02d}", "https://example.com")
        for index in range(1, 11)
    ]
    alerts.extend(
        [
            (11, "high", "2026-08-19T08:01:00", "https://example.com"),
            (12, "critical", "2026-08-19T08:02:00", "https://example.com"),
        ]
    )
    db_path = _create_alert_db(tmp_path, alerts)

    selected = self_healing_daemon.get_alerts_to_check(str(db_path))

    assert len(selected) == 10
    assert [alert["severity"] for alert in selected[:2]] == ["critical", "high"]
