"""Mode-scoped SQLite watch baselines, staged revisions and delivery receipts.

No method sends notifications. A commit advances the observation baseline even
when its durable delivery intents have not yet been delivered.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import time
import uuid
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .authority import Authority
from .normalization import (
    MAX_PAGE,
    MAX_SNAPSHOT_RECORDS,
    SHARED_RADAR_KEYS,
    AuthorityError,
    ConflictError,
    NotFoundError,
    StorageError,
    ValidationError,
    WatchStateError,
    bounded_string,
    comparison_value,
    json_text,
    normalize_definition,
    normalize_records,
    validate_json,
    validate_key,
)

MAX_DELIVERY_ATTEMPTS = 5
MAX_PENDING = 10_000
MAX_STAGED = 10
MAX_SNAPSHOT_BYTES = 10_000_000
STAGE_TTL_SECONDS = 7 * 86_400
MAX_READ_BYTES = 240_000
MAX_CHANGE_PREVIEW = 25

SCHEMA = """
CREATE TABLE IF NOT EXISTS watches (
 scope TEXT NOT NULL, key TEXT NOT NULL, owner TEXT NOT NULL,
 definition_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
 generation INTEGER NOT NULL DEFAULT 0, initialized INTEGER NOT NULL DEFAULT 0,
 created_at REAL NOT NULL, updated_at REAL NOT NULL, last_run_at REAL,
 last_success_at REAL, last_error_json TEXT, error_count INTEGER NOT NULL DEFAULT 0,
 muted_until REAL, deleted_at REAL, PRIMARY KEY(scope,key)
);
CREATE TABLE IF NOT EXISTS snapshots (
 scope TEXT NOT NULL, key TEXT NOT NULL, record_id TEXT NOT NULL,
 record_json TEXT NOT NULL, missing_count INTEGER NOT NULL DEFAULT 0,
 removed INTEGER NOT NULL DEFAULT 0, last_seen_at REAL NOT NULL,
 PRIMARY KEY(scope,key,record_id)
);
CREATE TABLE IF NOT EXISTS runs (
 run_id TEXT PRIMARY KEY, scope TEXT NOT NULL, key TEXT NOT NULL,
 base_revision INTEGER NOT NULL, generation INTEGER NOT NULL,
 definition_json TEXT NOT NULL, request_id TEXT, input_hash TEXT NOT NULL,
 created_at REAL NOT NULL, status TEXT NOT NULL,
 complete INTEGER NOT NULL, records_count INTEGER NOT NULL,
 snapshot_json TEXT, changes_json TEXT, receipt_json TEXT,
 UNIQUE(scope,key,request_id)
);
CREATE TABLE IF NOT EXISTS events (
 event_id TEXT PRIMARY KEY, scope TEXT NOT NULL, key TEXT NOT NULL,
 run_id TEXT NOT NULL, revision INTEGER NOT NULL, kind TEXT NOT NULL,
 record_id TEXT NOT NULL, before_json TEXT, after_json TEXT,
 fields_json TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS deliveries (
 event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
 channel TEXT NOT NULL, destination TEXT NOT NULL, status TEXT NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0, claim_token TEXT, lease_until REAL,
 receipt_json TEXT, error_json TEXT, delivered_at REAL, updated_at REAL NOT NULL,
 PRIMARY KEY(event_id,channel,destination)
);
CREATE TABLE IF NOT EXISTS handled_records (
 scope TEXT NOT NULL, key TEXT NOT NULL, record_id TEXT NOT NULL,
 channel TEXT NOT NULL, destination TEXT NOT NULL, record_json TEXT NOT NULL,
 receipt_json TEXT, delivered_at REAL NOT NULL,
 PRIMARY KEY(scope,key,record_id,channel,destination)
);
CREATE INDEX IF NOT EXISTS watch_runs_scope ON runs(scope,key,status,created_at);
CREATE INDEX IF NOT EXISTS watch_events_scope ON events(scope,key,created_at);
CREATE INDEX IF NOT EXISTS watch_deliveries_pending ON deliveries(status,updated_at);
CREATE INDEX IF NOT EXISTS watch_handled_scope ON handled_records(scope,key,channel,record_id);
"""


def _load(value: str | None, default: Any = None) -> Any:
    return json.loads(value) if value is not None else default


def _digest(value: Any) -> str:
    return hashlib.sha256(json_text(value).encode("utf-8")).hexdigest()


def _page(limit: int, offset: int) -> None:
    if type(limit) is not int or not 1 <= limit <= MAX_PAGE or type(offset) is not int or offset < 0:
        raise ValidationError(f"Pagination requires limit 1..{MAX_PAGE} and a nonnegative offset.")


def _read_page(rows: Iterable[Any], convert: Callable[[Any], dict], limit: int, offset: int, *, budget: int = MAX_READ_BYTES) -> tuple[list[dict], int | None]:
    items: list[dict] = []
    used = 2
    for row in rows:
        if len(items) >= limit:
            return items, offset + len(items)
        item = convert(row)
        cost = len(json_text(item).encode("utf-8")) + 1
        if used + cost > budget:
            if not items:
                raise ValidationError("Stored record exceeds a read page; keep large content in Stash.")
            return items, offset + len(items)
        items.append(item)
        used += cost
    return items, None


class Store:
    """Lazy connections keep dry runs and reads of a new store free of writes."""

    def __init__(
        self, project_root: str | Path, mode: str, *, db_path: str | Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if mode not in {"cloud", "local", "shared"}:
            raise ValidationError("Watch scope must be cloud, local or the internal shared radar scope.")
        self.project_root = Path(project_root)
        self.mode = mode
        self.db_path = Path(db_path) if db_path is not None else self.project_root / "data/watch_state.db"
        if not self.db_path.is_absolute():
            self.db_path = self.project_root / self.db_path if db_path is not None else self.db_path
        self.clock = clock
        self._initialized = False

    def _key(self, key: str) -> str:
        key = validate_key(key)
        if self.mode == "shared" and key not in SHARED_RADAR_KEYS:
            raise AuthorityError("Shared watch scope is reserved for the reviewed movie and TV radars.")
        return key

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection | None]:
        if not write and not self.db_path.exists():
            yield None
            return
        conn = None
        try:
            if write:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.db_path), timeout=10, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=10000")
            if write and not self._initialized:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(SCHEMA)
                self._initialized = True
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            if write:
                conn.commit()
        except sqlite3.Error as exc:
            if conn is not None:
                conn.rollback()
            raise StorageError("Watch-state storage is unavailable or its schema is incompatible.") from exc
        except BaseException:
            if conn is not None:
                conn.rollback()
            raise
        finally:
            if conn is not None:
                conn.close()

    def _watch(self, conn: sqlite3.Connection | None, key: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM watches WHERE scope=? AND key=? AND deleted_at IS NULL", (self.mode, key)).fetchone() if conn else None
        if row is None:
            raise NotFoundError("Watch is not registered in this scope.")
        return row

    def _authorize(self, row: sqlite3.Row, authority: Authority) -> None:
        if not isinstance(authority, Authority) or authority.writer == "workflow:unidentified":
            raise AuthorityError("Trusted watch authority is required.")
        if not authority.admin and row["owner"] != authority.writer:
            raise AuthorityError("Only the watch owner or an administrator may mutate this watch.")
        if self.mode == "shared" and not authority.admin and authority.writer != f"workflow:{row['key']}":
            raise AuthorityError("A shared radar requires its matching trusted workflow writer.")

    @staticmethod
    def _muted(row: sqlite3.Row, now: float) -> bool:
        return row["muted_until"] is not None and (row["muted_until"] < 0 or row["muted_until"] > now)

    def _metadata(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        definition = _load(row["definition_json"])
        now = self.clock()
        counts = conn.execute(
            "SELECT status,COUNT(*) n,SUM(CASE WHEN d.status='parked' OR (d.status='pending' AND (d.error_json IS NOT NULL OR (d.attempts>0 AND (d.claim_token IS NULL OR d.lease_until<=?)))) THEN 1 ELSE 0 END) failed FROM deliveries d JOIN events e USING(event_id) WHERE e.scope=? AND e.key=? GROUP BY status",
            (now, row["scope"], row["key"]),
        ).fetchall()
        delivery_errors = sum(item["failed"] for item in counts)
        counts = {item["status"]: item["n"] for item in counts}
        return {
            "key": row["key"], "scope": row["scope"], "mode": row["scope"], "owner": row["owner"],
            "revision": row["revision"], "initialized": bool(row["initialized"]), "definition": definition,
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "last_run_at": row["last_run_at"], "last_success_at": row["last_success_at"],
            "last_error": _load(row["last_error_json"]), "source_error_count": row["error_count"],
            "error_count": row["error_count"] + delivery_errors, "delivery_error_count": delivery_errors,
            "stale_after_seconds": definition["stale_after_seconds"],
            "stale": definition["stale_after_seconds"] > 0 and now - (row["last_success_at"] if row["last_success_at"] is not None else row["created_at"]) > definition["stale_after_seconds"],
            "muted": self._muted(row, now), "muted_until": row["muted_until"],
            "pending_count": counts.get("pending", 0), "parked_count": counts.get("parked", 0),
        }

    def register(self, key: str, definition: dict, authority: Authority, *, owner: str | None = None) -> dict:
        key = self._key(key)
        definition = normalize_definition(definition)
        if not isinstance(authority, Authority) or authority.writer == "workflow:unidentified":
            raise AuthorityError("Trusted watch authority is required.")
        if owner is not None and not authority.admin:
            raise AuthorityError("Only administrators may choose a registration owner.")
        writer = Authority(owner).writer if owner is not None else authority.writer
        if self.mode == "shared" and writer != f"workflow:{key}":
            raise AuthorityError("Shared radar ownership must match its reviewed workflow.")
        text = json_text(definition)
        now = self.clock()
        with self._connection(write=True) as conn:
            assert conn is not None
            old = conn.execute("SELECT * FROM watches WHERE scope=? AND key=?", (self.mode, key)).fetchone()
            if old:
                self._authorize(old, authority)
                if old["deleted_at"] is None and old["definition_json"] != text:
                    if old["initialized"] or definition["schema_version"] <= _load(old["definition_json"])["schema_version"]:
                        raise ConflictError("Reset the watch and increase schema_version before changing its definition.")
                    staged = conn.execute("SELECT 1 FROM runs WHERE scope=? AND key=? AND status='staged' LIMIT 1", (self.mode, key)).fetchone()
                    if staged:
                        raise ConflictError("Discard staged observations with reset before changing the definition.")
                    conn.execute("UPDATE watches SET definition_json=?,generation=generation+1,revision=revision+1,updated_at=? WHERE scope=? AND key=?", (text, now, self.mode, key))
                if old["deleted_at"] is not None:
                    # Also clean keys deleted by versions that retained their event history.
                    conn.execute("DELETE FROM snapshots WHERE scope=? AND key=?", (self.mode, key))
                    self._clear_deleted_history(conn, key)
                    conn.execute("UPDATE watches SET definition_json=?,deleted_at=NULL,initialized=0,generation=generation+1,revision=revision+1,created_at=?,updated_at=?,last_run_at=NULL,last_success_at=NULL,last_error_json=NULL,error_count=0,muted_until=NULL WHERE scope=? AND key=?", (text, now, now, self.mode, key))
                if owner is not None:
                    conn.execute("UPDATE watches SET owner=?,updated_at=? WHERE scope=? AND key=?", (writer, now, self.mode, key))
            else:
                conn.execute("INSERT INTO watches(scope,key,owner,definition_json,created_at,updated_at) VALUES(?,?,?,?,?,?)", (self.mode, key, writer, text, now, now))
            return self._metadata(conn, self._watch(conn, key))

    def _record_error(self, key: str, authority: Authority, error: WatchStateError) -> None:
        if not self.db_path.exists():
            return
        try:
            with self._connection(write=True) as conn:
                assert conn is not None
                row = self._watch(conn, key)
                self._authorize(row, authority)
                now = self.clock()
                safe = {"code": type(error).__name__, "message": str(error)[:300], "at": now}
                conn.execute("UPDATE watches SET last_run_at=?,last_error_json=?,error_count=error_count+1,updated_at=? WHERE scope=? AND key=?", (now, json_text(safe), now, self.mode, key))
        except (AuthorityError, NotFoundError, StorageError):
            return

    def record_error(self, key: str, authority: Authority, error_code: str = "source_fetch_failed") -> dict:
        """Report a source failure without accepting remote exception text or changing state."""
        key = self._key(key)
        if not isinstance(error_code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", error_code):
            raise ValidationError("error_code must be a short lowercase code, not exception text.")
        with self._connection(write=True) as conn:
            assert conn is not None
            watch = self._watch(conn, key)
            self._authorize(watch, authority)
            now = self.clock()
            error = {"code": error_code, "message": "The watch source could not be checked; its baseline was preserved.", "at": now}
            conn.execute("UPDATE watches SET last_run_at=?,last_error_json=?,error_count=error_count+1,updated_at=? WHERE scope=? AND key=?", (now, json_text(error), now, self.mode, key))
            return self._metadata(conn, self._watch(conn, key))

    def record_check_success(self, key: str, authority: Authority) -> dict:
        """Record a trusted successful ledger check without advancing its baseline."""
        key = self._key(key)
        with self._connection(write=True) as conn:
            assert conn is not None
            watch = self._watch(conn, key)
            self._authorize(watch, authority)
            now = self.clock()
            conn.execute("UPDATE watches SET last_run_at=?,last_success_at=?,last_error_json=NULL,error_count=0,updated_at=? WHERE scope=? AND key=?", (now, now, now, self.mode, key))
            return self._metadata(conn, self._watch(conn, key))

    def compare(
        self, key: str, records: list[dict], authority: Authority, *, complete: bool | None = None,
        dry_run: bool = False, request_id: str | None = None,
    ) -> dict:
        key = self._key(key)
        try:
            return self._compare(key, records, authority, complete=complete, dry_run=dry_run, request_id=request_id)
        except (ValidationError, ConflictError) as exc:
            if dry_run is not True:
                self._record_error(key, authority, exc)
            raise

    def _compare(self, key: str, records: list[dict], authority: Authority, *, complete: bool | None, dry_run: bool, request_id: str | None) -> dict:
        if type(dry_run) is not bool or (complete is not None and type(complete) is not bool):
            raise ValidationError("complete and dry_run must be booleans.")
        if request_id is not None:
            request_id = bounded_string(request_id, "request_id", 200)
        with self._connection() as conn:
            watch = self._watch(conn, key)
            self._authorize(watch, authority)
            definition = _load(watch["definition_json"])
            normalized = normalize_records(records, definition)
            complete = definition["complete"] if complete is None else complete
            input_hash = _digest({"records": normalized, "complete": complete, "definition": definition})
            if request_id is not None and conn is not None:
                previous = conn.execute("SELECT * FROM runs WHERE scope=? AND key=? AND request_id=?", (self.mode, key, request_id)).fetchone()
                if previous:
                    if previous["input_hash"] != input_hash or previous["generation"] != watch["generation"]:
                        raise ConflictError("request_id was already used for a different observation or watch generation.")
                    if previous["status"] in {"expired", "cancelled"}:
                        raise ConflictError("This staged request has expired or was reset; use a new request_id.")
                    return self._run_preview(previous, dry_run=dry_run)
            assert conn is not None
            snapshot = {row["record_id"]: {"record": _load(row["record_json"]), "missing_count": row["missing_count"],
                         "removed": bool(row["removed"]), "last_seen_at": row["last_seen_at"]}
                        for row in conn.execute("SELECT * FROM snapshots WHERE scope=? AND key=?", (self.mode, key))}
        run_id = uuid.uuid4().hex
        now = self.clock()
        changes = []

        def change(kind: str, identifier: str, before: dict | None, after: dict | None) -> None:
            before_value = comparison_value(before, definition) if before is not None else {}
            after_value = comparison_value(after, definition) if after is not None else {}
            fields = sorted(field for field in set(before_value) | set(after_value) if before_value.get(field) != after_value.get(field) or (field in before_value) != (field in after_value))
            changes.append({"event_id": hashlib.sha256(f"{run_id}\0{kind}\0{identifier}".encode()).hexdigest(),
                            "kind": kind, "record_id": identifier, "before": before, "after": after, "fields": fields})

        quiet = not watch["initialized"] and definition["quiet_first"]
        for identifier, record in normalized.items():
            old = snapshot.get(identifier)
            if not quiet:
                if old is None:
                    change("added", identifier, None, record)
                elif old["removed"]:
                    change("reappeared", identifier, old["record"], record)
                elif comparison_value(old["record"], definition) != comparison_value(record, definition):
                    change("changed", identifier, old["record"], record)
            snapshot[identifier] = {"record": record, "missing_count": 0, "removed": False, "last_seen_at": now}
        if complete:
            for identifier, old in snapshot.items():
                if identifier in normalized or old["removed"]:
                    continue
                old["missing_count"] += 1
                if old["missing_count"] >= definition["missing_grace"]:
                    old["removed"] = True
                    if not quiet:
                        change("removed", identifier, old["record"], None)
        if len(snapshot) > MAX_SNAPSHOT_RECORDS or len(json_text(snapshot).encode()) > MAX_SNAPSHOT_BYTES:
            raise ValidationError("The watch snapshot exceeds its bounded capacity; clean up old removed records or narrow the watch.")
        change_preview, more_changes = _read_page(changes, lambda value: value, MAX_CHANGE_PREVIEW, 0)
        preview = {"key": key, "scope": self.mode, "run_id": run_id, "base_revision": watch["revision"],
                   "status": "dry_run" if dry_run else "staged", "changes": change_preview, "changes_count": len(changes),
                   "changes_truncated": more_changes is not None,
                   "records_count": len(normalized), "snapshot_count": sum(not row["removed"] for row in snapshot.values()),
                   "complete": complete, "dry_run": dry_run, "quiet_first": quiet}
        if dry_run:
            return preview
        with self._connection(write=True) as conn:
            assert conn is not None
            current = self._watch(conn, key)
            self._authorize(current, authority)
            if current["revision"] != watch["revision"] or current["generation"] != watch["generation"] or current["definition_json"] != watch["definition_json"]:
                raise ConflictError("The watch advanced while this observation was being prepared; compare again.")
            if request_id is not None:
                previous = conn.execute("SELECT * FROM runs WHERE scope=? AND key=? AND request_id=?", (self.mode, key, request_id)).fetchone()
                if previous:
                    if previous["input_hash"] != input_hash:
                        raise ConflictError("request_id was already used for a different observation.")
                    return self._run_preview(previous)
            conn.execute("UPDATE runs SET status='expired',snapshot_json=NULL,changes_json=NULL WHERE run_id IN (SELECT run_id FROM runs WHERE scope=? AND key=? AND status='staged' AND created_at<? LIMIT 100)", (self.mode, key, now - STAGE_TTL_SECONDS))
            count = conn.execute("SELECT COUNT(*) FROM runs WHERE scope=? AND key=? AND status='staged'", (self.mode, key)).fetchone()[0]
            if count >= MAX_STAGED:
                raise ConflictError("Too many staged observations; commit or discard a staged run.")
            conn.execute("INSERT INTO runs(run_id,scope,key,base_revision,generation,definition_json,request_id,input_hash,created_at,status,complete,records_count,snapshot_json,changes_json) VALUES(?,?,?,?,?,?,?,?,?,'staged',?,?,?,?)",
                         (run_id, self.mode, key, watch["revision"], watch["generation"], watch["definition_json"], request_id, input_hash, now, int(complete), len(normalized), json_text(snapshot), json_text(changes)))
            conn.execute("UPDATE watches SET last_run_at=?,updated_at=? WHERE scope=? AND key=?", (now, now, self.mode, key))
        return preview

    def _run_preview(self, row: sqlite3.Row, *, dry_run: bool = False) -> dict:
        snapshot = _load(row["snapshot_json"], {})
        changes = _load(row["changes_json"], [])
        receipt = _load(row["receipt_json"], {})
        change_preview, more_changes = _read_page(changes, lambda value: value, MAX_CHANGE_PREVIEW, 0)
        return {"key": row["key"], "scope": row["scope"], "run_id": row["run_id"], "base_revision": row["base_revision"],
                "status": row["status"], "changes": change_preview, "changes_count": receipt.get("events_count", len(changes)), "changes_truncated": more_changes is not None or (row["changes_json"] is None and receipt.get("events_count", 0) > 0),
                "records_count": row["records_count"], "snapshot_count": receipt.get("snapshot_count", sum(not item["removed"] for item in snapshot.values())),
                "complete": bool(row["complete"]), "dry_run": dry_run, "changes_expired": row["changes_json"] is None}

    def commit(self, key: str, run_id: str, authority: Authority) -> dict:
        key = self._key(key)
        run_id = bounded_string(run_id, "run_id", 200)
        now = self.clock()
        try:
            with self._connection(write=True) as conn:
                assert conn is not None
                watch = self._watch(conn, key)
                self._authorize(watch, authority)
                run = conn.execute("SELECT * FROM runs WHERE run_id=? AND scope=? AND key=?", (run_id, self.mode, key)).fetchone()
                if run is None:
                    raise NotFoundError("Staged run was not found for this watch.")
                if run["status"] == "committed":
                    return {**_load(run["receipt_json"]), "already_committed": True}
                if run["status"] != "staged" or now - run["created_at"] > STAGE_TTL_SECONDS:
                    raise ConflictError("The staged run has expired or was cancelled.")
                if run["base_revision"] != watch["revision"] or run["generation"] != watch["generation"] or run["definition_json"] != watch["definition_json"]:
                    raise ConflictError("A newer watch revision exists; compare again before committing.")
                snapshot = _load(run["snapshot_json"])
                changes = _load(run["changes_json"])
                definition = _load(watch["definition_json"])
                old_pending = conn.execute("SELECT COUNT(*) FROM deliveries d JOIN events e USING(event_id) WHERE e.scope=? AND e.key=? AND d.status IN ('pending','parked')", (self.mode, key)).fetchone()[0]
                if old_pending + len(changes) * len(definition["channels"]) > MAX_PENDING:
                    raise ConflictError("Pending delivery capacity is full; resolve pending intents before committing more changes.")
                revision = watch["revision"] + 1
                conn.execute("DELETE FROM snapshots WHERE scope=? AND key=?", (self.mode, key))
                conn.executemany("INSERT INTO snapshots(scope,key,record_id,record_json,missing_count,removed,last_seen_at) VALUES(?,?,?,?,?,?,?)",
                                 [(self.mode, key, identifier, json_text(item["record"]), item["missing_count"], int(item["removed"]), item["last_seen_at"]) for identifier, item in snapshot.items()])
                for event in changes:
                    conn.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?)", (event["event_id"], self.mode, key, run_id, revision, event["kind"], event["record_id"], json_text(event["before"]) if event["before"] is not None else None, json_text(event["after"]) if event["after"] is not None else None, json_text(event["fields"]), now))
                    conn.executemany("INSERT INTO deliveries(event_id,channel,destination,status,updated_at) VALUES(?,?,?,'pending',?)",
                                     [(event["event_id"], channel["channel"], channel["destination"], now) for channel in definition["channels"]])
                receipt = {"key": key, "scope": self.mode, "run_id": run_id, "base_revision": run["base_revision"],
                           "revision": revision, "status": "committed", "already_committed": False,
                           "event_ids": [row["event_id"] for row in changes[:100]], "event_ids_truncated": len(changes) > 100, "events_count": len(changes),
                           "pending_count": old_pending + len(changes) * len(definition["channels"]),
                           "snapshot_count": sum(not item["removed"] for item in snapshot.values()), "committed_at": now}
                conn.execute("UPDATE runs SET status='committed',receipt_json=? WHERE run_id=?", (json_text(receipt), run_id))
                conn.execute("UPDATE runs SET status='cancelled',snapshot_json=NULL,changes_json=NULL WHERE scope=? AND key=? AND status='staged' AND base_revision<?", (self.mode, key, revision))
                conn.execute("UPDATE watches SET revision=?,initialized=1,last_success_at=?,last_run_at=?,last_error_json=NULL,error_count=0,updated_at=? WHERE scope=? AND key=?", (revision, now, now, now, self.mode, key))
                self._cleanup_in_transaction(conn, key, watch, 25, now)
                return receipt
        except ConflictError as exc:
            self._record_error(key, authority, exc)
            raise

    def discard(self, key: str, run_id: str, authority: Authority) -> dict:
        key = self._key(key)
        run_id = bounded_string(run_id, "run_id", 200)
        with self._connection(write=True) as conn:
            assert conn is not None
            self._authorize(self._watch(conn, key), authority)
            run = conn.execute("SELECT status FROM runs WHERE scope=? AND key=? AND run_id=?", (self.mode, key, run_id)).fetchone()
            if run is None:
                raise NotFoundError("Staged run was not found for this watch.")
            if run["status"] == "committed":
                raise ConflictError("A committed run cannot be discarded; its durable baseline and deliveries remain.")
            already = run["status"] != "staged"
            conn.execute("UPDATE runs SET status='cancelled',snapshot_json=NULL,changes_json=NULL WHERE run_id=?", (run_id,))
            return {"key": key, "scope": self.mode, "run_id": run_id, "status": "cancelled", "already_discarded": already}

    def _intent(self, conn: sqlite3.Connection, key: str, event_id: str, channel: str, destination: str) -> sqlite3.Row:
        bounded_string(event_id, "event_id", 200)
        bounded_string(channel, "channel", 40)
        bounded_string(destination, "destination", 1024)
        row = conn.execute("SELECT d.*,e.scope,e.key,e.record_id,e.kind,e.before_json,e.after_json,e.run_id,e.revision,e.created_at FROM deliveries d JOIN events e USING(event_id) WHERE e.scope=? AND e.key=? AND d.event_id=? AND channel=? AND destination=?", (self.mode, key, event_id, channel, destination)).fetchone()
        if row is None:
            raise NotFoundError("The channel-specific delivery intent was not found.")
        return row

    @staticmethod
    def _intent_data(row: sqlite3.Row) -> dict:
        result = {field: row[field] for field in ("event_id", "scope", "key", "record_id", "kind", "run_id", "revision", "created_at", "channel", "destination", "status", "attempts", "lease_until", "delivered_at")}
        result.update(before=_load(row["before_json"]), after=_load(row["after_json"]), receipt=_load(row["receipt_json"]), error=_load(row["error_json"]))
        return result

    def claim(self, key: str, event_id: str, channel: str, destination: str, authority: Authority, *, lease_seconds: int = 60) -> dict:
        key = self._key(key)
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise ValidationError("lease_seconds must be an integer from 1 to 3600.")
        now = self.clock()
        with self._connection(write=True) as conn:
            assert conn is not None
            watch = self._watch(conn, key)
            self._authorize(watch, authority)
            row = self._intent(conn, key, event_id, channel, destination)
            if row["status"] == "delivered":
                return {**self._intent_data(row), "already_delivered": True, "claimed": False, "claim_token": None}
            if row["status"] != "pending" or self._muted(watch, now):
                raise ConflictError("The delivery is parked, cancelled or muted and cannot be claimed.")
            if row["claim_token"] is not None and row["lease_until"] > now:
                raise ConflictError("Another caller currently holds this delivery claim.")
            if row["attempts"] >= MAX_DELIVERY_ATTEMPTS:
                conn.execute("UPDATE deliveries SET status='parked',claim_token=NULL,lease_until=NULL,error_json=?,updated_at=? WHERE event_id=? AND channel=? AND destination=?", (json_text({"code": "delivery_claim_expired"}), now, event_id, channel, destination))
                return {**self._intent_data(self._intent(conn, key, event_id, channel, destination)), "claimed": False, "claim_token": None, "already_delivered": False}
            token = secrets.token_urlsafe(24)
            error = row["error_json"] or (json_text({"code": "delivery_claim_expired"}) if row["claim_token"] else None)
            conn.execute("UPDATE deliveries SET claim_token=?,lease_until=?,attempts=attempts+1,error_json=?,updated_at=? WHERE event_id=? AND channel=? AND destination=?", (token, now + lease_seconds, error, now, event_id, channel, destination))
            return {**self._intent_data(self._intent(conn, key, event_id, channel, destination)), "claim_token": token, "claimed": True, "already_delivered": False}

    def retry(self, key: str, event_id: str, channel: str, destination: str, authority: Authority) -> dict:
        key = self._key(key)
        if not isinstance(authority, Authority) or not authority.admin:
            raise AuthorityError("Only an administrator may retry a parked delivery.")
        with self._connection(write=True) as conn:
            assert conn is not None
            self._authorize(self._watch(conn, key), authority)
            row = self._intent(conn, key, event_id, channel, destination)
            if row["status"] == "delivered":
                return {**self._intent_data(row), "already_delivered": True}
            if row["status"] != "parked":
                raise ConflictError("Only a parked delivery can be retried.")
            conn.execute("UPDATE deliveries SET status='pending',attempts=0,claim_token=NULL,lease_until=NULL,error_json=NULL,updated_at=? WHERE event_id=? AND channel=? AND destination=?", (self.clock(), event_id, channel, destination))
            return {**self._intent_data(self._intent(conn, key, event_id, channel, destination)), "already_delivered": False}

    def ack(
        self, key: str, event_id: str, channel: str, destination: str, authority: Authority, *,
        success: bool = True, receipt: Any = None, error: Any = None, claim_token: str | None = None,
    ) -> dict:
        key = self._key(key)
        if type(success) is not bool:
            raise ValidationError("success must be a boolean.")
        if claim_token is not None:
            bounded_string(claim_token, "claim_token", 200)
        if success and isinstance(receipt, dict) and receipt.get("ok") is False:
            raise ValidationError("A failed delivery receipt cannot acknowledge successful delivery.")
        validate_json(receipt, maximum=32_000)
        validate_json(error, maximum=2000)
        now = self.clock()
        with self._connection(write=True) as conn:
            assert conn is not None
            watch = self._watch(conn, key)
            self._authorize(watch, authority)
            row = self._intent(conn, key, event_id, channel, destination)
            if row["status"] == "delivered":
                return {**self._intent_data(row), "already_delivered": True}
            if row["status"] != "pending" or not claim_token or not secrets.compare_digest(claim_token, row["claim_token"] or ""):
                raise ConflictError("A matching delivery claim_token is required; the claim may have been reassigned.")
            attempts = row["attempts"]
            status = "delivered" if success else "parked" if attempts >= MAX_DELIVERY_ATTEMPTS else "pending"
            error = None if success else error if error is not None else {"code": "delivery_failed"}
            conn.execute("UPDATE deliveries SET status=?,attempts=?,claim_token=NULL,lease_until=NULL,receipt_json=?,error_json=?,delivered_at=?,updated_at=? WHERE event_id=? AND channel=? AND destination=?", (status, attempts, json_text(receipt) if receipt is not None else None, json_text(error) if error is not None else None, now if success else None, now, event_id, channel, destination))
            if success:
                self._insert_handled(conn, key, row["record_id"], _load(row["after_json"] or row["before_json"]), channel, destination, receipt, now)
            return {**self._intent_data(self._intent(conn, key, event_id, channel, destination)), "already_delivered": False}

    def _insert_handled(self, conn: sqlite3.Connection, key: str, record_id: str, record: dict, channel: str, destination: str, receipt: Any, now: float) -> bool:
        cursor = conn.execute("INSERT OR IGNORE INTO handled_records VALUES(?,?,?,?,?,?,?,?)", (self.mode, key, record_id, channel, destination, json_text(record), json_text(receipt) if receipt is not None else None, now))
        return cursor.rowcount == 1

    def record_delivery(self, key: str, record: dict, channel: str, destination: str, authority: Authority, *, receipt: Any = None) -> dict:
        if isinstance(receipt, dict) and receipt.get("ok") is False:
            raise ValidationError("A failed receipt cannot mark a record as delivered.")
        result = self.import_handled(key, [record], authority, channel, destination, _receipt=receipt, _cleanup=True)
        return {"key": key, "scope": self.mode, "record_id": result["ids"][0], "already_handled": result["imported_count"] == 0, "receipt": result["items"][0]["receipt"], "delivered_at": result["items"][0]["delivered_at"]}

    def import_handled(self, key: str, records: list[dict], authority: Authority, channel: str, destination: str = "legacy", *, _receipt: Any = None, _cleanup: bool = False) -> dict:
        key = self._key(key)
        channel = bounded_string(channel, "channel", 40)
        destination = bounded_string(destination, "destination", 1024)
        validate_json(_receipt, maximum=32_000)
        now = self.clock()
        with self._connection(write=True) as conn:
            assert conn is not None
            watch = self._watch(conn, key)
            self._authorize(watch, authority)
            normalized = normalize_records(records, _load(watch["definition_json"]))
            imported = 0
            items = []
            for identifier, record in normalized.items():
                imported += self._insert_handled(conn, key, identifier, record, channel, destination, _receipt, now)
                row = conn.execute("SELECT * FROM handled_records WHERE scope=? AND key=? AND record_id=? AND channel=? AND destination=?", (self.mode, key, identifier, channel, destination)).fetchone()
                items.append(self._handled_data(row))
            if _cleanup:
                self._cleanup_in_transaction(conn, key, watch, 25, now)
            preview, more = _read_page(items, lambda item: item, 100, 0)
            return {"key": key, "scope": self.mode, "imported_count": imported, "already_handled_count": len(normalized) - imported,
                    "ids": [item["record_id"] for item in preview], "items": preview, "items_truncated": more is not None}

    @staticmethod
    def _handled_data(row: sqlite3.Row) -> dict:
        return {"key": row["key"], "scope": row["scope"], "record_id": row["record_id"], "channel": row["channel"], "destination": row["destination"], "record": _load(row["record_json"]), "receipt": _load(row["receipt_json"]), "delivered_at": row["delivered_at"]}

    def handled(self, key: str, channel: str | None = None, *, limit: int = 100, offset: int = 0) -> dict:
        key = self._key(key)
        _page(limit, offset)
        with self._connection() as conn:
            self._watch(conn, key)
            assert conn is not None
            where = "scope=? AND key=?" + (" AND channel=?" if channel is not None else "")
            params = [self.mode, key] + ([channel] if channel is not None else [])
            rows = conn.execute(f"SELECT * FROM handled_records WHERE {where} ORDER BY record_id,channel,destination LIMIT ? OFFSET ?", (*params, limit + 1, offset))
            items, next_offset = _read_page(rows, self._handled_data, limit, offset)
            return {"key": key, "scope": self.mode, "ids": list(dict.fromkeys(row["record_id"] for row in items)), "items": items, "next_offset": next_offset}

    def _read_scopes(self) -> tuple[str, ...]:
        return (self.mode,) if self.mode == "shared" else (self.mode, "shared")

    def list(self, *, limit: int = 50, offset: int = 0) -> dict:
        _page(limit, offset)
        with self._connection() as conn:
            if conn is None:
                return {"scope": self.mode, "items": [], "next_offset": None}
            scopes = self._read_scopes()
            rows = conn.execute(f"SELECT * FROM watches WHERE scope IN ({','.join('?' for _ in scopes)}) AND deleted_at IS NULL ORDER BY scope,key LIMIT ? OFFSET ?", (*scopes, limit + 1, offset))
            items, next_offset = _read_page(rows, lambda row: self._metadata(conn, row), limit, offset)
            return {"scope": self.mode, "items": items, "next_offset": next_offset}

    def inspect(self, key: str) -> dict:
        key = self._key(key)
        with self._connection() as conn:
            watch = self._watch(conn, key)
            assert conn is not None
            result = self._metadata(conn, watch)
            count = conn.execute("SELECT COUNT(*) FROM snapshots WHERE scope=? AND key=? AND removed=0", (self.mode, key)).fetchone()[0]
            total = conn.execute("SELECT COUNT(*) FROM snapshots WHERE scope=? AND key=?", (self.mode, key)).fetchone()[0]
            rows = conn.execute("SELECT * FROM snapshots WHERE scope=? AND key=? ORDER BY record_id LIMIT 26", (self.mode, key))
            preview, _ = _read_page(rows, lambda row: {"record_id": row["record_id"], "record": _load(row["record_json"]), "missing_count": row["missing_count"], "removed": bool(row["removed"])}, 25, 0, budget=MAX_READ_BYTES - len(json_text(result).encode()))
            result.update(snapshot_count=count, snapshot_records_count=total, snapshot=preview, snapshot_truncated=total > len(preview))
            return result

    def pending(self, key: str | None = None, *, channel: str | None = None, destination: str | None = None, include_parked: bool = False, limit: int = 50, offset: int = 0) -> dict:
        _page(limit, offset)
        if type(include_parked) is not bool:
            raise ValidationError("include_parked must be a boolean.")
        if key is not None:
            key = self._key(key)
        with self._connection() as conn:
            if key is not None:
                self._watch(conn, key)
            if conn is None:
                return {"scope": self.mode, "items": [], "next_offset": None}
            scopes = self._read_scopes() if key is None else (self.mode,)
            conditions = [f"e.scope IN ({','.join('?' for _ in scopes)})", "w.deleted_at IS NULL", "(w.muted_until IS NULL OR (w.muted_until>=0 AND w.muted_until<=?))", "(d.claim_token IS NULL OR d.lease_until<=?)", "d.status IN ('pending','parked')" if include_parked else "d.status='pending'"]
            now = self.clock()
            params: list[Any] = [*scopes, now, now]
            for field, value in (("e.key", key), ("d.channel", channel), ("d.destination", destination)):
                if value is not None:
                    conditions.append(field + "=?")
                    params.append(value)
            rows = conn.execute("SELECT d.*,e.scope,e.key,e.record_id,e.kind,e.before_json,e.after_json,e.run_id,e.revision,e.created_at FROM deliveries d JOIN events e USING(event_id) JOIN watches w ON w.scope=e.scope AND w.key=e.key WHERE " + " AND ".join(conditions) + " ORDER BY e.created_at,e.event_id,d.channel,d.destination LIMIT ? OFFSET ?", (*params, limit + 1, offset))
            items, next_offset = _read_page(rows, self._intent_data, limit, offset)
            return {"scope": self.mode, "items": items, "next_offset": next_offset}

    def history(self, key: str, *, limit: int = 50, offset: int = 0) -> dict:
        key = self._key(key)
        _page(limit, offset)
        with self._connection() as conn:
            self._watch(conn, key)
            assert conn is not None
            rows = conn.execute("SELECT * FROM events WHERE scope=? AND key=? ORDER BY created_at DESC,event_id LIMIT ? OFFSET ?", (self.mode, key, limit + 1, offset))
            items, next_offset = _read_page(rows, lambda row: {"event_id": row["event_id"], "run_id": row["run_id"], "revision": row["revision"], "kind": row["kind"], "record_id": row["record_id"], "before": _load(row["before_json"]), "after": _load(row["after_json"]), "fields": _load(row["fields_json"]), "created_at": row["created_at"]}, limit, offset)
            return {"key": key, "scope": self.mode, "items": items, "next_offset": next_offset}

    def reset(self, key: str, authority: Authority) -> dict:
        key = self._key(key)
        with self._connection(write=True) as conn:
            assert conn is not None
            watch = self._watch(conn, key)
            self._authorize(watch, authority)
            self._clear_baseline(conn, key)
            return self._metadata(conn, self._watch(conn, key))

    def _clear_baseline(self, conn: sqlite3.Connection, key: str) -> None:
        now = self.clock()
        conn.execute("DELETE FROM snapshots WHERE scope=? AND key=?", (self.mode, key))
        conn.execute("UPDATE runs SET status='cancelled',snapshot_json=NULL,changes_json=NULL WHERE scope=? AND key=? AND status='staged'", (self.mode, key))
        conn.execute("UPDATE watches SET initialized=0,revision=revision+1,generation=generation+1,last_run_at=NULL,last_success_at=NULL,last_error_json=NULL,error_count=0,updated_at=? WHERE scope=? AND key=?", (now, self.mode, key))

    def _clear_deleted_history(self, conn: sqlite3.Connection, key: str) -> None:
        # Keep only run headers/commit receipts as replay fences, plus the separate handled ledger.
        conn.execute("DELETE FROM events WHERE scope=? AND key=?", (self.mode, key))
        conn.execute("UPDATE runs SET status=CASE WHEN status='committed' THEN status ELSE 'cancelled' END,snapshot_json=NULL,changes_json=NULL WHERE scope=? AND key=?", (self.mode, key))

    def mute(self, key: str, authority: Authority, *, until: float | None = None, seconds: float | None = None) -> dict:
        key = self._key(key)
        if until is not None and seconds is not None:
            raise ValidationError("Use until or seconds, not both.")
        for value in (until, seconds):
            if value is not None and (type(value) not in (int, float) or not 0 <= value < 1e15):
                raise ValidationError("Mute times must be finite nonnegative numbers.")
        muted_until = until if until is not None else self.clock() + seconds if seconds is not None else -1
        with self._connection(write=True) as conn:
            assert conn is not None
            watch = self._watch(conn, key)
            self._authorize(watch, authority)
            conn.execute("UPDATE watches SET muted_until=?,updated_at=? WHERE scope=? AND key=?", (muted_until, self.clock(), self.mode, key))
            return self._metadata(conn, self._watch(conn, key))

    def delete(self, key: str, authority: Authority, *, delete_handled: bool = False) -> dict:
        key = self._key(key)
        if not isinstance(authority, Authority) or type(delete_handled) is not bool or (delete_handled and not authority.admin):
            raise AuthorityError("Deleting durable handled receipts requires administrator authority.")
        with self._connection(write=True) as conn:
            assert conn is not None
            watch = self._watch(conn, key)
            self._authorize(watch, authority)
            self._clear_baseline(conn, key)
            self._clear_deleted_history(conn, key)
            conn.execute("UPDATE watches SET deleted_at=? WHERE scope=? AND key=?", (self.clock(), self.mode, key))
            if delete_handled:
                conn.execute("DELETE FROM handled_records WHERE scope=? AND key=?", (self.mode, key))
            return {"key": key, "scope": self.mode, "deleted": True, "handled_preserved": not delete_handled}

    def health(self, key: str | None = None) -> dict:
        if key is not None:
            key = self._key(key)
        with self._connection() as conn:
            if key is not None:
                rows = [self._watch(conn, key)]
            elif conn is not None:
                scopes = self._read_scopes()
                rows = conn.execute(f"SELECT * FROM watches WHERE scope IN ({','.join('?' for _ in scopes)}) AND deleted_at IS NULL ORDER BY scope,key LIMIT 1001", scopes)
            else:
                rows = []
            items = []
            used = 2
            totals = {name: 0 for name in ("watches_count", "stale_count", "error_count", "delivery_error_count", "pending_count", "parked_count")}
            complete = True
            item_limit = False
            for index, row in enumerate(rows):
                if index >= 1000:
                    complete = False
                    break
                assert conn is not None
                item = self._metadata(conn, row)
                totals["watches_count"] += 1
                totals["stale_count"] += item["stale"]
                for name in ("error_count", "delivery_error_count", "pending_count", "parked_count"):
                    totals[name] += item[name]
                cost = len(json_text(item).encode()) + 1
                if not item_limit and used + cost <= MAX_READ_BYTES:
                    items.append(item)
                    used += cost
                else:
                    item_limit = True
            return {"scope": self.mode, **totals, "ok": complete and totals["stale_count"] == totals["error_count"] == totals["parked_count"] == 0,
                    "items": items, "items_truncated": item_limit or not complete,
                    "counts_complete": complete, "next_offset": len(items) if item_limit or not complete else None}

    def cleanup(self, key: str, authority: Authority, *, limit: int = 100) -> dict:
        """Bound history cleanup; permanent handled receipts and commit headers remain."""
        key = self._key(key)
        _page(limit, 0)
        now = self.clock()
        with self._connection(write=True) as conn:
            assert conn is not None
            watch = self._watch(conn, key)
            self._authorize(watch, authority)
            return self._cleanup_in_transaction(conn, key, watch, limit, now)

    def _cleanup_in_transaction(self, conn: sqlite3.Connection, key: str, watch: sqlite3.Row, limit: int, now: float) -> dict:
        cutoff = now - _load(watch["definition_json"])["retention_days"] * 86_400
        expired = conn.execute("UPDATE runs SET status='expired',snapshot_json=NULL,changes_json=NULL WHERE run_id IN (SELECT run_id FROM runs WHERE scope=? AND key=? AND status='staged' AND created_at<? LIMIT ?)", (self.mode, key, now - STAGE_TTL_SECONDS, limit)).rowcount
        events = conn.execute("DELETE FROM events WHERE event_id IN (SELECT e.event_id FROM events e WHERE e.scope=? AND e.key=? AND e.created_at<? AND NOT EXISTS(SELECT 1 FROM deliveries d WHERE d.event_id=e.event_id AND d.status IN ('pending','parked')) LIMIT ?)", (self.mode, key, cutoff, limit)).rowcount
        runs = conn.execute("UPDATE runs SET snapshot_json=NULL,changes_json=NULL WHERE run_id IN (SELECT run_id FROM runs WHERE scope=? AND key=? AND status IN ('committed','cancelled','expired') AND created_at<? AND (snapshot_json IS NOT NULL OR changes_json IS NOT NULL) LIMIT ?)", (self.mode, key, cutoff, limit)).rowcount
        removed = conn.execute("DELETE FROM snapshots WHERE rowid IN (SELECT rowid FROM snapshots WHERE scope=? AND key=? AND removed=1 AND last_seen_at<? LIMIT ?)", (self.mode, key, cutoff, limit)).rowcount
        return {"key": key, "scope": self.mode, "expired_runs": expired, "events_deleted": events, "run_payloads_deleted": runs, "removed_records_deleted": removed, "handled_preserved": True}
