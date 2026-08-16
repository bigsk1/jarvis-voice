#!/usr/bin/env python3
"""SQLite metadata and fail-closed guards for persisted embedding spaces."""

from __future__ import annotations

import sqlite3
from typing import Any

from embeddings import EmbeddingRole, get_embedding_fingerprint

MEMORY_KNOWLEDGE_NAMESPACE = "memory.knowledge_base.embedding"
MEMORY_TOOLS_NAMESPACE = "memory.tool_definitions.embedding"
INTELLIGENCE_QUERY_NAMESPACE = "intelligence.experiences.query_embedding"
INTELLIGENCE_CONTEXT_NAMESPACE = "intelligence.experiences.context_embedding"
INTELLIGENCE_OUTCOME_NAMESPACE = "intelligence.experiences.outcome_embedding"
INTELLIGENCE_INSIGHT_NAMESPACE = "intelligence.insights.insight_embedding"
INTELLIGENCE_PATTERN_NAMESPACE = "intelligence.insights.pattern_embedding"

NAMESPACE_ROLES: dict[str, EmbeddingRole] = {
    MEMORY_KNOWLEDGE_NAMESPACE: "document",
    MEMORY_TOOLS_NAMESPACE: "document",
    INTELLIGENCE_QUERY_NAMESPACE: "document",
    INTELLIGENCE_CONTEXT_NAMESPACE: "document",
    INTELLIGENCE_OUTCOME_NAMESPACE: "document",
    INTELLIGENCE_INSIGHT_NAMESPACE: "similarity",
    INTELLIGENCE_PATTERN_NAMESPACE: "document",
}

NAMESPACE_INPUT_FORMATS = {
    MEMORY_KNOWLEDGE_NAMESPACE: "memory-title-key-text-value-v1",
    MEMORY_TOOLS_NAMESPACE: "tool-title-name-text-description-v1",
    INTELLIGENCE_QUERY_NAMESPACE: "intelligence-query-v1",
    INTELLIGENCE_CONTEXT_NAMESPACE: "intelligence-context-v1",
    INTELLIGENCE_OUTCOME_NAMESPACE: "intelligence-outcome-v1",
    INTELLIGENCE_INSIGHT_NAMESPACE: "intelligence-insight-v1",
    INTELLIGENCE_PATTERN_NAMESPACE: "intelligence-pattern-v1",
}

FINGERPRINT_FIELDS = (
    "provider",
    "model_family",
    "model",
    "model_digest",
    "dimensions",
    "prompt_profile",
    "prompt_role",
    "input_format",
)


class EmbeddingCompatibilityError(RuntimeError):
    """Raised when persisted vectors do not match the configured contract."""


