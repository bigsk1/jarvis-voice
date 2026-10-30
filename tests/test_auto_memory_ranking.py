"""Auto-injection admits exact or dense evidence, not source-only relevance."""

from __future__ import annotations

import json
import math
import sys
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "orchestrator"))

import orchestrator_v2  # noqa: E402
from config_loader import config_override_scope, config_scope  # noqa: E402
from orchestrator_v2 import Orchestrator  # noqa: E402

from lib.memory_db import MemoryDB  # noqa: E402

INTEL_SOURCES = ("intel/example-notes.md", "intel/jarvis-learned-lessons.md")


@pytest.fixture(params=("cloud", "local"))
def memory_case(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[MemoryDB, Orchestrator]]:
    settings = {
        "AUTO_MEMORY_INJECTION_ENABLED": "true",
        "AUTO_MEMORY_LIMIT": "2",
        "AUTO_MEMORY_SIMILARITY_THRESHOLD": "0.45",
        "AUTO_MEMORY_RECENCY_ENABLED": "true",
        "AUTO_MEMORY_ALWAYS_INCLUDE_LIMIT": "4",
        "AUTO_MEMORY_TYPE_FILTER_ENABLED": "true",
        "USER_PROFILE_CARD_ENABLED": "true",
    }
    with config_scope(str(request.param), overrides=settings):
        db = MemoryDB(str(tmp_path / f"{request.param}-memory.db"))
        monkeypatch.setattr(orchestrator_v2, "get_memory_db", lambda: db)
        # Provider generation and namespace verification are the only embedding
        # boundaries replaced; FTS, vector decoding, cosine and fusion stay real.
        monkeypatch.setattr("embeddings.get_embedding", lambda *_a, **_kw: [1.0, 0.0])
        monkeypatch.setattr("lib.memory_db.require_embedding_namespace", lambda *_a, **_kw: None)
        orch = Orchestrator.__new__(Orchestrator)
        orch.timezone = timezone.utc
        orch.session_id = "test-session"
        orch.web_conversation_id = "test-web-session"
        try:
            yield db, orch
        finally:
            db.close()


def add_fact(
    db: MemoryDB,
    key: str,
    value: str,
    *,
    source: str = "remember",
    similarity: float | None = None,
    importance: int = 5,
    days_old: int = 0,
) -> int:
    memory_id = db.remember(
        "fact", key, value, importance=importance, source=source,
        generate_embedding=False, metadata={"memory_type": "fact"},
    )
    vector = (
        json.dumps([similarity, math.sqrt(1.0 - similarity**2)]).encode()
        if similarity is not None else None
    )
    updated = datetime.now(timezone.utc) - timedelta(days=days_old)
    db.conn.execute(
        "UPDATE knowledge_base SET embedding = ?, updated_at = ? WHERE id = ?",
        (vector, updated.replace(tzinfo=None).isoformat(sep=" "), memory_id),
    )
    db.conn.commit()
    return memory_id


@pytest.mark.parametrize("source", INTEL_SOURCES)
def test_broad_intel_keyword_hit_does_not_enter_prompt_review(
    memory_case: tuple[MemoryDB, Orchestrator], source: str,
) -> None:
    db, orch = memory_case
    query = "Please review the system prompt instructions for clarity"
    wrong_id = add_fact(
        db, "image_setup_note", "This system produces square pictures.",
        source=source, similarity=0.10, importance=10,
    )
    add_fact(
        db, "instruction_priority", "Earlier directives defer to the current request.",
        similarity=0.72,
    )
    assert wrong_id in {row["id"] for row in db.fts_search(query)}
    assert db.fts_search_precise(query) == []

    bundle = orch._get_relevant_memories_bundle(query)

    assert "instruction_priority" in bundle["context"]
    assert "image_setup_note" not in bundle["context"]


@pytest.mark.parametrize("source", INTEL_SOURCES)
def test_source_and_importance_do_not_outrank_adjusted_cosine(
    memory_case: tuple[MemoryDB, Orchestrator], source: str,
) -> None:
    db, orch = memory_case
    query = "Which memory captures earlier events?"
    add_fact(
        db, "history_archive", "The assistant retains its interaction history.",
        similarity=0.80, importance=1, days_old=180,
    )
    add_fact(
        db, "context_notes", "General notes about preserving context.",
        source=source, similarity=0.66, importance=10,
    )
    assert db.fts_search_precise(query) == []

    bundle = orch._get_relevant_memories_bundle(query)

    context = bundle["context"]
    assert context.index("history_archive") < context.index("context_notes")
    assert "embed=0.80 rank=0.68" in context
    assert "embed=0.66 rank=0.66" in context


@pytest.mark.parametrize("source", INTEL_SOURCES)
def test_source_cannot_rescue_below_threshold_semantic_match(
    memory_case: tuple[MemoryDB, Orchestrator], source: str,
) -> None:
    db, orch = memory_case
    add_fact(
        db, "near_threshold_note", "General notes about preserving context.",
        source=source, similarity=0.42, importance=10,
    )

    bundle = orch._get_relevant_memories_bundle("Which memory captures earlier events?")

    assert "near_threshold_note" not in bundle["context"]
    assert bundle["meta"]["injected"] is False


