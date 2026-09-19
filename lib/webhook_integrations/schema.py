"""Task callback storage, migrated atomically with the task control database."""

MIGRATION = (
    "ALTER TABLE jobs ADD COLUMN callback_waiting INTEGER NOT NULL DEFAULT 0 CHECK(callback_waiting IN (0,1))",
    """CREATE TABLE task_integrations (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0,
        revoked INTEGER NOT NULL DEFAULT 0, adapter TEXT NOT NULL,
        events_json TEXT NOT NULL, callback_base TEXT NOT NULL, submit_url TEXT NOT NULL,
        revision INTEGER NOT NULL DEFAULT 1, validated_revision INTEGER,
        validated_at REAL, created_at REAL NOT NULL, rate_limit INTEGER NOT NULL DEFAULT 60
    )""",
    """CREATE TABLE task_credentials (
        id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES task_integrations(id),
        version INTEGER NOT NULL, scheme TEXT NOT NULL, verifier TEXT, encrypted TEXT,
        created_at REAL NOT NULL, expires_at REAL, revoked_at REAL, last_used_at REAL,
        probe INTEGER NOT NULL DEFAULT 0, probe_revision INTEGER, UNIQUE(source_id,version)
    )""",
    """CREATE TABLE task_callback_bindings (
        job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
        source_id TEXT NOT NULL REFERENCES task_integrations(id), attempt_id TEXT NOT NULL,
        fence INTEGER NOT NULL, capability_hash TEXT NOT NULL, created_at REAL NOT NULL,
        remote_id TEXT, last_progress_at REAL
    )""",
    """CREATE TABLE task_callback_inbox (
        id INTEGER PRIMARY KEY, source_id TEXT NOT NULL REFERENCES task_integrations(id),
        credential_id TEXT NOT NULL REFERENCES task_credentials(id), event_id TEXT NOT NULL,
        job_id TEXT, attempt_id TEXT, event_type TEXT NOT NULL, payload_json TEXT NOT NULL,
        payload_digest TEXT NOT NULL, verified_at REAL NOT NULL,
        state TEXT NOT NULL DEFAULT 'pending', reason TEXT, processed_at REAL,
        attempts INTEGER NOT NULL DEFAULT 0, UNIQUE(source_id,event_id)
    )""",
    "CREATE INDEX task_callback_drain ON task_callback_inbox(state,id)",
    """CREATE TABLE task_callback_limits (
        bucket TEXT PRIMARY KEY, window INTEGER NOT NULL, count INTEGER NOT NULL
    )""",
)