def ensure_embedding_metadata_table(conn: sqlite3.Connection) -> None:
    """Create the current metadata table without accepting legacy vectors."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS embedding_metadata (
            namespace TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            model_family TEXT NOT NULL,
            model TEXT NOT NULL,
            model_digest TEXT NOT NULL,
            dimensions INTEGER NOT NULL,
            prompt_profile TEXT NOT NULL,
            prompt_role TEXT NOT NULL,
            input_format TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('complete', 'rebuilding')),
            last_row_id INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def metadata_table_exists(conn: sqlite3.Connection) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='embedding_metadata'"
    ).fetchone() is not None


def read_embedding_metadata(conn: sqlite3.Connection, namespace: str) -> dict[str, Any] | None:
    """Read one namespace fingerprint without mutating the database."""
    if not metadata_table_exists(conn):
        return None
    previous_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM embedding_metadata WHERE namespace = ?",
            (namespace,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.row_factory = previous_factory


def _fingerprint_matches(stored: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(stored.get(field) == expected.get(field) for field in FINGERPRINT_FIELDS)


def expected_namespace_fingerprint(namespace: str) -> dict[str, Any]:
    fingerprint = get_embedding_fingerprint(NAMESPACE_ROLES[namespace])
    fingerprint["input_format"] = NAMESPACE_INPUT_FORMATS[namespace]
    return fingerprint


def embedding_namespace_status(
    conn: sqlite3.Connection,
    namespace: str,
    *,
    vector_count: int,
) -> dict[str, Any]:
    """Assess one stored namespace against the current configured fingerprint."""
    expected = expected_namespace_fingerprint(namespace)
    stored = read_embedding_metadata(conn, namespace)

    if stored is None:
        if vector_count:
            reason = (
                "legacy or untracked vectors are present; delete the database or run "
                "./bin/rebuild-embeddings"
            )
            status = "incompatible"
        else:
            reason = "namespace has no vectors and will initialize on first successful write"
            status = "empty"
        return {
            "ok": vector_count == 0,
            "status": status,
            "reason": reason,
            "namespace": namespace,
            "vector_count": vector_count,
            "stored": None,
            "expected": expected,
        }

    if stored.get("state") != "complete":
        return {
            "ok": False,
            "status": "rebuilding",
            "reason": "embedding rebuild is incomplete; resume ./bin/rebuild-embeddings",
            "namespace": namespace,
            "vector_count": vector_count,
            "stored": stored,
            "expected": expected,
        }

    if not _fingerprint_matches(stored, expected):
        mismatches = [
            field for field in FINGERPRINT_FIELDS
            if stored.get(field) != expected.get(field)
        ]
        return {
            "ok": False,
            "status": "incompatible",
            "reason": "fingerprint mismatch: " + ", ".join(mismatches),
            "namespace": namespace,
            "vector_count": vector_count,
            "stored": stored,
            "expected": expected,
        }

    return {
        "ok": True,
        "status": "complete",
        "reason": None,
        "namespace": namespace,
        "vector_count": vector_count,
        "stored": stored,
        "expected": expected,
    }


def require_embedding_namespace(
    conn: sqlite3.Connection,
    namespace: str,
    *,
    vector_count: int,
) -> dict[str, Any]:
    """Raise unless stored vectors are empty or exactly compatible."""
    status = embedding_namespace_status(conn, namespace, vector_count=vector_count)
    if not status["ok"]:
        raise EmbeddingCompatibilityError(
            f"{namespace}: {status['reason']}. Semantic access is disabled."
        )
    return status["expected"]


def _write_metadata(
    conn: sqlite3.Connection,
    namespace: str,
    fingerprint: dict[str, Any],
    *,
    state: str,
    last_row_id: int,
) -> None:
    ensure_embedding_metadata_table(conn)
    conn.execute(
        """
        INSERT INTO embedding_metadata (
            namespace, provider, model_family, model, model_digest, dimensions,
            prompt_profile, prompt_role, input_format, state, last_row_id, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(namespace) DO UPDATE SET
            provider=excluded.provider,
            model_family=excluded.model_family,
            model=excluded.model,
            model_digest=excluded.model_digest,
            dimensions=excluded.dimensions,
            prompt_profile=excluded.prompt_profile,
            prompt_role=excluded.prompt_role,
            input_format=excluded.input_format,
            state=excluded.state,
            last_row_id=excluded.last_row_id,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            namespace,
            fingerprint["provider"],
            fingerprint["model_family"],
            fingerprint["model"],
            fingerprint["model_digest"],
            fingerprint["dimensions"],
            fingerprint["prompt_profile"],
            fingerprint["prompt_role"],
            fingerprint["input_format"],
            state,
            int(last_row_id),
        ),
    )


def record_embedding_namespace_complete(conn: sqlite3.Connection, namespace: str) -> None:
    """Record a complete current fingerprint in the caller's transaction."""
    _write_metadata(
        conn,
        namespace,
        expected_namespace_fingerprint(namespace),
        state="complete",
        last_row_id=0,
    )


def start_embedding_namespace_rebuild(
    conn: sqlite3.Connection,
    namespace: str,
    *,
    force: bool = False,
) -> int | None:
    """Start or resume a rebuild and return its last completed row ID.

    ``None`` means the namespace is already complete for the current contract.
    """
    expected = expected_namespace_fingerprint(namespace)
    stored = read_embedding_metadata(conn, namespace)
    if stored and stored.get("state") == "complete" and _fingerprint_matches(stored, expected):
        if not force:
            return None
    if stored and stored.get("state") == "rebuilding" and _fingerprint_matches(stored, expected):
        return int(stored.get("last_row_id") or 0)
    _write_metadata(conn, namespace, expected, state="rebuilding", last_row_id=0)
    return 0


def update_embedding_rebuild_progress(
    conn: sqlite3.Connection,
    namespace: str,
    last_row_id: int,
) -> None:
    """Advance rebuild progress in the same transaction as vector updates."""
    fingerprint = expected_namespace_fingerprint(namespace)
    _write_metadata(
        conn,
        namespace,
        fingerprint,
        state="rebuilding",
        last_row_id=last_row_id,
    )


def complete_embedding_namespace_rebuild(conn: sqlite3.Connection, namespace: str) -> None:
    """Atomically mark a fully rebuilt namespace usable."""
    record_embedding_namespace_complete(conn, namespace)