@pytest.mark.parametrize("source", INTEL_SOURCES)
def test_broad_keyword_fallback_without_embeddings_is_not_auto_injected(
    memory_case: tuple[MemoryDB, Orchestrator], source: str,
) -> None:
    db, orch = memory_case
    query = "Please review the system prompt instructions for clarity"
    wrong_id = add_fact(
        db, "image_setup_note", "This system produces square pictures.", source=source,
    )
    assert wrong_id in {row["id"] for row in db.fts_search(query)}
    assert db.fts_search_precise(query) == []

    bundle = orch._get_relevant_memories_bundle(query)

    assert db.last_semantic_search_meta["retrieval_mode"] == "keyword_fallback"
    assert bundle["meta"]["injected"] is False
    assert "image_setup_note" not in bundle["context"]


@pytest.mark.parametrize("source", INTEL_SOURCES)
def test_exact_intel_fact_is_retained_without_embeddings(
    memory_case: tuple[MemoryDB, Orchestrator], source: str,
) -> None:
    db, orch = memory_case
    memory_id = add_fact(
        db, "atlas_relay_endpoint", "Atlas relay endpoint is https://example.invalid/relay.",
        source=source,
    )
    query = "Atlas relay endpoint"
    assert memory_id in {row["id"] for row in db.fts_search_precise(query)}

    bundle = orch._get_relevant_memories_bundle(query)

    assert bundle["meta"]["injected"] is True
    assert "atlas_relay_endpoint" in bundle["context"]
    assert f"memory_id: {memory_id}" in bundle["context"]
    assert "keyword_exact" in bundle["context"]
    candidate = next(
        item for item in bundle["meta"]["top_candidates"]
        if item["key"] == "atlas_relay_endpoint"
    )
    assert candidate["similarity"] is None


@pytest.mark.parametrize("source", INTEL_SOURCES)
def test_zero_threshold_does_not_admit_keyword_fallback_as_dense_evidence(
    memory_case: tuple[MemoryDB, Orchestrator], source: str,
) -> None:
    db, orch = memory_case
    query = "Please review the system prompt instructions for clarity"
    wrong_id = add_fact(
        db, "image_setup_note", "This system produces square pictures.", source=source,
    )
    assert wrong_id in {row["id"] for row in db.fts_search(query)}
    assert db.fts_search_precise(query) == []

    with config_override_scope({"AUTO_MEMORY_SIMILARITY_THRESHOLD": "0"}):
        bundle = orch._get_relevant_memories_bundle(query)

    assert db.last_semantic_search_meta["retrieval_mode"] == "keyword_fallback"
    assert bundle["meta"]["injected"] is False
    assert "image_setup_note" not in bundle["context"]
    candidate = next(
        item for item in bundle["meta"]["top_candidates"]
        if item["key"] == "image_setup_note"
    )
    assert candidate["similarity"] is None


def test_zero_cosine_is_real_dense_evidence_when_threshold_is_zero(
    memory_case: tuple[MemoryDB, Orchestrator],
) -> None:
    db, orch = memory_case
    add_fact(
        db, "orthogonal_dense_fact", "The assistant retains its interaction history.",
        similarity=0.0,
    )
    query = "Which memory captures earlier events?"
    assert db.fts_search_precise(query) == []

    with config_override_scope({"AUTO_MEMORY_SIMILARITY_THRESHOLD": "0"}):
        bundle = orch._get_relevant_memories_bundle(query)

    assert bundle["meta"]["injected"] is True
    assert "orthogonal_dense_fact" in bundle["context"]
    assert "semantic embed=0.00 rank=0.00" in bundle["context"]
    candidate = next(
        item for item in bundle["meta"]["top_candidates"]
        if item["key"] == "orthogonal_dense_fact"
    )
    assert candidate["similarity"] == 0.0
    assert candidate["similarity"] is not None


def test_profile_type_and_scoped_preference_gates_remain_in_force(
    memory_case: tuple[MemoryDB, Orchestrator],
) -> None:
    db, orch = memory_case
    db.remember(
        "preference", "preferred_language", "Use the language English",
        source="remember", generate_embedding=False,
    )
    db.remember(
        "preference", "preferred_language", "Use the language Spanish",
        source="remember", generate_embedding=False,
        metadata={
            "preference_scope": "session",
            "preference_session_id": "test-web-session",
        },
    )
    db.remember(
        "preference", "preferred_language", "Use the language German",
        source="remember", generate_embedding=False,
        metadata={
            "preference_scope": "session",
            "preference_session_id": "another-test-session",
        },
    )
    expired_id = db.remember(
        "preference", "preferred_language", "Use the language French",
        source="remember", generate_embedding=False,
        metadata={"preference_scope": "temporary", "ttl_minutes": 60},
    )
    expired_metadata = json.loads(db.conn.execute(
        "SELECT metadata FROM knowledge_base WHERE id = ?", (expired_id,),
    ).fetchone()["metadata"])
    expired_metadata["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(days=1)
    ).isoformat()
    db.conn.execute(
        "UPDATE knowledge_base SET metadata = ? WHERE id = ?",
        (json.dumps(expired_metadata), expired_id),
    )
    db.conn.commit()
    add_fact(
        db, "profile_language_baseline", "The profile language is Italian.",
        source="intel/user-profile.md", similarity=0.99,
    )
    db.remember(
        "stash_artifact", "cached_language_output", "Language output from a temporary artifact.",
        source="generate_image", generate_embedding=False,
        metadata={"memory_type": "artifact"},
    )
    add_fact(db, "language_reference", "Language codes follow an established standard.")

    bundle = orch._get_relevant_memories_bundle("language")

    context = bundle["context"]
    assert "Use the language Spanish" in context
    assert "active_pref slot=preferred_language scope=session" in context
    assert "language_reference" in context
    for excluded in (
        "Use the language English", "Use the language German", "Use the language French",
        "profile_language_baseline", "cached_language_output",
    ):
        assert excluded not in context
