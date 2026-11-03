"""Private SQLite state for workflow drafts and supervised builder runs."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ACTIVE_STATUSES = ('starting', 'running', 'awaiting_approval', 'cancelling')


class BuilderError(ValueError):
    """A safe error envelope that can be returned to the editor."""

    def __init__(self, message: str, status: int = 400, **details: Any):
        super().__init__(message)
        self.status = status
        self.details = details


def encoded(value: Any) -> str:
    """Canonical JSON for immutable hashes and internal snapshots."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class BuilderStore:
    """Versioned control store; no operation touches Jarvis's other databases."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise BuilderError('Builder database cannot be a symlink')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise BuilderError('Unsupported workflow builder database schema')
            if version == 0:
                for statement in (
                    'CREATE TABLE drafts (id TEXT PRIMARY KEY, document TEXT NOT NULL, revision INTEGER NOT NULL, source_id TEXT, source_hash TEXT, created REAL NOT NULL, updated REAL NOT NULL)',
                    'CREATE TABLE catalog (mode TEXT PRIMARY KEY, document TEXT NOT NULL, updated REAL NOT NULL)',
                    'CREATE TABLE preparations (token TEXT PRIMARY KEY, document TEXT NOT NULL, expires REAL NOT NULL)',
                    'CREATE TABLE runs (id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL, status TEXT NOT NULL, document TEXT NOT NULL, result TEXT, created REAL NOT NULL, updated REAL NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0)',
                    'CREATE TABLE events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE, document TEXT NOT NULL, created REAL NOT NULL)',
                    'CREATE INDEX events_run ON events(run_id, sequence)',
                    'CREATE TABLE worker_processes (run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE, pid INTEGER NOT NULL, started TEXT NOT NULL, parent INTEGER NOT NULL, boot_id TEXT NOT NULL, PRIMARY KEY(run_id,pid,started,boot_id))',
                    'CREATE TABLE approvals (id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE, call_hash TEXT NOT NULL, document TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL)',
                    "CREATE UNIQUE INDEX one_active_run ON runs ((1)) WHERE status IN ('starting','running','awaiting_approval','cancelling')",
                ):
                    db.execute(statement)
                db.execute('PRAGMA user_version=1')
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=15000')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _draft(row: sqlite3.Row) -> dict[str, Any]:
        document = json.loads(row['document'])
        return {'id': row['id'], 'workflow': document, 'definition': document,
                'revision': row['revision'], 'source_id': row['source_id'],
                'base_hash': row['source_hash'], 'source_hash': row['source_hash'],
                'created_at': row['created'], 'updated_at': row['updated']}

    def create_draft(self, workflow: dict, source_id=None, source_hash=None) -> dict:
        now = time.time()
        draft_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute('INSERT INTO drafts VALUES (?,?,1,?,?,?,?)',
                       (draft_id, encoded(workflow), source_id, source_hash, now, now))
        return self.get_draft(draft_id)

    def get_draft(self, draft_id: str) -> dict:
        with self.connect() as db:
            row = db.execute('SELECT * FROM drafts WHERE id=?', (draft_id,)).fetchone()
        if row is None:
            raise BuilderError('Draft not found', 404)
        return self._draft(row)

    def list_drafts(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute('SELECT * FROM drafts ORDER BY updated DESC').fetchall()
        return [self._draft(row) for row in rows]

    def update_draft(self, draft_id: str, workflow: dict, revision: int) -> dict:
        with self.connect() as db:
            changed = db.execute('UPDATE drafts SET document=?, revision=revision+1, updated=? WHERE id=? AND revision=?',
                                 (encoded(workflow), time.time(), draft_id, revision)).rowcount
            if not changed:
                raise BuilderError('Draft changed in another tab; reload before saving', 409)
        return self.get_draft(draft_id)

    def catalog(self, mode: str) -> dict | None:
        with self.connect() as db:
            row = db.execute('SELECT * FROM catalog WHERE mode=?', (mode,)).fetchone()
        return {'tools': json.loads(row['document']), 'updated_at': row['updated']} if row else None

    def save_catalog(self, mode: str, tools: list[dict]) -> None:
        with self.connect() as db:
            db.execute('INSERT INTO catalog VALUES (?,?,?) ON CONFLICT(mode) DO UPDATE SET document=excluded.document, updated=excluded.updated',
                       (mode, encoded(tools), time.time()))

    def prepare(self, document: dict) -> str:
        token = uuid.uuid4().hex + uuid.uuid4().hex
        with self.connect() as db:
            db.execute('DELETE FROM preparations WHERE expires<?', (time.time(),))
            db.execute('INSERT INTO preparations VALUES (?,?,?)',
                       (token, encoded(document), time.time() + 300))
        return token

    def preparation(self, token: str) -> dict:
        with self.connect() as db:
            row = db.execute('SELECT * FROM preparations WHERE token=?', (token,)).fetchone()
        if row is None or row['expires'] < time.time():
            raise BuilderError('Run confirmation expired; review the effects again', 409)
        return json.loads(row['document'])

    @staticmethod
    def _run(row: sqlite3.Row, *, internal=False) -> dict:
        document = json.loads(row['document'])
        if not internal:
            document.pop('workflow', None)
            document.pop('query', None)
            document.pop('confirmation_digest', None)
            document.pop('worker_identity', None)
        result = json.loads(row['result']) if row['result'] else None
        if not internal and isinstance(result, dict) and '_pending_status' in result:
            result = result.get('output')
        return {**document, 'id': row['id'], 'status': row['status'], 'result': result,
                'created_at': row['created'], 'updated_at': row['updated'],
                'cancel_requested': bool(row['cancel_requested'])}

    def admit(self, token: str, idempotency_key: str) -> tuple[dict, bool]:
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM runs WHERE idempotency_key=?',
                                  (idempotency_key,)).fetchone()
            if existing:
                existing_document = json.loads(existing['document'])
                if existing_document.get('confirmation_digest') != hashlib.sha256(token.encode()).hexdigest():
                    raise BuilderError('Idempotency key was already used for a different confirmed run', 409)
                return self._run(existing), False
            row = db.execute('SELECT * FROM preparations WHERE token=?', (token,)).fetchone()
            if not row or row['expires'] < time.time():
                raise BuilderError('Run confirmation expired; review the effects again', 409)
            if db.execute("SELECT id FROM runs WHERE status IN ('starting','running','awaiting_approval','cancelling')").fetchone():
                raise BuilderError('A builder run is already active', 409)
            document = json.loads(row['document'])
            document['confirmation_digest'] = hashlib.sha256(token.encode()).hexdigest()
            now = time.time()
            run_id = uuid.uuid4().hex
            db.execute('INSERT INTO runs VALUES (?,?,?, ?,NULL,?,?,0)',
                       (run_id, idempotency_key, 'starting', encoded(document), now, now))
            db.execute('DELETE FROM preparations WHERE token=?', (token,))
        self.prune()
        return self.get_run(run_id), True

    def get_run(self, run_id: str, *, internal=False) -> dict:
        with self.connect() as db:
            row = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise BuilderError('Run not found', 404)
        return self._run(row, internal=internal)

    def list_runs(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute('SELECT * FROM runs ORDER BY created DESC LIMIT 500').fetchall()
        return [self._run(row) for row in rows]

    def active_run(self) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE status IN ('starting','running','awaiting_approval','cancelling')").fetchone()
        return self._run(row) if row else None

    def record_processes(self, run_id: str, processes: dict[int, dict]) -> None:
        with self.connect() as db:
            db.executemany('INSERT OR IGNORE INTO worker_processes VALUES (?,?,?,?,?)',
                           [(run_id, item['pid'], item['started'], item['parent'], item['boot_id'])
                            for item in processes.values()])

    def worker_processes(self, run_id: str) -> dict[int, dict]:
        with self.connect() as db:
            rows = db.execute('SELECT pid,started,parent,boot_id FROM worker_processes WHERE run_id=? ORDER BY CAST(started AS INTEGER)', (run_id,)).fetchall()
        return {row['pid']: dict(row) for row in rows}

    def set_worker_identity(self, run_id: str, identity: dict) -> None:
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT document FROM runs WHERE id=?', (run_id,)).fetchone()
            document = json.loads(row['document'])
            document['worker_identity'] = identity
            db.execute('UPDATE runs SET document=? WHERE id=?', (encoded(document), run_id))

    def finish_worker(self, run_id: str, status: str, result=None) -> None:
        # Only the supervisor releases the active slot, after verified process exit.
        with self.connect() as db:
            db.execute("UPDATE runs SET result=?,updated=? WHERE id=? AND status IN ('starting','running','awaiting_approval','cancelling')",
                       (encoded({'_pending_status': status, 'output': result}), time.time(), run_id))

    def finalize_worker(self, run_id: str, status: str | None = None) -> None:
        run = self.get_run(run_id, internal=True)
        pending = run.get('result')
        result = pending.get('output') if isinstance(pending, dict) and '_pending_status' in pending else pending
        terminal = status or (pending.get('_pending_status') if isinstance(pending, dict) else None) or 'interrupted'
        self.set_status(run_id, terminal, result or {'error': 'Worker stopped without a completion result; inspect recovery references before rerunning'})

    def set_status(self, run_id: str, status: str, result=None) -> None:
        with self.connect() as db:
            # A cancelled/terminated run cannot be resurrected by a late worker.
            db.execute("UPDATE runs SET status=?, result=COALESCE(?,result), updated=? WHERE id=? AND status IN ('starting','running','awaiting_approval','cancelling')",
                       (status, encoded(result) if result is not None else None, time.time(), run_id))
            if status not in ACTIVE_STATUSES:
                db.execute("UPDATE approvals SET status='expired' WHERE run_id=? AND status='pending'", (run_id,))

    def cancel(self, run_id: str) -> dict:
        self.get_run(run_id)
        with self.connect() as db:
            db.execute("UPDATE runs SET cancel_requested=1,status='cancelling',updated=? WHERE id=? AND status IN ('starting','running','awaiting_approval','cancelling')", (time.time(), run_id))
        return self.get_run(run_id)

    def event(self, run_id: str, payload: dict) -> None:
        with self.connect() as db:
            db.execute('INSERT INTO events (run_id,document,created) VALUES (?,?,?)',
                       (run_id, encoded(payload), time.time()))
            # Bounded even for unexpectedly chatty integrations.
            db.execute('DELETE FROM events WHERE run_id=? AND sequence NOT IN (SELECT sequence FROM events WHERE run_id=? ORDER BY sequence DESC LIMIT 5000)', (run_id, run_id))

    def events(self, run_id: str, after: int = 0) -> list[dict]:
        with self.connect() as db:
            rows = db.execute('SELECT * FROM events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT 300', (run_id, after)).fetchall()
        return [{**json.loads(row['document']), 'sequence': row['sequence'],
                 'created_at': row['created']} for row in rows]

    def request_approval(self, run_id: str, payload: dict) -> str:
        approval_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute('INSERT INTO approvals VALUES (?,?,?,?,?,?,?)',
                       (approval_id, run_id, payload['call_hash'], encoded(payload), 'pending',
                        time.time(), time.time() + 300))
        self.set_status(run_id, 'awaiting_approval')
        return approval_id

    def approvals(self, run_id: str) -> list[dict]:
        with self.connect() as db:
            db.execute("UPDATE approvals SET status='expired' WHERE expires<? AND status='pending'", (time.time(),))
            rows = db.execute('SELECT * FROM approvals WHERE run_id=? ORDER BY created', (run_id,)).fetchall()
        return [{**json.loads(row['document']), 'payload': json.loads(row['document']),
                 'id': row['id'], 'status': row['status'], 'expires_at': row['expires']}
                for row in rows]

    def decide(self, approval_id: str, approved: bool, call_hash: str) -> None:
        with self.connect() as db:
            changed = db.execute("UPDATE approvals SET status=? WHERE id=? AND call_hash=? AND status='pending' AND expires>? AND run_id IN (SELECT id FROM runs WHERE status='awaiting_approval' AND cancel_requested=0)",
                                 ('approved' if approved else 'denied', approval_id,
                                  call_hash, time.time())).rowcount
        if not changed:
            raise BuilderError('Approval expired, changed, or already answered', 409)

    def prune(self) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM runs WHERE status NOT IN ('starting','running','awaiting_approval','cancelling') AND (created<? OR id NOT IN (SELECT id FROM runs ORDER BY created DESC LIMIT 500))", (time.time() - 30 * 86400,))
