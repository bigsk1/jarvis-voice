"""FastAPI contract coverage for hybrid memory search."""

import asyncio
from unittest.mock import patch

from api.models.memory import SemanticSearchRequest
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
