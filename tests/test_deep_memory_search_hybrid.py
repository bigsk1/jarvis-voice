"""Hybrid MemoryDB result labeling for deep_memory_search."""

from unittest.mock import patch

from skills.deep_memory_search import memory_retrieval_label, search_memory_db


def test_labels_dense_and_keyword_result_as_hybrid():
    source, display = memory_retrieval_label({
        "retrieval_channels": ["dense", "keyword"],
        "similarity": 0.437,
    })

    assert source == "memory_hybrid"
    assert display == "Memory (hybrid, 44% semantic match)"


def test_labels_keyword_fallback_without_fake_zero_percent_similarity():
    source, display = memory_retrieval_label({
        "retrieval_channels": ["keyword"],
        "keyword_match_mode": "fallback",
        "retrieval_score": 0.55,
    })

    assert source == "memory_keyword"
    assert display == "Memory (keyword fallback; embeddings unavailable)"
    assert "0%" not in display


def test_semantic_mode_preserves_keyword_only_channel_from_memory_db():
    class FakeDb:
        last_semantic_search_meta = {
            "retrieval_mode": "keyword_only",
            "semantic_disabled_reason": None,
        }

        def semantic_search(self, query, limit):
            assert query == "Atlas phrase"
            assert limit == 3
            return [{
                "id": 7,
                "key": "atlas_phrase",
                "value": "silver harbor",
                "retrieval_channels": ["keyword"],
                "keyword_match_mode": "precise",
                "retrieval_score": 0.55,
            }]

        def close(self):
            pass

    with patch("skills.deep_memory_search.get_memory_db", return_value=FakeDb()):
        results, meta = search_memory_db("Atlas phrase", 3, "semantic")

    assert meta["retrieval_mode"] == "keyword_only"
    assert results[0]["_source"] == "memory_keyword"
    assert results[0]["_source_display"] == "Memory (exact keyword match)"


def test_comprehensive_mode_uses_memory_db_fused_ranking_without_retruncating():
    class FakeDb:
        last_semantic_search_meta = {
            "retrieval_mode": "hybrid",
            "semantic_disabled_reason": None,
        }

        def search_memory(self, query, limit):
            assert query == "phone call"
            assert limit == 3
            return [
                {"id": 1, "key": "keyword-1", "value": "one"},
                {"id": 2, "key": "keyword-2", "value": "two"},
                {"id": 3, "key": "keyword-3", "value": "three"},
            ]

        def semantic_search(self, query, limit):
            assert query == "phone call"
            assert limit == 3
            return [
                {
                    "id": 1,
                    "key": "keyword-1",
                    "value": "one",
                    "similarity": 0.8,
                    "retrieval_channels": ["dense", "keyword"],
                },
                {
                    "id": 4,
                    "key": "semantic-1",
                    "value": "four",
                    "similarity": 0.7,
                    "retrieval_channels": ["dense"],
                },
                {
                    "id": 5,
                    "key": "precise-1",
                    "value": "five",
                    "retrieval_channels": ["keyword"],
                    "keyword_match_mode": "precise",
                },
            ]

        def close(self):
            pass

    with patch("skills.deep_memory_search.get_memory_db", return_value=FakeDb()):
        results, meta = search_memory_db("phone call", 3, "comprehensive")

    assert meta["retrieval_mode"] == "hybrid"
    assert [result["id"] for result in results] == [1, 4, 5]
    assert [result["_source"] for result in results] == [
        "memory_hybrid",
        "memory_semantic",
        "memory_keyword",
    ]
