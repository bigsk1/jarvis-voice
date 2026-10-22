"""Provider-neutral saved notifications; transports run in the existing worker.

Content is retained for 90 days. Identity and delivery receipts outlive content
so repeating an old idempotency key never recreates a phone notification.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import time
import uuid
from collections.abc import Callable
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

CHANNELS = frozenset({"ntfy"})
STATES = frozenset({"pending", "delivered", "failed", "suppressed", "unavailable", "saved"})
SOURCE_TYPES = frozenset({"notifications", "alerts", "reminders", "background_tasks"})
CONTENT_RETENTION_SECONDS = 90 * 86400


def _text(value, name, limit, *, multiline=False):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > limit
        or any(ord(char) < 32 and (not multiline or char not in "\n\r\t") for char in value)
    ):
        raise ValueError(f"{name} must be nonempty text of at most {limit} characters")
    return value.strip()


def _iso(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat()


def _safe_error(error):
    if error is None:
        return None
    if re.fullmatch(r"ntfy HTTP [0-9]{3}|ntfy [A-Za-z]+Error", str(error)):
        return str(error)
    if error in {
        "ntfy_unconfigured",
        "ntfy_disabled",
        "ntfy_invalid_configuration",
        "ntfy_notifications_disabled",
        "expired",
        "channel_disabled",
    }:
        return error
    return "delivery_failed"


def ntfy_readiness(root: Path) -> tuple[dict | None, str | None]:
    """Read only the canonical JSON config; never expose config in a result."""
    from lib.ntfy_notifications import load_config

    path = Path(root) / "config" / "ntfy.json"
    try:
        if not path.exists():
            return None, "ntfy_unconfigured"
        config = load_config(path)
    except Exception:
        return None, "ntfy_invalid_configuration"
    if not config["enabled"]:
        return None, "ntfy_disabled"
    if not config["notifications"]["enabled"]:
        return None, "ntfy_notifications_disabled"
    return config, None


class NotificationStore:
    """Mode-scoped notification history with independently tracked transports."""

    def __init__(self, root: Path, mode: str) -> None:
        """Use the existing delivery database without creating it until needed."""
        if not isinstance(mode, str) or mode not in {"cloud", "local"}:
            raise ValueError("Invalid notification mode")
        self.root, self.mode = Path(root), mode
        self.path = self.root / "data" / "ntfy_notifications.db"

    def _connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        conn = sqlite3.connect(self.path, timeout=3)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS notification_events (
                id TEXT PRIMARY KEY, mode TEXT NOT NULL, title TEXT NOT NULL,
                message TEXT NOT NULL, source TEXT NOT NULL, created_at REAL NOT NULL,
                expires_at REAL NOT NULL, dedupe_key TEXT, content_retained INTEGER NOT NULL DEFAULT 1
            );
            CREATE UNIQUE INDEX IF NOT EXISTS notification_events_dedupe
                ON notification_events(mode,source,dedupe_key) WHERE dedupe_key IS NOT NULL;
            CREATE INDEX IF NOT EXISTS notification_events_history ON notification_events(mode,created_at);
            CREATE TABLE IF NOT EXISTS notification_channel_deliveries (
                notification_id TEXT NOT NULL REFERENCES notification_events(id),
                channel TEXT NOT NULL, state TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, next_try REAL NOT NULL DEFAULT 0,
                error TEXT, sent_at TEXT, receipt TEXT,
                PRIMARY KEY(notification_id,channel)
            );
            CREATE INDEX IF NOT EXISTS notification_channel_pending
                ON notification_channel_deliveries(channel,state,next_try);
        """)
        return conn

    @staticmethod
    def _retain(conn, now):
        cutoff = now - CONTENT_RETENTION_SECONDS
        count = conn.execute(
            """UPDATE notification_channel_deliveries SET state='suppressed',error='expired'
            WHERE state='pending' AND notification_id IN
            (SELECT id FROM notification_events WHERE expires_at<=?)""",
            (now,),
        ).rowcount
        conn.execute(
            """UPDATE notification_events SET title='',message='',content_retained=0
            WHERE content_retained=1 AND created_at<?""",
            (cutoff,),
        )
        return count

    @staticmethod
    def _item(conn, row, *, deduplicated=False):
        deliveries = []
        for channel in conn.execute(
            """SELECT channel,state,error,sent_at
            FROM notification_channel_deliveries WHERE notification_id=? ORDER BY channel""",
            (row["id"],),
        ):
            delivery = {"channel": channel["channel"], "state": channel["state"]}
            if channel["error"]:
                delivery["error"] = _safe_error(channel["error"])
            if channel["sent_at"]:
                delivery["sent_at"] = channel["sent_at"]
            deliveries.append(delivery)
        states = {item["state"] for item in deliveries}
        state = next(
            (
                name
                for name in ("pending", "failed", "unavailable", "suppressed", "delivered")
                if name in states
            ),
            "saved",
        )
        return {
            "id": row["id"],
            "title": row["title"],
            "message": row["message"],
            "source": row["source"],
            "source_type": "notifications",
            "source_id": row["id"],
            "mode": row["mode"],
            "created_at": _iso(row["created_at"]),
            "deduplicated": deduplicated,
            "content_expired": not bool(row["content_retained"]),
            "state": state,
            "deliveries": deliveries,
        }

    def create(
        self,
        title: str,
        message: str,
        source: str = "manual",
        channels: list[str] | None = None,
        dedupe_key: str | None = None,
        max_age_seconds: int = 3600,
    ) -> dict:
        """Save once; unavailable transports are recorded without blocking history.

        Omitted channels request ntfy; an empty list saves only local history.
        A duplicate mode/source/key returns its original receipt without replay.
        """
        title = _text(title, "title", 200)
        message = _text(message, "message", 2000, multiline=True)
        source = _text(source, "source", 80)
        if dedupe_key is not None:
            dedupe_key = _text(dedupe_key, "dedupe_key", 200)
        if type(max_age_seconds) is not int or not 60 <= max_age_seconds <= 86400:
            raise ValueError("max_age_seconds must be between 60 and 86400")
        channels = ["ntfy"] if channels is None else channels
        if (
            not isinstance(channels, list)
            or len(channels) > len(CHANNELS)
            or any(not isinstance(channel, str) or channel not in CHANNELS for channel in channels)
            or len(set(channels)) != len(channels)
        ):
            raise ValueError("channels must contain supported, unique channel IDs")
        config, error = ntfy_readiness(self.root) if "ntfy" in channels else (None, None)
        age = (
            min(max_age_seconds, config["notifications"]["max_age_seconds"])
            if config
            else max_age_seconds
        )
        now = time.time()
        with closing(self._connection()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            self._retain(conn, now)
            if dedupe_key is not None:
                row = conn.execute(
                    "SELECT * FROM notification_events WHERE mode=? AND source=? AND dedupe_key=?",
                    (self.mode, source, dedupe_key),
                ).fetchone()
                if row is not None:
                    return self._item(conn, row, deduplicated=True)
            ident = "notification_" + uuid.uuid4().hex
            conn.execute(
                """INSERT INTO notification_events
                (id,mode,title,message,source,created_at,expires_at,dedupe_key) VALUES(?,?,?,?,?,?,?,?)""",
                (ident, self.mode, title, message, source, now, now + age, dedupe_key),
            )
            for channel in channels:
                conn.execute(
                    """INSERT INTO notification_channel_deliveries
                    (notification_id,channel,state,error) VALUES(?,?,?,?)""",
                    (ident, channel, "unavailable" if error else "pending", error),
                )
            return self._item(
                conn,
                conn.execute("SELECT * FROM notification_events WHERE id=?", (ident,)).fetchone(),
            )

    def list_history(
        self,
        *,
        source: str | None = None,
        source_type: str | None = None,
        channel: str | None = None,
        state: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> dict:
        """Page this mode's explicit notices and minimal legacy delivery references.

        Source selects producer origins, while source_type selects event
        categories. Legacy private payloads are never projected.
        """
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if type(offset) is not int or not 0 <= offset <= 1000000:
            raise ValueError("offset must be between 0 and 1000000")
        if source is not None:
            source = _text(source, "source", 80)
        if source_type is not None and (
            not isinstance(source_type, str) or source_type not in SOURCE_TYPES
        ):
            raise ValueError("Unknown notification source type")
        if channel is not None and (not isinstance(channel, str) or channel not in CHANNELS):
            raise ValueError("Unknown notification channel")
        if state is not None and (not isinstance(state, str) or state not in STATES):
            raise ValueError("Unknown notification state")
        if not self.path.exists():
            return {"items": [], "total": 0, "limit": limit, "offset": offset}
        with closing(self._connection()) as conn, conn:
            self._retain(conn, time.time())
            clauses, args = ["e.mode=?", "e.content_retained=1"], [self.mode]
            if source_type is not None and source_type != "notifications":
                clauses.append("0")
            if source is not None:
                clauses.append("e.source=?")
                args.append(source)
            if channel is not None:
                clauses.append(
                    "EXISTS(SELECT 1 FROM notification_channel_deliveries d WHERE d.notification_id=e.id AND d.channel=?)"
                )
                args.append(channel)
            if state == "saved":
                clauses.append(
                    "NOT EXISTS(SELECT 1 FROM notification_channel_deliveries d WHERE d.notification_id=e.id)"
                )
            elif state is not None:
                clauses.append(
                    "EXISTS(SELECT 1 FROM notification_channel_deliveries d WHERE d.notification_id=e.id AND d.state=?)"
                )
                args.append(state)
            query = (
                "SELECT 'explicit' AS kind,e.id AS ident,e.created_at AS sort_time FROM notification_events e WHERE "
                + " AND ".join(clauses)
            )
            legacy = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='deliveries'"
            ).fetchone()
            if legacy:
                clauses = ["mode=?", "state IN ('pending','delivered','failed','suppressed')"]
                args.append(self.mode)
                if source is not None:
                    clauses.append("category=?")
                    args.append(source)
                if source_type is not None:
                    clauses.append("category=?")
                    args.append(source_type)
                if channel is not None and channel != "ntfy":
                    clauses.append("0")
                if state is not None:
                    clauses.append("state=?")
                    args.append(state)
                columns = {row["name"] for row in conn.execute("PRAGMA table_info(deliveries)")}
                times = []
                if "event_at" in columns:
                    times.append("event_at")
                if "sent_at" in columns:
                    times.append("unixepoch(sent_at)")
                # A delivery deadline is not an event time. Unknown old times
                # remain NULL and sort after dated entries in descending order.
                stamp = (
                    "COALESCE(" + ",".join(times) + ")"
                    if len(times) > 1 else times[0] if times else "NULL"
                )
                query += (
                    " UNION ALL SELECT 'legacy',event_key,"
                    + stamp
                    + " FROM deliveries WHERE "
                    + " AND ".join(clauses)
                )
            total = conn.execute("SELECT COUNT(*) FROM (" + query + ")", args).fetchone()[0]
            rows = conn.execute(
                query + " ORDER BY sort_time DESC,ident DESC LIMIT ? OFFSET ?",
                [*args, limit, offset],
            ).fetchall()
            items = []
            for row in rows:
                if row["kind"] == "explicit":
                    item = conn.execute(
                        "SELECT * FROM notification_events WHERE id=?", (row["ident"],)
                    ).fetchone()
                    items.append(self._item(conn, item))
                else:
                    old = conn.execute(
                        "SELECT * FROM deliveries WHERE event_key=?", (row["ident"],)
                    ).fetchone()
                    delivery = {"channel": "ntfy", "state": old["state"]}
                    if old["error"]:
                        delivery["error"] = _safe_error(old["error"])
                    if "sent_at" in old.keys() and old["sent_at"]:
                        delivery["sent_at"] = old["sent_at"]
                    event_at = old["event_at"] if "event_at" in old.keys() else None
                    items.append(
                        {
                            "id": "legacy_" + hashlib.sha256(row["ident"].encode()).hexdigest(),
                            "source_type": old["category"],
                            "source": old["category"],
                            "source_id": old["source_id"],
                            "title": f"{old['category'].replace('_', ' ')} #{old['source_id']}",
                            "message": "",
                            "mode": self.mode,
                            "created_at": _iso(event_at) if event_at is not None else None,
                            "deduplicated": False,
                            "state": old["state"],
                            "deliveries": [delivery],
                        }
                    )
            return {"items": items, "total": total, "limit": limit, "offset": offset}

    def deliver_ntfy(
        self,
        config: dict,
        sender: Callable[[dict, dict], str],
        clock: Callable[[], float] = time.time,
    ) -> dict:
        """Deliver pending explicit notices from both modes under the worker lock.

        Caller-authored messages are intentional notification content and do
        not use the legacy include_descriptions switch. No write lock is held
        while publishing; receipts describe remote acceptance, not phone reads.
        """
        from lib.ntfy_notifications import DeliveryError

        stats = {"delivered": 0, "suppressed": 0, "errors": []}
        now = clock()
        with closing(self._connection()) as conn:
            with conn:
                stats["suppressed"] += self._retain(conn, now)
                if not config["enabled"] or not config["notifications"]["enabled"]:
                    stats["suppressed"] += conn.execute("""UPDATE notification_channel_deliveries
                        SET state='suppressed',error='channel_disabled' WHERE channel='ntfy' AND state='pending'""").rowcount
            rows = conn.execute(
                """SELECT e.*,d.attempts FROM notification_events e
                JOIN notification_channel_deliveries d ON d.notification_id=e.id
                WHERE d.channel='ntfy' AND d.state='pending' AND d.next_try<=?
                ORDER BY e.expires_at,e.id LIMIT 20""",
                (now,),
            ).fetchall()
            for row in rows:
                if row["expires_at"] <= clock():
                    with conn:
                        conn.execute(
                            """UPDATE notification_channel_deliveries SET state='suppressed',error='expired'
                            WHERE notification_id=? AND channel='ntfy'""",
                            (row["id"],),
                        )
                    stats["suppressed"] += 1
                    continue
                payload = {
                    "topic": config["notifications"]["topic"],
                    "title": row["title"],
                    "message": row["message"],
                    "priority": 3,
                }
                try:
                    receipt = sender(config, payload)
                except DeliveryError as exc:
                    attempts = row["attempts"] + 1
                    failed = not exc.retryable or attempts >= config["max_attempts"]
                    with conn:
                        conn.execute(
                            """UPDATE notification_channel_deliveries SET state=?,attempts=?,next_try=?,error=?
                            WHERE notification_id=? AND channel='ntfy'""",
                            (
                                "failed" if failed else "pending",
                                attempts,
                                clock() + min(30 * 2 ** (attempts - 1), 900),
                                _safe_error(str(exc)),
                                row["id"],
                            ),
                        )
                    stats["errors"].append(_safe_error(str(exc)))
                else:
                    with conn:
                        conn.execute(
                            """UPDATE notification_channel_deliveries SET state='delivered',receipt=?,sent_at=?,error=NULL
                            WHERE notification_id=? AND channel='ntfy'""",
                            (receipt, _iso(clock()), row["id"]),
                        )
                    stats["delivered"] += 1
        return stats
