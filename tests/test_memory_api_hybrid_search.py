"""FastAPI contract coverage for hybrid memory search."""

import asyncio
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from api.models.memory import MemoryCreate, SemanticSearchRequest
from api.routes import memory as memory_routes


class _HybridMemoryDB:
    def __init__(self):
        self.calls: list[dict] = []
        self.last_semantic_search_meta = {
            "retrieval_mode": "hybrid",
            "semantic_disabled_reason": None,
            "similarity_threshold": 0.31,
            "dense_candidate_count": 3,
            "keyword_candidate_count": 2,
            "keyword_precise_candidate_count": 1,
            "keyword_admitted_count": 1,
            "fused_candidate_count": 3,
        }

    def semantic_search(self, query, limit, similarity_threshold):
        self.calls.append(
            {
                "query": query,
                "limit": limit,
                "similarity_threshold": similarity_threshold,
            }
        )
        return [
            {
                "id": 42,
                "category": "fact",
                "key": "jarvis_api",
                "value": "Jarvis API runs on port 8880",
                "importance": 7,
                "similarity": 0.52,
                "retrieval_score": 0.81,
                "hybrid_score": 0.81,
                "rrf_score": 0.0325,
                "retrieval_channels": ["dense", "keyword"],
                "keyword_match_mode": "dense_support",
            }
        ]


def test_get_hybrid_search_uses_mode_threshold_and_exposes_diagnostics():
    db = _HybridMemoryDB()

    with patch.object(memory_routes, "get_db", return_value=db):
        response = asyncio.run(
            memory_routes.search_memories_semantic(
                q="where does the Jarvis API run",
                limit=5,
                threshold=None,
            )
        )

    assert db.calls == [
        {
            "query": "where does the Jarvis API run",
            "limit": 5,
            "similarity_threshold": None,
        }
    ]
    payload = response.model_dump(exclude_none=True)
    assert payload["retrieval"] == {
        "retrieval_mode": "hybrid",
        "similarity_threshold": 0.31,
        "dense_candidate_count": 3,
        "keyword_candidate_count": 2,
        "keyword_precise_candidate_count": 1,
        "keyword_admitted_count": 1,
        "fused_candidate_count": 3,
    }
    memory = payload["memories"][0]
    assert {
        key: memory[key]
        for key in (
            "retrieval_score",
            "hybrid_score",
            "rrf_score",
            "retrieval_channels",
            "keyword_match_mode",
        )
    } == {
        "retrieval_score": 0.81,
        "hybrid_score": 0.81,
        "rrf_score": 0.0325,
        "retrieval_channels": ["dense", "keyword"],
        "keyword_match_mode": "dense_support",
    }


def test_post_hybrid_search_omits_threshold_by_default():
    db = _HybridMemoryDB()
    db.last_semantic_search_meta.update(
        {
            "retrieval_mode": "keyword_fallback",
            "semantic_disabled_reason": "embedding fingerprint mismatch",
        }
    )
    request = SemanticSearchRequest(query="where does the Jarvis API run")

    assert request.similarity_threshold is None
    with patch.object(memory_routes, "get_db", return_value=db):
        response = asyncio.run(memory_routes.search_memories_semantic_post(request))

    assert db.calls[0]["similarity_threshold"] is None
    assert response.retrieval.retrieval_mode == "keyword_fallback"
    assert (
        response.retrieval.semantic_disabled_reason
        == "embedding fingerprint mismatch"
    )


def test_create_memory_exposes_response_preference_lifecycle_fields():
    class FakeDb:
        kwargs = None

        def remember(self, **kwargs):
            self.kwargs = kwargs
            return 91

    db = FakeDb()
    request = MemoryCreate(
        category="preference",
        key="response_style",
        value="Talk like a pirate",
        preference_slot="response_style",
        preference_scope="temporary",
        ttl_minutes=60,
        generate_embedding=False,
    )

    with patch.object(memory_routes, "get_db", return_value=db):
        response = asyncio.run(memory_routes.create_memory(request))

    assert response.memory_id == 91
    assert db.kwargs["metadata"] == {
        "preference_slot": "response_style",
        "preference_scope": "temporary",
        "ttl_minutes": 60,
    }


def test_create_memory_reports_invalid_preference_lifecycle_as_bad_request():
    class FakeDb:
        def remember(self, **kwargs):
            raise ValueError("temporary preferences require expires_at or ttl_minutes")

    request = MemoryCreate(
        category="preference",
        key="response_style",
        value="Talk like a pirate",
        preference_slot="response_style",
        preference_scope="temporary",
    )

    with patch.object(memory_routes, "get_db", return_value=FakeDb()), pytest.raises(
        HTTPException,
    ) as exc_info:
        asyncio.run(memory_routes.create_memory(request))

    assert exc_info.value.status_code == 400
