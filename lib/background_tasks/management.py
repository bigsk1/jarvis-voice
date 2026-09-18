"""Operator mutations: cancellation is a request until termination is verified."""

import uuid

from .models import MAX_RESULT_BYTES, Conflict, TaskError, canonical_json, digest, identifier


class ManagementStore:
    @staticmethod
    def _event(conn, job_id, action, evidence, now):
        conn.execute(
            "INSERT INTO operator_events(job_id,action,evidence,created_at) VALUES(?,?,?,?)",
            (job_id, action, evidence, now),
        )

    @staticmethod
    def _operator_job(conn, job_id, revision):
        identifier(job_id, "job ID")
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise TaskError("Job not found")
        if type(revision) is not int or row["revision"] != revision:
            raise Conflict("Job changed; refresh before acting")
        return row

    def list_jobs(self, *, conversation_id=None, tool=None, state=None, offset=0, limit=25):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise TaskError("Invalid page")
        where, values = [], []
        if conversation_id:
            identifier(conversation_id, "conversation ID")
            where.append("j.conversation_id=?")
            values.append(conversation_id)
        if tool:
            identifier(tool, "tool")
            where.append("json_extract(j.admission_json,'$.tool')=?")
            values.append(tool)
        states = {
            "cancelled": "j.cancelled=1",
            "cancel_requested": "j.cancel_requested=1 AND j.state IN ('starting','running')",
            "failed": "j.state='failed' AND j.cancelled=0 AND j.expired=0",
            "expired": "j.expired=1",
            **{name: f"j.state='{name}'" for name in ("queued", "starting", "running", "needs_attention", "succeeded")},
        }
        if state:
            if state not in states:
                raise TaskError("Invalid state filter")
            where.append(states[state])
        if not self.path.exists():
            return {"jobs": [], "total": 0, "next_offset": None}
        clause = " WHERE " + " AND ".join(where) if where else ""
        with self._connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM jobs j" + clause, values).fetchone()[0]
            rows = conn.execute(
                self.JOB_SELECT + clause + " ORDER BY j.created_at DESC,j.id DESC LIMIT ? OFFSET ?",
                [*values, limit, offset],
            ).fetchall()
            return {"jobs": [self._job(row) for row in rows], "total": total,
                    "next_offset": offset + limit if offset + limit < total else None}

    def counts(self):
        if not self.path.exists():
            return {"outstanding": 0, "running": 0, "reserved": 0, "unread": 0}
        with self._connection() as conn:
            row = conn.execute("""SELECT
                COALESCE(SUM(j.state NOT IN ('succeeded','failed') OR EXISTS
                    (SELECT 1 FROM outbox o WHERE o.job_id=j.id AND o.state NOT IN ('delivered','suppressed'))),0),
                COALESCE(SUM(j.state IN ('starting','running')),0),
                COALESCE(SUM(j.state='needs_attention' AND j.attempt_id IS NOT NULL),0),
                COALESCE(SUM(j.state IN ('succeeded','failed','needs_attention')
                    AND (j.read_at IS NULL OR j.read_at<j.updated_at)),0)
                FROM jobs j""").fetchone()
            return dict(zip(("outstanding", "running", "reserved", "unread"), row))

    def job_detail(self, job_id):
        job = self.get(job_id)
        if not job:
            raise TaskError("Job not found")
        with self._connection() as conn:
            job["attempts"] = [dict(row) for row in conn.execute(
                "SELECT * FROM attempts WHERE job_id=? ORDER BY started_at", (job_id,))]
            job["operator_events"] = [dict(row) for row in conn.execute(
                "SELECT * FROM operator_events WHERE job_id=? ORDER BY id", (job_id,))]
        return job

    def mark_read(self, job_id):
        identifier(job_id, "job ID")
        with self._connection(write=True) as conn:
            conn.execute("UPDATE jobs SET read_at=? WHERE id=?", (self._time(), job_id))

    def _operator_terminal(self, conn, row, *, cancelled, evidence, verified_stop=False):
        now = self._time()
        outcome = 'cancelled' if cancelled else ('failed' if verified_stop else 'reconciled')
        result = {"ok": False, "cancelled": cancelled,
                  "speech": ("Task cancelled." if cancelled else
                             "The local task stopped before completion." if verified_stop else
                             "Task reconciled by the operator.")}
        payload = canonical_json(result, MAX_RESULT_BYTES)
        fingerprint = digest(payload)
        conn.execute("""UPDATE jobs SET state='failed', cancelled=?, result_json=?, result_digest=?,
            fence=fence+1, lease_expires_at=NULL, updated_at=?, progress_json=NULL,
            attention_reason=CASE WHEN ? THEN NULL ELSE attention_reason END WHERE id=?""",
                     (int(cancelled), payload, fingerprint, now, int(verified_stop), row["id"]))
        conn.execute("UPDATE attempts SET finished_at=?,outcome=? WHERE id=?",
                     (now, outcome, row["attempt_id"]))
        # Operator actions are card-only. A verified worker failure uses normal
        # late delivery, unless cancellation was explicitly requested.
        conn.execute("""INSERT INTO outbox(id,job_id,result_digest,created_at,state) VALUES(?,?,?,?,?)
            ON CONFLICT(job_id) DO UPDATE SET state='suppressed', fence=fence+1, lease_expires_at=NULL""",
                     (uuid.uuid4().hex, row["id"], fingerprint, now,
                      'pending' if verified_stop and not cancelled else 'suppressed'))
        self._event(conn, row["id"], 'verified_local_stop' if verified_stop else outcome, evidence, now)

    def request_cancel(self, job_id, revision, *, supported_adapters):
        with self._connection(write=True) as conn:
            row = self._operator_job(conn, job_id, revision)
            if row["state"] == "queued":
                self._operator_terminal(conn, row, cancelled=True, evidence="Never dispatched")
            elif row["state"] in {"starting", "running"}:
                if row["adapter"] not in supported_adapters:
                    raise TaskError("This adapter cannot acknowledge cancellation")
                conn.execute("UPDATE jobs SET cancel_requested=1,updated_at=? WHERE id=?",
                             (self._time(), job_id))
                self._event(conn, job_id, "cancel_requested", "Operator requested a stop", self._time())
            else:
                raise Conflict("Execution has already settled or needs reconciliation")
        return self.get(job_id)

    def acknowledge_cancel(self, claim, evidence):
        with self._connection(write=True) as conn:
            row = self._active(conn, claim)
            if not row["cancel_requested"]:
                raise Conflict("No cancellation was requested")
            self._operator_terminal(conn, row, cancelled=True, evidence=evidence)

    def reconcile_job(self, job_id, revision, *, disposition, evidence, stopped):
        if disposition not in {"failed", "cancelled"} or stopped is not True:
            raise TaskError("Confirm execution has stopped and choose failed or cancelled")
        if not isinstance(evidence, str) or not 20 <= len(evidence.strip()) <= 4000:
            raise TaskError("Record 20–4000 characters of termination/status evidence")
        with self._connection(write=True) as conn:
            row = self._operator_job(conn, job_id, revision)
            if row["state"] != "needs_attention":
                raise Conflict("Only uncertain jobs require reconciliation")
            self._operator_terminal(conn, row, cancelled=disposition == "cancelled", evidence=evidence.strip())
        return self.get(job_id)

    def control_delivery(self, job_id, revision, action):
        if action not in {"retry_delivery", "suppress_delivery"}:
            raise TaskError("Invalid delivery action")
        with self._connection(write=True) as conn:
            row = self._operator_job(conn, job_id, revision)
            delivery = conn.execute("SELECT * FROM outbox WHERE job_id=?", (job_id,)).fetchone()
            if not delivery or delivery["state"] == "delivered":
                raise Conflict("There is no pending follow-up to change")
            if action == "retry_delivery":
                if row["archived_at"] is not None:
                    raise TaskError("The result payload has expired; delivery cannot be retried")
                if not self._generation_allowed(conn, row["conversation_id"], row["generation"]):
                    raise Conflict("The destination was disposed")
                if delivery["lease_expires_at"] and delivery["lease_expires_at"] > self._time():
                    raise Conflict("A follow-up is still being generated")
                state = "ready" if delivery["output_json"] else "pending"
            else:
                state = "suppressed"
            conn.execute("""UPDATE outbox SET state=?,fence=fence+1,lease_expires_at=NULL,
                next_attempt_at=0,error=NULL WHERE job_id=?""", (state, job_id))
            conn.execute("UPDATE jobs SET updated_at=? WHERE id=?", (self._time(), job_id))
            self._event(conn, job_id, action, "Explicit operator action", self._time())
        return self.get(job_id)

    def archive_results(self, limit=100, *, dry_run=False):
        """Bounded cleanup retains invocation identities, audit evidence, and artifacts."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise TaskError('Invalid archival batch')
        if not self.path.exists():
            return 0
        with self._connection(write=not dry_run) as conn:
            now = self._time()
            cutoff = now - self._settings(conn)['result_retention_days'] * 86400
            rows = conn.execute("""SELECT j.id FROM jobs j JOIN outbox o ON o.job_id=j.id
                WHERE j.state IN ('succeeded','failed') AND j.archived_at IS NULL AND j.updated_at<?
                AND o.state IN ('delivered','suppressed') LIMIT ?""", (cutoff, limit)).fetchall()
            if dry_run:
                return len(rows)
            for row in rows:
                conn.execute('UPDATE jobs SET result_json=NULL,progress_json=NULL,archived_at=? WHERE id=?', (now,row['id']))
                conn.execute('UPDATE outbox SET output_json=NULL,error=NULL WHERE job_id=?', (row['id'],))
            # Include historical orphan rows, but preserve authorization while
            # any referencing job can still execute or deliver its result.
            conn.execute("""DELETE FROM authorizations WHERE id IN (
                SELECT a.id FROM authorizations a WHERE a.created_at<? AND NOT EXISTS (
                    SELECT 1 FROM jobs j WHERE
                    json_extract(j.admission_json,'$.authorization_id')=a.id
                    AND j.archived_at IS NULL) LIMIT ?)""", (cutoff, limit))
            return len(rows)
