"""Local, mode-shared task control store with no import/startup side effects."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import stat
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .delivery import DeliveryStore
from .events import TaskEventLog
from .management import ManagementStore
from .migrations import MIGRATIONS
from .models import (
    MAX_PROGRESS_BYTES,
    MAX_RESULT_BYTES,
    Admission,
    AdmissionDenied,
    Claim,
    Conflict,
    LostLease,
    ReceiptEvidence,
    TaskError,
    canonical_json,
    digest,
    identifier,
)

DEFAULT_SETTINGS = {
    "background_enabled": False,
    "background_tools": [],
    "webhooks_enabled": False,
    "max_running": 2,
    "max_outstanding": 5,
    "max_queued": 100,
    "max_per_adapter": 2,
    "result_retention_days": 30,
}


def default_store_path() -> Path:
    """One control DB for Web conversations in both modes; never a MemoryDB target."""
    return Path(__file__).resolve().parents[2] / "data" / "background_tasks.db"


class TaskStore(DeliveryStore, ManagementStore):
    def __init__(self, path: Path | str | None = None, *, clock=time.time):
        self.path = Path(path if path is not None else default_store_path()).expanduser().absolute()
        self.clock = clock
        self.events = TaskEventLog(self.path)

    def _time(self) -> float:
        now = float(self.clock())
        if not math.isfinite(now):
            raise TaskError("Invalid store clock")
        return now

    def _secure_path(self, *, create=False):
        if create:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            flags = os.O_CREAT | os.O_RDWR | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self.path, flags, 0o600)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise TaskError("Task store must be a regular file")
                os.fchmod(fd, 0o600)
            finally:
                os.close(fd)
        if self.path.is_symlink():
            raise TaskError("Task store cannot be a symlink")
        info = self.path.stat()
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
            raise TaskError("Task store requires an owner-only regular file")

    def initialize(self):
        """Explicit initialization only. Schema and migration stamps commit together."""
        self._secure_path(create=True)
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY, applied_at REAL NOT NULL
            )""")
            versions = [
                row[0]
                for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")
            ]
            if versions != list(range(1, len(versions) + 1)) or len(versions) > len(MIGRATIONS):
                raise TaskError("Unsupported task store schema; use a compatible worker")
            for version in range(len(versions) + 1, len(MIGRATIONS) + 1):
                for statement in MIGRATIONS[version - 1]:
                    conn.execute(statement)
                conn.execute("INSERT INTO schema_migrations VALUES (?, ?)", (version, self._time()))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def _connection(self, *, write=False):
        self._secure_path()
        conn = sqlite3.connect(
            self.path.as_uri() + ("?mode=rw" if write else "?mode=ro"),
            uri=True,
            timeout=5,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            versions = [
                row[0]
                for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")
            ]
            if versions != list(range(1, len(MIGRATIONS) + 1)):
                raise TaskError("Task store needs a supported explicit migration")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _settings(conn):
        values = dict(conn.execute("SELECT * FROM settings WHERE id=1").fetchone())
        values.pop("id")
        for key in ("background_enabled", "webhooks_enabled"):
            values[key] = bool(values[key])
        values["background_tools"] = json.loads(values.get("background_tools", "[]"))
        return values

    def settings(self) -> dict:
        if not self.path.exists():
            return {**DEFAULT_SETTINGS, "background_tools": []}
        with self._connection() as conn:
            return self._settings(conn)

    def configure(self, **changes) -> dict:
        for key, value in changes.items():
            if key not in DEFAULT_SETTINGS:
                raise TaskError("Unknown background setting")
            if key == "background_tools":
                if (not isinstance(value, list) or len(value) > 128
                        or any(not isinstance(name, str) for name in value)
                        or len(set(value)) != len(value)):
                    raise TaskError("Expected distinct background tool names")
                for name in value:
                    identifier(name, "tool name")
            elif key.endswith("enabled"):
                if type(value) is not bool:
                    raise TaskError("Feature settings must be boolean")
            elif (
                type(value) is not int
                or not 1
                <= value
                <= {"max_running": 32, "max_outstanding": 100, "max_queued": 10000, "max_per_adapter": 32, "result_retention_days": 3650}[key]
            ):
                raise TaskError("Invalid task capacity")
        with self._connection(write=True) as conn:
            for key, value in changes.items():
                # Identifiers come only from DEFAULT_SETTINGS, never user SQL.
                if key == "background_tools":
                    value = json.dumps(sorted(value))
                conn.execute(f"UPDATE settings SET {key}=? WHERE id=1", (value,))
            settings = self._settings(conn)
        self.events.emit('settings_changed', component='operator', **settings)
        return settings

    @staticmethod
    def _job(row) -> dict | None:
        if row is None:
            return None
        job = dict(row)
        for field in ("admission", "receipt", "progress", "result"):
            encoded = job.pop(field + "_json")
            job[field] = json.loads(encoded) if encoded is not None else None
        if job.get("expired"):
            job["state"] = "expired"
        elif job.get("cancelled"):
            job["state"] = "cancelled"
        elif job.get("cancel_requested") and job["state"] in {"starting", "running"}:
            job["state"] = "cancel_requested"
        return job

    def get(self, job_id: str) -> dict | None:
        identifier(job_id, "job ID")
        if not self.path.exists():
            return None
        with self._connection() as conn:
            return self._job(conn.execute(self.JOB_SELECT + " WHERE j.id=?", (job_id,)).fetchone())

    def admit(self, admission: Admission, *, authorization=None) -> dict:
        """Internal persistence primitive; caller still owns adapter/auth/readiness checks."""
        payload = admission.serialize()
        fingerprint = digest(payload)
        with self._connection(write=True) as conn:
            if not self._generation_allowed(conn, admission.conversation_id, admission.generation):
                raise AdmissionDenied("Conversation was disposed")
            existing = conn.execute(
                "SELECT * FROM jobs WHERE invocation_key=?", (admission.invocation_key,)
            ).fetchone()
            if existing:
                if existing["admission_digest"] != fingerprint:
                    raise Conflict("Invocation identity already belongs to different work")
                return self._job(existing)
            settings = self._settings(conn)
            if not settings["background_enabled"]:
                raise AdmissionDenied("Background task admission is disabled")
            if admission.tool not in settings["background_tools"]:
                raise AdmissionDenied("This tool is no longer enabled for background execution")
            if admission.adapter == 'http_callback_v1':
                from lib.webhook_integrations.service import IntegrationService
                source_id = (authorization or {}).get('callback_sources', {}).get(admission.tool)
                if not source_id:
                    raise AdmissionDenied('Missing trusted callback source authorization')
                IntegrationService(self)._ready_source(conn, source_id)
            outstanding = conn.execute(
                """SELECT COUNT(*) FROM jobs j WHERE conversation_id=? AND generation=? AND
                (state NOT IN ('succeeded','failed') OR EXISTS (
                    SELECT 1 FROM outbox o WHERE o.job_id=j.id
                    AND o.state NOT IN ('delivered','suppressed')))""",
                (admission.conversation_id, admission.generation),
            ).fetchone()[0]
            queued = conn.execute("SELECT COUNT(*) FROM jobs WHERE state='queued'").fetchone()[0]
            if outstanding >= settings["max_outstanding"] or queued >= settings["max_queued"]:
                raise AdmissionDenied("Background task capacity reached")
            now = self._time()
            job_id = uuid.uuid4().hex
            if authorization is not None:
                if (any(authorization.get(key) != getattr(admission, key)
                        for key in ('conversation_id', 'generation', 'request_id', 'mode', 'source'))
                        or admission.tool not in authorization.get('selected', [])):
                    raise AdmissionDenied("Authorization does not match admission")
                encoded = canonical_json({key: value for key, value in authorization.items()
                                          if key != 'query'}, 65536)
                prior = conn.execute('SELECT payload FROM authorizations WHERE id=?',
                                     (admission.authorization_id,)).fetchone()
                if prior and prior[0] != encoded:
                    raise Conflict("Authorization identity already belongs to different work")
                conn.execute('INSERT OR IGNORE INTO authorizations VALUES(?,?,?)',
                             (admission.authorization_id, encoded, now))
            conn.execute(
                """INSERT INTO jobs (
                id, invocation_key, admission_json, admission_digest, conversation_id,
                generation, mode, adapter, state, dispatch_state, created_at, updated_at, deadline
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', 'held', ?, ?, ?)""",
                (
                    job_id,
                    admission.invocation_key,
                    payload,
                    fingerprint,
                    admission.conversation_id,
                    admission.generation,
                    admission.mode,
                    admission.adapter,
                    now,
                    now,
                    now + admission.timeout_seconds,
                ),
            )
            job = self._job(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
        self.events.emit('job_accepted', component='web', job=job)
        return job

    def release(self, job_id: str, evidence: ReceiptEvidence) -> dict:
        """Make a held admission claimable only with matching source settlement evidence."""
        proof = evidence.serialize()
        with self._connection(write=True) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise TaskError("Unknown job")
            admission = json.loads(row["admission_json"])
            if not self._generation_allowed(conn, row['conversation_id'], row['generation']):
                raise AdmissionDenied("Conversation was disposed")
            if any(
                admission[key] != getattr(evidence, key)
                for key in ("conversation_id", "generation", "request_id")
            ):
                raise Conflict("Receipt belongs to a different originating request")
            if row["receipt_json"] is not None:
                if row["receipt_json"] != proof:
                    raise Conflict("Job already has different receipt evidence")
                return self._job(row)
            if row["state"] != "queued" or row["deadline"] <= self._time():
                raise AdmissionDenied("Held job is no longer eligible for dispatch")
            conn.execute(
                """UPDATE jobs SET dispatch_state='ready', receipt_json=?, updated_at=?
                WHERE id=?""",
                (proof, self._time(), job_id),
            )
            return self._job(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    @staticmethod
    def _ttl(seconds):
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise TaskError("Invalid lease duration")
        if not math.isfinite(seconds) or not 0 < seconds <= 3600:
            raise TaskError("Invalid lease duration")
        return seconds

    @staticmethod
    def _recover(conn, now):
        expired = conn.execute(
            """SELECT id, attempt_id FROM jobs
            WHERE state IN ('starting','running') AND ((callback_waiting=0 AND lease_expires_at<=?) OR deadline<=?)""",
            (now, now),
        ).fetchall()
        for row in expired:
            conn.execute(
                """UPDATE jobs SET state='needs_attention', updated_at=?, fence=fence+1,
                attention_reason='Execution ownership or observation deadline expired; not retried'
                WHERE id=?""",
                (now, row["id"]),
            )
            conn.execute(
                """UPDATE attempts SET finished_at=?, outcome='needs_attention'
                WHERE id=?""",
                (now, row["attempt_id"]),
            )
        held = conn.execute("SELECT id FROM jobs WHERE state='queued' AND deadline<=?", (now,)).fetchall()
        payload = canonical_json({"ok": False, "speech": "Task expired before execution; it was never dispatched."}, MAX_RESULT_BYTES)
        for row in held:
            conn.execute("""UPDATE jobs SET state='failed',expired=1,updated_at=?,result_json=?,result_digest=?,
                attention_reason='Admission deadline expired before execution; not dispatched' WHERE id=?""",
                         (now, payload, digest(payload), row['id']))
            conn.execute("INSERT INTO outbox(id,job_id,result_digest,state,created_at) VALUES(?,?,?,'suppressed',?)",
                         (uuid.uuid4().hex, row['id'], digest(payload), now))
        return len(expired) + len(held)

    def reconcile(self) -> int:
        """Fence uncertain executions; never turn interrupted attempts back into queued jobs."""
        with self._connection(write=True) as conn:
            count = self._recover(conn, self._time())
        if count:
            self.events.emit('expired_work_recovered', component='store', level='WARNING', count=count)
        return count

    def claim(self, owner: str, adapters: set[str], *, lease_seconds=30) -> Claim | None:
        identifier(owner, "worker owner")
        names = sorted({identifier(name, "adapter") for name in adapters})
        self._ttl(lease_seconds)
        if not names:
            return None
        with self._connection(write=True) as conn:
            now = self._time()
            self._recover(conn, now)
            # Unknown executions reserve capacity until explicit reconciliation.
            active = conn.execute("""SELECT COUNT(*) FROM jobs WHERE
                (state IN ('starting','running') AND callback_waiting=0) OR
                (state='needs_attention' AND attempt_id IS NOT NULL)""").fetchone()[0]
            if active >= self._settings(conn)["max_running"]:
                return None
            slots = ",".join("?" for _ in names)
            row = conn.execute(
                f"""SELECT * FROM jobs WHERE state='queued'
                AND dispatch_state='ready' AND receipt_json IS NOT NULL AND adapter IN ({slots})
                AND (SELECT COUNT(*) FROM jobs active WHERE
                    active.adapter = jobs.adapter
                    AND ((active.state IN ('starting','running') AND active.callback_waiting=0) OR
                        (active.state='needs_attention' AND active.attempt_id IS NOT NULL))) < ?
                ORDER BY created_at, id LIMIT 1""",
                [*names, self._settings(conn)["max_per_adapter"]],
            ).fetchone()
            if row is None:
                return None
            attempt_id = uuid.uuid4().hex
            fence = row["fence"] + 1
            conn.execute(
                """UPDATE jobs SET state='starting', owner=?, attempt_id=?, fence=?,
                lease_expires_at=?, heartbeat_at=?, updated_at=? WHERE id=?""",
                (
                    owner,
                    attempt_id,
                    fence,
                    now + lease_seconds,
                    now,
                    now,
                    row["id"],
                ),
            )
            conn.execute(
                "INSERT INTO attempts(id,job_id,owner,fence,started_at) VALUES(?,?,?,?,?)",
                (attempt_id, row["id"], owner, fence, now),
            )
            job = self._job(conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())
            return Claim(row["id"], attempt_id, owner, fence, job)

    def _owned(self, conn, claim):
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (claim.job_id,)).fetchone()
        if row is None or (row["owner"], row["attempt_id"], row["fence"]) != (
            claim.owner,
            claim.attempt_id,
            claim.fence,
        ):
            raise LostLease("Execution identity is no longer current")
        return row

    def _active(self, conn, claim):
        row = self._owned(conn, claim)
        if row["state"] not in {"starting", "running"} or row["lease_expires_at"] <= self._time():
            raise LostLease("Execution lease is inactive or expired")
        if row["deadline"] <= self._time():
            raise LostLease("Execution observation deadline expired")
        return row

    def running(self, claim: Claim):
        with self._connection(write=True) as conn:
            self._active(conn, claim)
            conn.execute(
                "UPDATE jobs SET state='running', updated_at=? WHERE id=?",
                (self._time(), claim.job_id),
            )

    def renew(self, claim: Claim, *, lease_seconds=30):
        self._ttl(lease_seconds)
        with self._connection(write=True) as conn:
            self._active(conn, claim)
            now = self._time()
            conn.execute(
                "UPDATE jobs SET lease_expires_at=?, heartbeat_at=? WHERE id=?",
                (now + lease_seconds, now, claim.job_id),
            )

    def progress(self, claim: Claim, value: dict):
        if not isinstance(value, dict):
            raise TaskError("Progress must be an object")
        payload = canonical_json(value, MAX_PROGRESS_BYTES)
        with self._connection(write=True) as conn:
            self._active(conn, claim)
            conn.execute(
                "UPDATE jobs SET progress_json=?, updated_at=? WHERE id=?",
                (payload, self._time(), claim.job_id),
            )

    def finish(self, claim: Claim, result: dict, *, succeeded=True) -> str:
        if not isinstance(result, dict) or type(succeeded) is not bool:
            raise TaskError("Invalid task outcome")
        payload = canonical_json(result, MAX_RESULT_BYTES)
        fingerprint = digest(payload)
        state = "succeeded" if succeeded else "failed"
        with self._connection(write=True) as conn:
            row = self._owned(conn, claim)
            if row["state"] in {"succeeded", "failed"}:
                if row["state"] != state or row["result_digest"] != fingerprint:
                    raise Conflict("A different terminal result was already committed")
                return conn.execute(
                    "SELECT id FROM outbox WHERE job_id=?", (claim.job_id,)
                ).fetchone()[0]
            self._active(conn, claim)
            now = self._time()
            delivery_id = uuid.uuid4().hex
            conn.execute(
                """UPDATE jobs SET state=?, callback_waiting=0, result_json=?, result_digest=?,
                updated_at=?, progress_json=NULL WHERE id=?""",
                (state, payload, fingerprint, now, claim.job_id),
            )
            conn.execute(
                "UPDATE attempts SET finished_at=?, outcome=? WHERE id=?",
                (now, state, claim.attempt_id),
            )
            conn.execute(
                "INSERT INTO outbox(id,job_id,result_digest,created_at) VALUES(?,?,?,?)",
                (delivery_id, claim.job_id, fingerprint, now),
            )
            return delivery_id

    def record_local_stop(self, claim: Claim):
        """Accept only a supervisor's stop proof for this exact local attempt.

        Recovery cannot infer this from a PID or expired lease. A surviving
        supervisor can report verified termination even after expiry recovery
        fences normal writes. It cannot replace an operator disposition or
        write through a conversation disposal fence.
        """
        from .local_contract import LOCAL_ADAPTERS

        with self._connection(write=True) as conn:
            row = conn.execute('SELECT * FROM jobs WHERE id=?', (claim.job_id,)).fetchone()
            recovered = bool(row and row['state'] == 'needs_attention'
                and row['fence'] == claim.fence + 1
                and row['attention_reason'] == 'Execution ownership or observation deadline expired; not retried')
            if (not row or row['adapter'] not in LOCAL_ADAPTERS
                    or (row['owner'], row['attempt_id']) != (claim.owner, claim.attempt_id)
                    or not ((row['state'] in {'starting', 'running'} and row['fence'] == claim.fence) or recovered)
                    or not self._generation_allowed(conn, row['conversation_id'], row['generation'])):
                raise LostLease('Local stop proof no longer belongs to a current attempt')
            self._operator_terminal(conn, row, cancelled=bool(row['cancel_requested']),
                                    evidence='Supervisor verified local process-group termination or no launch',
                                    verified_stop=True)

    def attention(self, claim: Claim, reason: str):
        """Fence an interrupted/unknown adapter outcome instead of pretending it failed safely."""
        with self._connection(write=True) as conn:
            self._active(conn, claim)
            now = self._time()
            conn.execute(
                """UPDATE jobs SET state='needs_attention', fence=fence+1,
                attention_reason=?, updated_at=? WHERE id=?""",
                (reason[:500], now, claim.job_id),
            )
            conn.execute(
                "UPDATE attempts SET finished_at=?, outcome='needs_attention' WHERE id=?",
                (now, claim.attempt_id),
            )

    def pending_deliveries(self, *, limit=100) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise TaskError("Invalid delivery batch limit")
        if not self.path.exists():
            return []
        with self._connection() as conn:
            return [
                dict(row)
                for row in conn.execute(
                """SELECT * FROM outbox WHERE state NOT IN ('delivered','suppressed')
                AND next_attempt_at<=? ORDER BY created_at, id LIMIT ?""", (self._time(), limit)
                )
            ]

    def touch_worker(self, owner: str, adapters: set[str], *, lease_seconds=30, draining=False):
        identifier(owner, "worker owner")
        self._ttl(lease_seconds)
        payload = canonical_json(sorted(identifier(name, "adapter") for name in adapters), 4096)
        with self._connection(write=True) as conn:
            now = self._time()
            conn.execute(
                """INSERT INTO workers VALUES(?,?,?,?,?) ON CONFLICT(owner)
                DO UPDATE SET adapters_json=excluded.adapters_json, heartbeat_at=excluded.heartbeat_at,
                    lease_expires_at=excluded.lease_expires_at, draining=excluded.draining""",
                (owner, payload, now, now if draining else now + lease_seconds, int(draining)),
            )

    def healthy_workers(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self._connection() as conn:
            workers = []
            for row in conn.execute(
                "SELECT * FROM workers WHERE draining=0 AND lease_expires_at>?", (self._time(),)
            ):
                worker = dict(row)
                worker["adapters"] = json.loads(worker.pop("adapters_json"))
                workers.append(worker)
            return workers
