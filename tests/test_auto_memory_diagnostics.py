"""Keep the operator diagnostic aligned with automatic memory admission rules."""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_auto_memory_similarity as diagnostics  # noqa: E402


def _row(key, similarity=0.7, source="user_conversation", **overrides):
    return {
        "key": key,
        "value": "A stored fact",
        "category": "technical",
        "source": source,
        "similarity": similarity,
        "metadata": {"memory_type": "fact"},
        **overrides,
    }


def _diagnose(*, semantic=(), precise=(), preferences=(), **options):
    db = Mock()
    db.db_path = "fake-memory.db"
    db.get_addressing_preferences.return_value = list(preferences)
    db.fts_search.return_value = [_row("irrelevant_tooling_intel", source="intel/guide.md")]
    db.fts_search_precise.return_value = list(precise)
    db.semantic_search.return_value = list(semantic)
    db.last_semantic_search_meta = {"retrieval_mode": "hybrid"}
    result = diagnostics.collect_auto_memory_diagnostics(
        db=db,
        query="Which tool handles this request?",
        **{
            "threshold": 0.45,
            "limit": 3,
            "recency_enabled": False,
            "addressing_limit": 4,
            **options,
        },
    )
    return db, result


@pytest.mark.parametrize("source", [
    "user_conversation", "intel/guide.md", "intel/jarvis-tool-knowledge.md",
])
def test_semantic_admission_has_no_source_promotion(source):
    db, result = _diagnose(semantic=[_row("below_threshold", 0.40, source)])

    assert result["injected"] == []
    assert result["semantic_candidates"][0]["adjusted_score"] == 0.40
    db.fts_search.assert_not_called()


def test_precise_keyword_hit_is_independent_of_semantic_threshold():
    exact = _row("exact_identifier", 0.0, "intel/guide.md")
    db, result = _diagnose(precise=[exact], threshold=0.99)

    assert [entry["key"] for entry in result["injected"]] == ["exact_identifier"]
    assert result["injected"][0]["bucket"] == "keyword"
    assert result["injected"][0]["base_similarity"] is None
    db.fts_search_precise.assert_called_once_with(
        "Which tool handles this request?", limit=8,
    )
    db.fts_search.assert_not_called()


def test_recency_weights_cosine_without_promoting_curated_intel(monkeypatch):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 30)

    monkeypatch.setattr(diagnostics, "datetime", FixedDatetime)
    _, result = _diagnose(
        semantic=[
            _row("old_curated", 0.55, "intel/jarvis-tool-knowledge.md",
                 updated_at="2026-01-01T00:00:00"),
            _row("recent_fact", 0.55, updated_at="2026-10-30T00:00:00"),
        ],
        limit=1,
        recency_enabled=True,
    )

    assert [entry["key"] for entry in result["injected"]] == ["recent_fact"]
    scores = {entry["key"]: entry["adjusted_score"] for entry in result["semantic_candidates"]}
    assert scores == {"recent_fact": 0.55, "old_curated": pytest.approx(0.55 * 0.85)}


def test_rejected_semantic_row_does_not_suppress_later_qualifying_same_key():
    _, result = _diagnose(semantic=[
        _row("same_key", 0.20), _row("same_key", 0.70),
    ])

    assert len(result["injected"]) == 1
    assert result["injected"][0]["key"] == "same_key"
    assert result["injected"][0]["base_similarity"] == 0.70


@pytest.mark.parametrize("similarity", [None, 0.0])
def test_zero_threshold_requires_actual_cosine_evidence(similarity):
    memory = _row("zero_threshold_fact", similarity)
    if similarity is None:
        memory.pop("similarity")

    _, result = _diagnose(semantic=[memory], threshold=0.0)

    candidate = result["semantic_candidates"][0]
    assert candidate["include"] is (similarity is not None)
    assert [entry["key"] for entry in result["injected"]] == (
        ["zero_threshold_fact"] if similarity is not None else []
    )
    if similarity is None:
        assert "passes final threshold" not in candidate["reason"]


def test_active_preferences_keep_separate_budget_and_retrieval_guards():
    active = _row(
        "response_style", category="preference", value="Use concise prose",
        preference_scope="session",
    )
    stale = _row(
        "preference_override:response_style:session:other", 0.99,
        category="preference", metadata={"preference_slot": "response_style"},
    )
    profile = _row("profile", 0.99, "intel/user-profile.md")
    artifact = _row("artifact", 0.99, metadata={"memory_type": "artifact"})
    db, result = _diagnose(
        preferences=[active], precise=[stale, profile, artifact],
        semantic=[stale, profile, artifact, _row("relevant_fact")],
        limit=1, session_id="current-session",
    )

    assert [entry["key"] for entry in result["injected"]] == [
        "response_style", "relevant_fact",
    ]
    db.get_addressing_preferences.assert_called_once_with(
        limit=4, session_id="current-session",
    )


@pytest.mark.parametrize("limit,type_filter,expected_limit", [
    (3, True, 15), (3, False, 6), (20, True, 50),
])
def test_candidate_budgets_remain_bounded(limit, type_filter, expected_limit):
    db, _ = _diagnose(limit=limit, type_filter_enabled=type_filter)

    db.semantic_search.assert_called_once_with(
        query="Which tool handles this request?", limit=expected_limit,
        similarity_threshold=0.30,
    )
