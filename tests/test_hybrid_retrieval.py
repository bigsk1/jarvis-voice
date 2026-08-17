"""Regression coverage for deterministic hybrid ranking and adaptive cutoffs."""

from lib.hybrid_retrieval import (
    adaptive_rank_cutoff,
    fts5_query,
    query_segments,
    query_terms,
)


def test_query_terms_remove_filler_without_classifying_intent():
    terms = query_terms("Hey, can you get the current Bitcoin price and chart?")

    assert terms == ["current", "bitcoin", "price", "chart"]
    assert fts5_query(terms, operator="AND") == (
        '"current" AND "bitcoin" AND "price" AND "chart"'
    )


def test_query_segments_extract_compound_actions_without_tool_rules():
    segments = query_segments(
        "Look up NVIDIA stock price and the latest news about NVIDIA."
    )

    assert segments == [
        "Look up NVIDIA stock price",
        "the latest news about NVIDIA",
    ]


def test_query_segments_leave_short_requests_on_single_vector_path():
    assert query_segments("Bitcoin price and chart") == []


def test_adaptive_cutoff_keeps_a_dominant_single_result():
    ranked = [
        {"name": "forget", "hybrid_score": 1.0, "similarity": 0.52},
        {"name": "memory_deduper", "hybrid_score": 0.27, "similarity": 0.37},
        {"name": "remember", "hybrid_score": 0.26, "similarity": 0.36},
    ]

    selected, meta = adaptive_rank_cutoff(ranked, budget=3)

    assert [row["name"] for row in selected] == ["forget"]
    assert meta["reason"] == "dominant_top_result"


def test_adaptive_cutoff_preserves_clustered_multitool_pair():
    ranked = [
        {"name": "crypto_price", "hybrid_score": 0.91, "similarity": 0.526},
        {"name": "crypto_chart", "hybrid_score": 0.71, "similarity": 0.522},
        {"name": "stock_price", "hybrid_score": 0.68, "similarity": 0.455},
        {"name": "status_recap", "hybrid_score": 0.30, "similarity": 0.381},
    ]

    selected, meta = adaptive_rank_cutoff(ranked, budget=4)

    assert [row["name"] for row in selected] == ["crypto_price", "crypto_chart"]
    assert meta["reason"] == "dense_score_gap"


def test_adaptive_cutoff_uses_budget_when_scores_remain_ambiguous():
    ranked = [
        {"name": "one", "hybrid_score": 0.90, "similarity": 0.50},
        {"name": "two", "hybrid_score": 0.80, "similarity": 0.48},
        {"name": "three", "hybrid_score": 0.72, "similarity": 0.46},
    ]

    selected, meta = adaptive_rank_cutoff(ranked, budget=3)

    assert [row["name"] for row in selected] == ["one", "two", "three"]
    assert meta["reason"] == "budget"
