"""Ordered migrations; execute statements individually inside BEGIN IMMEDIATE."""

from lib.webhook_integrations.schema import MIGRATION as CALLBACK_MIGRATION

MIGRATIONS = (
    (
        """CREATE TABLE settings (
            id INTEGER PRIMARY KEY CHECK(id=1),
            background_enabled INTEGER NOT NULL DEFAULT 0 CHECK(background_enabled IN (0,1)),
            webhooks_enabled INTEGER NOT NULL DEFAULT 0 CHECK(webhooks_enabled IN (0,1)),
            max_running INTEGER NOT NULL DEFAULT 2 CHECK(max_running BETWEEN 1 AND 32),
            max_outstanding INTEGER NOT NULL DEFAULT 5 CHECK(max_outstanding BETWEEN 1 AND 100),
            max_queued INTEGER NOT NULL DEFAULT 100 CHECK(max_queued BETWEEN 1 AND 10000)
        )""",
        "INSERT INTO settings(id) VALUES(1)",
        """CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            invocation_key TEXT NOT NULL UNIQUE,
            admission_json TEXT NOT NULL,
            admission_digest TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            generation INTEGER NOT NULL,
            mode TEXT NOT NULL CHECK(mode IN ('cloud','local')),
            adapter TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN
                ('queued','starting','running','succeeded','failed','needs_attention')),
            dispatch_state TEXT NOT NULL CHECK(dispatch_state IN ('held','ready')),
            receipt_json TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            deadline REAL NOT NULL,
            fence INTEGER NOT NULL DEFAULT 0,
            owner TEXT,
            attempt_id TEXT,
            lease_expires_at REAL,
            heartbeat_at REAL,
            progress_json TEXT,
            result_json TEXT,
            result_digest TEXT,
            attention_reason TEXT
        )""",
        "CREATE INDEX jobs_dispatch ON jobs(state, dispatch_state, created_at, id)",
        "CREATE INDEX jobs_conversation ON jobs(conversation_id, generation, state)",
        """CREATE TABLE attempts (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES jobs(id),
            owner TEXT NOT NULL,
            fence INTEGER NOT NULL,
            started_at REAL NOT NULL,
            finished_at REAL,
            outcome TEXT,
            UNIQUE(job_id, fence)
        )""",
        """CREATE TABLE outbox (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id),
            result_digest TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending' CHECK(state='pending'),
            created_at REAL NOT NULL
        )""",
        """CREATE TABLE workers (
            owner TEXT PRIMARY KEY,
            adapters_json TEXT NOT NULL,
            heartbeat_at REAL NOT NULL,
            lease_expires_at REAL NOT NULL,
            draining INTEGER NOT NULL CHECK(draining IN (0,1))
        )""",
    ),
    (
        "ALTER TABLE jobs ADD COLUMN revision INTEGER NOT NULL DEFAULT 1",
        """CREATE TRIGGER jobs_revision AFTER UPDATE ON jobs
            WHEN NEW.revision=OLD.revision BEGIN
                UPDATE jobs SET revision=OLD.revision+1 WHERE id=NEW.id;
            END""",
        """CREATE TABLE conversation_fences (
            conversation_id TEXT PRIMARY KEY, generation INTEGER NOT NULL,
            action TEXT NOT NULL CHECK(action IN ('clear','delete')),
            created_at REAL NOT NULL
        )""",
        """CREATE TABLE authorizations (
            id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at REAL NOT NULL
        )""",
        "ALTER TABLE outbox RENAME TO outbox_v1",
        """CREATE TABLE outbox (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id),
            result_digest TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending'
                CHECK(state IN ('pending','generating','ready','delivered','suppressed')),
            created_at REAL NOT NULL, owner TEXT, fence INTEGER NOT NULL DEFAULT 0,
            lease_expires_at REAL, output_json TEXT, error TEXT,
            next_attempt_at REAL NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0
        )""",
        """INSERT INTO outbox(id,job_id,result_digest,state,created_at)
            SELECT id,job_id,result_digest,state,created_at FROM outbox_v1""",
        "DROP TABLE outbox_v1",
        """CREATE TRIGGER outbox_job_revision AFTER UPDATE ON outbox
            WHEN NEW.state != OLD.state OR COALESCE(NEW.error,'') != COALESCE(OLD.error,'') BEGIN
                UPDATE jobs SET revision=revision+1 WHERE id=NEW.job_id;
            END""",
        "CREATE INDEX jobs_updated ON jobs(updated_at, id)",
    ),
    (
        "ALTER TABLE settings ADD COLUMN max_per_adapter INTEGER NOT NULL DEFAULT 2 CHECK(max_per_adapter BETWEEN 1 AND 32)",
        "ALTER TABLE jobs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0,1))",
        "ALTER TABLE jobs ADD COLUMN cancelled INTEGER NOT NULL DEFAULT 0 CHECK(cancelled IN (0,1))",
        "ALTER TABLE jobs ADD COLUMN read_at REAL",
        """CREATE TABLE operator_events (
            id INTEGER PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
            action TEXT NOT NULL, evidence TEXT NOT NULL, created_at REAL NOT NULL
        )""",
    ),
    (
        "ALTER TABLE settings ADD COLUMN result_retention_days INTEGER NOT NULL DEFAULT 30 CHECK(result_retention_days BETWEEN 1 AND 3650)",
        "ALTER TABLE jobs ADD COLUMN expired INTEGER NOT NULL DEFAULT 0 CHECK(expired IN (0,1))",
        "ALTER TABLE jobs ADD COLUMN archived_at REAL",
    ),
    (
        "ALTER TABLE settings ADD COLUMN background_tools TEXT NOT NULL DEFAULT '[]'",
    ),
    (
        # The conversation owns user text. Existing jobs retain their policy
        # and provider metadata, never another copy of the original message.
        "UPDATE authorizations SET payload=json_remove(payload, '$.query')",
    ),
    (
        # Lease renewal is liveness bookkeeping, not a new card or OCC token.
        # Keep read_at semantic so unread badges still propagate to clients.
        "DROP TRIGGER jobs_revision",
        """CREATE TRIGGER jobs_revision AFTER UPDATE ON jobs
            WHEN NEW.revision=OLD.revision AND (
                NEW.state IS NOT OLD.state OR NEW.dispatch_state IS NOT OLD.dispatch_state OR
                NEW.receipt_json IS NOT OLD.receipt_json OR NEW.fence IS NOT OLD.fence OR
                NEW.attempt_id IS NOT OLD.attempt_id OR NEW.progress_json IS NOT OLD.progress_json OR
                NEW.result_json IS NOT OLD.result_json OR NEW.attention_reason IS NOT OLD.attention_reason OR
                NEW.cancel_requested IS NOT OLD.cancel_requested OR NEW.cancelled IS NOT OLD.cancelled OR
                NEW.read_at IS NOT OLD.read_at OR NEW.expired IS NOT OLD.expired OR
                NEW.archived_at IS NOT OLD.archived_at
            ) BEGIN
                UPDATE jobs SET revision=OLD.revision+1 WHERE id=NEW.id;
            END""",
    ),
    CALLBACK_MIGRATION,
)
