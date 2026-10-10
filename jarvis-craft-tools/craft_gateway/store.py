"""Durable admission and explicit remote outcomes; interrupted work is never replayed."""
import contextlib
import hashlib
import json
import mimetypes
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from .models import ID_PATTERN

TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}

class Conflict(ValueError):
    pass

class Store:
    def __init__(self, root: Path, queue_limit=8):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.workspaces = self.root / "projects"
        self.workspaces.mkdir(exist_ok=True, mode=0o700)
        self.path = self.root / "jobs.sqlite3"
        self.queue_limit = queue_limit
        self.lock = threading.RLock()
        with self.db() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS artifacts (id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                    job_id TEXT, path TEXT NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL,
                    mime_type TEXT NOT NULL, size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
                    body TEXT NOT NULL, project_id TEXT NOT NULL, state TEXT NOT NULL,
                    cancel_requested INTEGER NOT NULL DEFAULT 0, error TEXT,
                    app_version TEXT NOT NULL, binary TEXT NOT NULL, created REAL NOT NULL,
                    renderer TEXT, process_pid INTEGER, process_start TEXT);
            ''')
        self.path.chmod(0o600)

    @contextlib.contextmanager
    def db(self):
        with self.lock:
            db = sqlite3.connect(self.path, timeout=10)
            db.row_factory = sqlite3.Row
            try:
                with db:
                    yield db
            finally:
                db.close()

    def identify(self, value):
        if not re.fullmatch(ID_PATTERN, value):
            raise ValueError("Invalid identifier")
        return value

    def project(self, project_id):
        self.identify(project_id)
        with self.db() as db:
            row = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if row is None:
                raise KeyError("Project does not exist")
            artifacts = db.execute("SELECT id,name,role,mime_type,size_bytes,sha256,job_id FROM artifacts WHERE project_id=?", (project_id,)).fetchall()
            return {**dict(row), "artifacts": [dict(item) for item in artifacts]}

    def create_project(self):
        project_id = uuid.uuid4().hex
        (self.workspaces / project_id).mkdir(mode=0o700)
        with self.db() as db:
            db.execute("INSERT INTO projects(id) VALUES(?)", (project_id,))
        return self.project(project_id)

    def artifact(self, artifact_id, project_id=None):
        self.identify(artifact_id)
        with self.db() as db:
            row = db.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
        if row is None or (project_id is not None and row["project_id"] != project_id):
            raise KeyError("Artifact does not exist in this project")
        result = dict(row)
        path = (self.root / result["path"]).resolve()
        if not path.is_relative_to(self.workspaces / result["project_id"]) or not path.is_file():
            raise ValueError("Artifact path is missing or outside its workspace")
        result["path"] = path
        return result

    def add_artifact(self, project_id, path, role="input", job_id=None):
        self.project(project_id)
        path = path.resolve()
        if not path.is_relative_to(self.workspaces / project_id) or not path.is_file():
            raise ValueError("Artifact outside project")
        artifact_id = uuid.uuid4().hex
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        result = {"id": artifact_id, "project_id": project_id, "job_id": job_id,
                  "path": str(path.relative_to(self.root)), "name": path.name, "role": role,
                  "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                  "size_bytes": path.stat().st_size, "sha256": digest.hexdigest()}
        with self.db() as db:
            db.execute("INSERT INTO artifacts VALUES(:id,:project_id,:job_id,:path,:name,:role,:mime_type,:size_bytes,:sha256)", result)
        return {k: v for k, v in result.items() if k != "path"}

    def submit(self, submission, binary, version):
        body = submission.model_dump_json(exclude_unset=True)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT id,body FROM jobs WHERE request_id=?", (submission.request_id,)).fetchone()
            if prior:
                if prior['body'] != body:
                    raise Conflict("Request ID already belongs to different parameters")
                return self.job(prior['id'])
            project = db.execute("SELECT revision FROM projects WHERE id=?", (submission.project_id,)).fetchone()
            if project is None:
                raise KeyError("Project does not exist")
            if project['revision'] != submission.revision:
                raise Conflict("Project revision changed; inspect the project before editing")
            if db.execute("SELECT 1 FROM jobs WHERE project_id=? AND state IN ('queued','running')", (submission.project_id,)).fetchone():
                raise Conflict("Project already has an active writer")
            if db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0] >= self.queue_limit:
                raise Conflict("Gateway queue is full")
            job_id = uuid.uuid4().hex
            db.execute("INSERT INTO jobs(id,request_id,body,project_id,state,app_version,binary,created) VALUES(?,?,?,?,?,?,?,?)",
                       (job_id, submission.request_id, body, submission.project_id, "queued", version, str(binary), time.time()))
        return self.job(job_id)

    def job(self, job_id=None, request_id=None):
        self.identify(job_id or request_id)
        with self.db() as db:
            row = db.execute("SELECT * FROM jobs WHERE " + ("id=?" if job_id else "request_id=?"), (job_id or request_id,)).fetchone()
            if row is None:
                raise KeyError("Job does not exist")
            outputs = db.execute("SELECT id,name,role,mime_type,size_bytes,sha256 FROM artifacts WHERE job_id=?", (row['id'],)).fetchall()
        return {k: row[k] for k in ('id','request_id','project_id','state','cancel_requested','error','app_version','created','renderer')} | {
            "revision": json.loads(row['body'])['revision'], "operation": json.loads(row['body'])['operation'], "outputs": [dict(item) for item in outputs] if row['state'] == 'succeeded' else []}

    def recent_jobs(self):
        with self.db() as db:
            rows = db.execute("SELECT id FROM jobs ORDER BY created DESC LIMIT 20").fetchall()
        return [self.job(row['id']) for row in rows]

    def claim(self):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            if row:
                db.execute("UPDATE jobs SET state='running' WHERE id=?", (row['id'],))
                return dict(row)
        return None

    def process_started(self, job_id, pid):
        # Linux start time prevents PID reuse from killing an unrelated process.
        start = process_identity(pid)
        with self.db() as db:
            db.execute("UPDATE jobs SET process_pid=?,process_start=? WHERE id=?", (pid, start, job_id))

    def finish(self, job_id, state, error=None, renderer=None):
        assert state in TERMINAL
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE jobs SET state=?,error=?,renderer=?,process_pid=NULL,process_start=NULL WHERE id=?", (state, error, renderer, job_id))
            if state == 'succeeded':
                db.execute("UPDATE projects SET revision=revision+1 WHERE id=(SELECT project_id FROM jobs WHERE id=?)", (job_id,))

    def cancel(self, job_id):
        self.job(job_id)
        with self.db() as db:
            db.execute("UPDATE jobs SET cancel_requested=1,state=CASE WHEN state='queued' THEN 'cancelled' ELSE state END WHERE id=? AND state IN ('queued','running')", (job_id,))
        return self.job(job_id)

    def interrupted(self):
        with self.db() as db:
            return [dict(row) for row in db.execute("SELECT * FROM jobs WHERE state='running'")]


def process_identity(pid):
    try:
        # /proc stat's comm field can contain spaces and parentheses.
        tail = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return Path('/proc/sys/kernel/random/boot_id').read_text().strip() + ':' + tail[19]
    except (OSError, IndexError):
        return None
