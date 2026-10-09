"""Optional phone delivery from persisted events; never called by event producers.

The worker owns its delivery database. Source databases are opened read-only,
without MemoryDB initialization, migrations, embeddings, or model calls.
"""

import json
import os
import re
import sqlite3
import stat
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

CATEGORIES = ("alerts", "reminders", "background_tasks")
DEFAULTS = {
    "enabled": False,
    "server_url": "",
    "publisher_token": "",
    "poll_seconds": 15,
    "request_timeout_seconds": 10,
    "max_attempts": 5,
    "include_descriptions": False,
    "alerts": {
        "enabled": True, "topic": "jarvis-alerts", "severities": ["high", "critical"],
        "max_age_seconds": 1800,
    },
    "reminders": {"enabled": True, "topic": "jarvis-reminders", "max_age_seconds": 3600},
    "background_tasks": {
        "enabled": False, "topic": "jarvis-tasks", "max_age_seconds": 3600,
    },
}


def validate_config(raw: dict) -> dict:
    """Validate secrets and switches without including their values in errors."""
    if not isinstance(raw, dict) or set(raw) - set(DEFAULTS):
        raise ValueError("Unknown ntfy configuration setting")
    config = {**DEFAULTS, **raw}
    for category in CATEGORIES:
        section = raw.get(category, {})
        if not isinstance(section, dict) or set(section) - set(DEFAULTS[category]):
            raise ValueError("Unknown ntfy category setting")
        config[category] = {**DEFAULTS[category], **section}
        if type(config[category]["enabled"]) is not bool:
            raise ValueError("ntfy category enabled must be boolean")
        if not isinstance(config[category]["topic"], str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,64}", config[category]["topic"]
        ):
            raise ValueError("Invalid ntfy topic")
        age = config[category]["max_age_seconds"]
        if type(age) is not int or not 60 <= age <= 86400:
            raise ValueError("ntfy max_age_seconds must be between 60 and 86400")
    for key in ("enabled", "include_descriptions"):
        if type(config[key]) is not bool:
            raise ValueError("ntfy switches must be boolean")
    for key, low, high in (
        ("poll_seconds", 5, 300), ("request_timeout_seconds", 1, 30), ("max_attempts", 1, 10)
    ):
        if type(config[key]) is not int or not low <= config[key] <= high:
            raise ValueError("Invalid ntfy timing or retry setting")
    severities = config["alerts"]["severities"]
    if not isinstance(severities, list) or any(
        item not in {"low", "medium", "high", "critical"} for item in severities
    ):
        raise ValueError("Invalid ntfy alert severities")
    if config["enabled"]:
        try:
            url = urlsplit(config["server_url"])
            valid_url = (
                url.scheme == "https" and url.hostname and not url.username
                and not url.password and url.path in {"", "/"} and not url.query
                and not url.fragment and url.port != 0
            )
        except (TypeError, ValueError):
            valid_url = False
        if not valid_url:
            raise ValueError("ntfy requires an HTTPS server origin")
        token = config["publisher_token"]
        if not isinstance(token, str) or not re.fullmatch(r"tk_[a-z0-9]{29}", token):
            raise ValueError("Invalid ntfy publisher token")
        config["server_url"] = config["server_url"].rstrip("/")
    return config


def load_config(path: Path) -> dict:
    if not path.exists():
        return validate_config({})
    if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError("ntfy configuration must be private (chmod 600)")
    return validate_config(json.loads(path.read_text()))


