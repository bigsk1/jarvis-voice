"""Durable Web delivery and generation fences. No Web imports or network work."""

import json
import uuid
from contextlib import contextmanager

from .models import MAX_RESULT_BYTES, AdmissionDenied, Conflict, LostLease, canonical_json


class DeliveryStore:
    """TaskStore mixin; all writes use its short SQLite transactions."""

    JOB_SELECT = """SELECT j.*, o.state AS delivery_state, o.error AS delivery_error
        FROM jobs j LEFT JOIN outbox o ON o.job_id=j.id"""

    def conversation_fence(self, conversation_id):
        if not self.path.exists():
            return None
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM conversation_fences WHERE conversation_id=?", (conversation_id,)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def _generation_allowed(conn, conversation_id, generation):
        fence = conn.execute(
            "SELECT * FROM conversation_fences WHERE conversation_id=?", (conversation_id,)
        ).fetchone()
        return not fence or (fence["action"] != "delete" and generation >= fence["generation"])

    def outstanding(self, conversation_id):
        if not self.path.exists():
            return False
        with self._connection() as conn:
            return self._outstanding(conn, conversation_id)

    @staticmethod
    def _outstanding(conn, conversation_id):
        return bool(
            conn.execute(
                """SELECT 1 FROM jobs j WHERE conversation_id=? AND
            NOT EXISTS (SELECT 1 FROM conversation_fences f WHERE f.conversation_id=j.conversation_id
                AND (f.action='delete' OR f.generation>j.generation)) AND
            (state NOT IN ('succeeded','failed') OR EXISTS (
                SELECT 1 FROM outbox o WHERE o.job_id=j.id
                AND o.state NOT IN ('delivered','suppressed'))) LIMIT 1""",
                (conversation_id,),
            ).fetchone()
        )

    def fence_conversation(self, conversation_id, generation, action, *, dispose=False):
        if action not in {"clear", "delete"}:
            raise ValueError("Invalid conversation mutation")
        if not self.path.exists():
            # A normal clone need not create task storage just to delete a chat.
            return generation + 1
        with self._connection(write=True) as conn:
            if self._outstanding(conn, conversation_id) and not dispose:
                raise AdmissionDenied(
                    "Background jobs or deliveries need explicit disposition first"
                )
            current = conn.execute(
                "SELECT * FROM conversation_fences WHERE conversation_id=?", (conversation_id,)
            ).fetchone()
            if current and (current["action"] == "delete" or current["generation"] > generation):
                raise Conflict("Conversation generation has changed")
            next_generation = generation + 1
            conn.execute(
                """INSERT INTO conversation_fences VALUES(?,?,?,?)
                ON CONFLICT(conversation_id) DO UPDATE SET generation=excluded.generation,
                    action=excluded.action, created_at=excluded.created_at""",
                (conversation_id, next_generation, action, self._time()),
            )
            conn.execute(
                """UPDATE jobs SET state='needs_attention', fence=fence+1,
                attention_reason='Conversation disposed; execution outcome is not cancellation proof',
                updated_at=? WHERE conversation_id=? AND generation<=?
                AND state NOT IN ('succeeded','failed','needs_attention')""",
                (self._time(), conversation_id, generation),
            )
            conn.execute(
                """UPDATE outbox SET state='suppressed', fence=fence+1,
                lease_expires_at=NULL WHERE job_id IN (
                    SELECT id FROM jobs WHERE conversation_id=? AND generation<=?)""",
                (conversation_id, generation),
            )
            conn.execute(
                """UPDATE attempts SET finished_at=?, outcome='needs_attention'
                WHERE finished_at IS NULL AND job_id IN (
                    SELECT id FROM jobs WHERE conversation_id=? AND generation<=?)""",
                (self._time(), conversation_id, generation),
            )
            conn.execute("""DELETE FROM authorizations
                WHERE json_extract(payload,'$.conversation_id')=?
                AND json_extract(payload,'$.generation')<=?""", (conversation_id, generation))
            return next_generation

    def save_authorization(self, payload):
        encoded = canonical_json({key: value for key, value in payload.items() if key != 'query'}, 65536)
        authorization_id = uuid.uuid4().hex
        with self._connection(write=True) as conn:
            if not self._generation_allowed(
                conn, payload["conversation_id"], payload["generation"]
            ):
                raise AdmissionDenied("Conversation was disposed")
            conn.execute(
                "INSERT INTO authorizations VALUES(?,?,?)",
                (authorization_id, encoded, self._time()),
            )
        return authorization_id

    def authorization(self, authorization_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT payload FROM authorizations WHERE id=?", (authorization_id,)
            ).fetchone()
            return json.loads(row[0]) if row else None

    def conversation_jobs(self, conversation_id=None, *, limit=100):
        if not self.path.exists():
            return []
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Invalid job batch")
        with self._connection() as conn:
            rows = conn.execute(
                self.JOB_SELECT
                + """ WHERE (? IS NULL OR j.conversation_id=?)
                ORDER BY j.created_at DESC, j.id DESC LIMIT ?""",
                (conversation_id, conversation_id, limit),
            )
            return [self._job(row) for row in rows]

    def context_jobs(self, conversation_id, generation, *, limit=8):
        """Conversation-owned evidence across modes, independent of admission settings."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid context batch")
        empty = {"jobs": [], "total": 0}
        if not self.path.exists():
            return empty
        with self._connection() as conn:
            if not self._generation_allowed(conn, conversation_id, generation):
                return empty
            where = " WHERE j.conversation_id=? AND j.generation=?"
            values = (conversation_id, generation)
            total = conn.execute("SELECT COUNT(*) FROM jobs j" + where, values).fetchone()[0]
            # Cancelled/expired are display states backed by terminal failed
            # rows. They share terminal recency ranking, never active priority.
            rows = conn.execute(
                self.JOB_SELECT + where + """ ORDER BY
                (j.state NOT IN ('succeeded','failed')) DESC,
                (o.state NOT IN ('delivered','suppressed')) DESC,
                j.updated_at DESC, j.id DESC LIMIT ?""",
                (*values, limit),
            )
            return {"jobs": [self._job(row) for row in rows], "total": total}

    def publication_jobs(self, cursor=None):
        """Always observe running attempts; page other jobs so old results cannot starve."""
        with self._connection() as conn:
            active = conn.execute(
                self.JOB_SELECT + " WHERE j.state IN ('starting','running')"
            ).fetchall()
            rows = conn.execute(
                self.JOB_SELECT
                + """ WHERE (j.updated_at,j.id) > (?,?)
                ORDER BY j.updated_at,j.id LIMIT 100""",
                cursor or (-1, ""),
            ).fetchall()
            next_cursor = (rows[-1]["updated_at"], rows[-1]["id"]) if rows else None
            return list(
                {row["id"]: self._job(row) for row in [*active, *rows]}.values()
            ), next_cursor

    def held_jobs(self, *, limit=100):
        if not self.path.exists():
            return []
        with self._connection() as conn:
            return [
                self._job(row)
                for row in conn.execute(
                    """SELECT * FROM jobs
                WHERE state='queued' AND dispatch_state='held' ORDER BY created_at,id LIMIT ?""",
                    (limit,),
                )
            ]

    def delivery(self, delivery_id):
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM outbox WHERE id=?", (delivery_id,)).fetchone()
            return dict(row) if row else None

    def claim_delivery(self, delivery_id, owner, *, lease_seconds=30):
        self._ttl(lease_seconds)
        with self._connection(write=True) as conn:
            now = self._time()
            row = conn.execute("SELECT * FROM outbox WHERE id=?", (delivery_id,)).fetchone()
            if (
                not row
                or row["state"] in {"delivered", "suppressed"}
                or row["next_attempt_at"] > now
            ):
                return None
            if row["lease_expires_at"] and row["lease_expires_at"] > now:
                return None
            job = conn.execute("SELECT * FROM jobs WHERE id=?", (row["job_id"],)).fetchone()
            if not self._generation_allowed(conn, job["conversation_id"], job["generation"]):
                conn.execute(
                    "UPDATE outbox SET state='suppressed', fence=fence+1 WHERE id=?", (delivery_id,)
                )
                return None
            conn.execute(
                """UPDATE outbox SET state=?, owner=?, fence=fence+1,
                lease_expires_at=?, attempts=attempts+1 WHERE id=?""",
                (
                    "ready" if row["output_json"] else "generating",
                    owner,
                    now + lease_seconds,
                    delivery_id,
                ),
            )
            return dict(conn.execute("SELECT * FROM outbox WHERE id=?", (delivery_id,)).fetchone())

    def _delivery_owned(self, conn, claim):
        row = conn.execute("SELECT * FROM outbox WHERE id=?", (claim["id"],)).fetchone()
        if (
            not row
            or row["owner"] != claim["owner"]
            or row["fence"] != claim["fence"]
            or row["state"] not in {"generating", "ready"}
            or row["lease_expires_at"] <= self._time()
        ):
            raise LostLease("Delivery ownership expired or was fenced")
        job = conn.execute("SELECT * FROM jobs WHERE id=?", (row["job_id"],)).fetchone()
        if not self._generation_allowed(conn, job["conversation_id"], job["generation"]):
            raise LostLease("Conversation generation was fenced")
        return row

    def renew_delivery(self, claim, *, lease_seconds=30):
        self._ttl(lease_seconds)
        with self._connection(write=True) as conn:
            self._delivery_owned(conn, claim)
            conn.execute(
                "UPDATE outbox SET lease_expires_at=? WHERE id=?",
                (self._time() + lease_seconds, claim["id"]),
            )

    def save_delivery_output(self, claim, output):
        encoded = canonical_json(output, MAX_RESULT_BYTES)
        with self._connection(write=True) as conn:
            row = self._delivery_owned(conn, claim)
            if row["output_json"] and row["output_json"] != encoded:
                raise Conflict("Delivery already has generated output")
            conn.execute(
                "UPDATE outbox SET output_json=?, state='ready', error=NULL WHERE id=?",
                (encoded, claim["id"]),
            )

    def discard_delivery_output(self, claim):
        """Invalidate generated prose without changing the saved tool result."""
        with self._connection(write=True) as conn:
            self._delivery_owned(conn, claim)
            conn.execute("UPDATE outbox SET output_json=NULL, state='generating' WHERE id=?", (claim['id'],))

    @contextmanager
    def delivery_commit(self, claim):
        """Caller holds conversation mutation lock; no model work in this transaction.

        Keep the fence valid across the atomic JSON replacement. If SQLite commit
        fails afterward, the saved continuation ID makes retry a projection check.
        """
        with self._connection(write=True) as conn:
            row = self._delivery_owned(conn, claim)
            if not row["output_json"]:
                raise Conflict("No durable continuation output")
            yield json.loads(row["output_json"])
            conn.execute(
                "UPDATE outbox SET state='delivered', lease_expires_at=NULL WHERE id=?",
                (claim["id"],),
            )

    def defer_delivery(self, claim, *, error="", delay=1):
        with self._connection(write=True) as conn:
            row = self._delivery_owned(conn, claim)
            conn.execute(
                """UPDATE outbox SET state=?, lease_expires_at=NULL,
                next_attempt_at=?, error=? WHERE id=?""",
                (
                    "ready" if row["output_json"] else "pending",
                    self._time() + delay,
                    error[:500],
                    claim["id"],
                ),
            )