class DeliveryError(Exception):
    """Sanitized error; request headers and response bodies never become logs."""

    def __init__(self, reason: str, retryable: bool = True):
        super().__init__(reason)
        self.retryable = retryable


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def publish(config: dict, payload: dict) -> str:
    request = urllib.request.Request(
        config["server_url"] + "/", data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": "Bearer " + config["publisher_token"],
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(
            request, timeout=config["request_timeout_seconds"]
        ) as response:
            receipt = json.loads(response.read(65537))
            if (not isinstance(receipt, dict) or receipt.get("event") != "message"
                    or receipt.get("topic") != payload["topic"]
                    or not isinstance(receipt.get("id"), str) or not receipt["id"]):
                raise DeliveryError("Invalid ntfy delivery receipt")
            return receipt["id"]
    except urllib.error.HTTPError as exc:
        raise DeliveryError(
            f"ntfy HTTP {exc.code}", retryable=exc.code in {408, 429} or exc.code >= 500
        ) from None
    except DeliveryError:
        raise
    except Exception as exc:
        raise DeliveryError(f"ntfy {type(exc).__name__}") from None


def _source(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
    conn.row_factory = sqlite3.Row
    return conn


def _timestamp(value: str) -> float:
    # Alert timestamps are host-local naive dates; reminder timestamps carry UTC.
    return datetime.fromisoformat(value).timestamp()


def write_worker_status(root: Path, mode: str, state: str, poll_seconds: int) -> None:
    """Private shared heartbeat, readable across native/Docker process namespaces."""
    folder = root / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".ntfy-status-", dir=folder)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump({"mode": mode, "state": state, "updated_at": time.time(),
                       "poll_seconds": poll_seconds}, output)
        os.replace(temporary, folder / "ntfy_notifications.status.json")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class NotificationWorker:
    def __init__(self, root: Path, mode: str, sender=publish, clock=time.time):
        if mode not in {"cloud", "local"}:
            raise ValueError("Invalid notification mode")
        self.root, self.mode, self.sender, self.clock = root, mode, sender, clock
        self.state_path = root / "data" / "ntfy_notifications.db"

    def source_path(self, category: str, mode: str) -> Path:
        if category == "background_tasks":
            return self.root / "data" / "background_tasks.db"
        suffix = "_local" if mode == "local" else ""
        return self.root / "data" / f"jarvis_memory{suffix}.db"

    def _state(self) -> sqlite3.Connection:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.state_path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.state_path.chmod(0o600)
        conn = sqlite3.connect(self.state_path, timeout=1)
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS cursors (
                category TEXT, mode TEXT, value TEXT NOT NULL, PRIMARY KEY(category, mode)
            );
            CREATE TABLE IF NOT EXISTS deliveries (
                event_key TEXT PRIMARY KEY, category TEXT NOT NULL, mode TEXT NOT NULL,
                source_id TEXT NOT NULL, stamp TEXT, expires REAL NOT NULL,
                payload TEXT, state TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0, next_try REAL NOT NULL DEFAULT 0,
                receipt TEXT, error TEXT
            );
            CREATE INDEX IF NOT EXISTS deliveries_pending ON deliveries(state,next_try);
        """)
        return conn

    def _rows(self, category: str, cursor, now: float):
        """Bounded reads; cursor advances even across nonqualifying records."""
        with closing(_source(self.source_path(category, self.mode))) as conn:
            if category == "alerts":
                if cursor is None:
                    return [], conn.execute("SELECT COALESCE(MAX(id),0) FROM alerts").fetchone()[0]
                rows = conn.execute(
                    "SELECT id,title,description,severity,status,created_at FROM alerts "
                    "WHERE id>? ORDER BY id LIMIT 500", (cursor,)
                ).fetchall()
                return rows, rows[-1]["id"] if rows else cursor
            if cursor is None:
                # First enable never sends already-triggered reminders or completed jobs.
                if category == "reminders":
                    baseline = conn.execute(
                        "SELECT (julianday(?)-2440587.5)*86400",
                        (datetime.fromtimestamp(now, timezone.utc).isoformat(),),
                    ).fetchone()[0]
                    return [], [baseline, 9223372036854775807]
                # Job updated_at also changes when a result is read. Remember
                # existing terminal identities so such edits cannot replay the baseline.
                rows = conn.execute(
                    "SELECT id,state FROM jobs WHERE mode=? AND state IN ('succeeded','failed')",
                    (self.mode,),
                ).fetchall()
                return rows, [now, "\uffff"]
            if category == "reminders":
                rows = conn.execute(
                    "SELECT id,title,description,status,triggered_at,"
                    "(julianday(triggered_at)-2440587.5)*86400 AS event_time FROM reminders "
                    "WHERE event_time>? OR (event_time=? AND id>?) "
                    "ORDER BY event_time,id LIMIT 500", (cursor[0], cursor[0], cursor[1])
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id,admission_json,state,updated_at AS event_time,cancelled,"
                    "cancel_requested,expired,archived_at FROM jobs WHERE mode=? AND "
                    "(updated_at>? OR (updated_at=? AND id>?)) "
                    "ORDER BY updated_at,id LIMIT 500",
                    (self.mode, cursor[0], cursor[0], cursor[1]),
                ).fetchall()
            return rows, [rows[-1]["event_time"], rows[-1]["id"]] if rows else cursor

    def _event(self, category: str, row, config: dict, now: float):
        section = config[category]
        if category == "alerts":
            if row["status"] != "pending" or row["severity"] not in section["severities"]:
                return None
            stamp, when = None, _timestamp(row["created_at"])
            title = row["title"]
            priority = {"critical": 5, "high": 4, "medium": 3, "low": 2}[row["severity"]]
        elif category == "reminders":
            if row["status"] not in {"scheduled", "triggered"}:
                return None
            stamp, when = row["triggered_at"], row["event_time"]
            title, priority = "Reminder: " + row["title"], 3
        else:
            if (row["state"] not in {"succeeded", "failed"} or row["cancelled"]
                    or row["cancel_requested"] or row["expired"] or row["archived_at"]):
                return None
            stamp, when = row["state"], row["event_time"]
            tool = json.loads(row["admission_json"]).get("tool", "Background task")
            title, priority = f"{tool}: {row['state']}", 3
        expires = when + section["max_age_seconds"]
        if expires <= now:
            return None
        title = str(title).strip()[:200] or "Jarvis notification"
        message = title
        if config["include_descriptions"] and category != "background_tasks":
            message = str(row["description"] or title).strip()[:2000] or title
        payload = {"topic": section["topic"], "title": title, "message": message,
                   "priority": priority}
        event_key = json.dumps([self.mode, category, str(row["id"]), stamp])
        return (event_key, category, self.mode, str(row["id"]), stamp, expires,
                json.dumps(payload))

    def _current(self, item, config: dict) -> bool:
        """Retries must still represent a live, eligible source event."""
        category, mode = item["category"], item["mode"]
        with closing(_source(self.source_path(category, mode))) as conn:
            if category == "alerts":
                row = conn.execute("SELECT status,severity FROM alerts WHERE id=?",
                                   (item["source_id"],)).fetchone()
                return bool(row and row["status"] == "pending"
                            and row["severity"] in config["alerts"]["severities"])
            if category == "reminders":
                row = conn.execute("SELECT status,triggered_at FROM reminders WHERE id=?",
                                   (item["source_id"],)).fetchone()
                return bool(row and row["status"] in {"triggered", "scheduled"}
                            and row["triggered_at"] == item["stamp"])
            row = conn.execute(
                "SELECT state,cancelled,cancel_requested,expired,archived_at FROM jobs WHERE id=?",
                (item["source_id"],),
            ).fetchone()
            return bool(row and row["state"] == item["stamp"] and not row["cancelled"]
                        and not row["cancel_requested"] and not row["expired"]
                        and not row["archived_at"])

    def cycle(self, config: dict) -> dict:
        """Scan transactionally, then publish with no SQLite write lock held."""
        stats = {"queued": 0, "delivered": 0, "suppressed": 0, "errors": []}
        if not config["enabled"] and not self.state_path.exists():
            return stats
        now = self.clock()
        with closing(self._state()) as state:
            for category in CATEGORIES:
                if not config["enabled"] or not config[category]["enabled"]:
                    with state:
                        state.execute("DELETE FROM cursors WHERE category=?", (category,))
                        count = state.execute(
                            "UPDATE deliveries SET state='suppressed',payload=NULL "
                            "WHERE category=? AND state='pending'", (category,)
                        ).rowcount
                        stats["suppressed"] += count
                    continue
                saved = state.execute(
                    "SELECT value FROM cursors WHERE category=? AND mode=?",
                    (category, self.mode),
                ).fetchone()
                try:
                    rows, cursor = self._rows(category, json.loads(saved[0]) if saved else None, now)
                except (OSError, sqlite3.Error) as exc:
                    stats["errors"].append(f"{category} source {type(exc).__name__}")
                    continue
                with state:
                    for row in rows:
                        if saved is None and category == "background_tasks":
                            key = json.dumps([self.mode, category, str(row["id"]), row["state"]])
                            state.execute(
                                "INSERT OR IGNORE INTO deliveries "
                                "(event_key,category,mode,source_id,stamp,expires,state) "
                                "VALUES(?,?,?,?,?,?,'baseline')",
                                (key, category, self.mode, str(row["id"]), row["state"], now),
                            )
                            continue
                        try:
                            event = self._event(category, row, config, now)
                        except (ValueError, TypeError, KeyError, AttributeError):
                            stats["errors"].append(f"{category} invalid record")
                            continue
                        if event:
                            stats["queued"] += state.execute(
                                "INSERT OR IGNORE INTO deliveries "
                                "(event_key,category,mode,source_id,stamp,expires,payload) "
                                "VALUES(?,?,?,?,?,?,?)", event,
                            ).rowcount
                    state.execute("INSERT OR REPLACE INTO cursors VALUES(?,?,?)",
                                  (category, self.mode, json.dumps(cursor)))
            with state:
                stats["suppressed"] += state.execute(
                    "UPDATE deliveries SET state='suppressed',payload=NULL "
                    "WHERE state='pending' AND expires<=?", (now,)
                ).rowcount
            pending = state.execute(
                "SELECT * FROM deliveries WHERE state='pending' AND mode=? AND next_try<=? "
                "ORDER BY expires,event_key LIMIT 20", (self.mode, now)
            ).fetchall()
            for item in pending:
                try:
                    current = self._current(item, config)
                except (OSError, sqlite3.Error) as exc:
                    stats["errors"].append(f"{item['category']} source {type(exc).__name__}")
                    continue
                # Recheck expiry after earlier requests consumed time.
                if not current or item["expires"] <= self.clock():
                    with state:
                        state.execute("UPDATE deliveries SET state='suppressed',payload=NULL "
                                      "WHERE event_key=?", (item["event_key"],))
                    stats["suppressed"] += 1
                    continue
                try:
                    payload = json.loads(item["payload"])
                    payload["topic"] = config[item["category"]]["topic"]
                    if not config["include_descriptions"]:
                        payload["message"] = payload["title"]
                    receipt = self.sender(config, payload)
                except DeliveryError as exc:
                    attempts = item["attempts"] + 1
                    final = not exc.retryable or attempts >= config["max_attempts"]
                    with state:
                        state.execute(
                            "UPDATE deliveries SET attempts=?,next_try=?,error=?,state=?,"
                            "payload=CASE WHEN ? THEN NULL ELSE payload END WHERE event_key=?",
                            (attempts, self.clock() + min(30 * 2 ** (attempts - 1), 900),
                             str(exc), "failed" if final else "pending", final, item["event_key"]),
                        )
                    stats["errors"].append(str(exc))
                else:
                    with state:
                        state.execute("UPDATE deliveries SET state='delivered',receipt=?,"
                                      "payload=NULL,error=NULL WHERE event_key=?",
                                      (receipt, item["event_key"]))
                    stats["delivered"] += 1
        return stats
