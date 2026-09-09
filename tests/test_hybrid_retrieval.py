"""Regression coverage for deterministic hybrid ranking and adaptive cutoffs."""

import pytest

from lib.hybrid_retrieval import (
    adaptive_rank_cutoff,
    fts5_query,
    query_segments,
    query_terms,
    segment_retrieval_query,
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


def test_trailing_youtube_url_does_not_dilute_the_summarize_view():
    url = "https://www.youtube.com/watch?v=4JofSJIrjwU"
    assert query_segments(f"Get this YouTube video and summarize it {url}") == [
        "Get this YouTube video", "summarize it",
    ]


@pytest.mark.parametrize("url", [
    "https://example.com/v2.1/report?source=one;part=two!detail",
    "www.example.com/report?v=2.1",
    "example.com/v2.1/report?source=one;part=two!detail",
    "stash://space_reports/report.v2.pdf",
])
def test_url_punctuation_does_not_create_task_clauses(url):
    assert query_segments(f"Read this detailed report at {url} and email the summary") == [
        "Read this detailed report at", "email the summary",
    ]


def test_markdown_url_preserves_the_following_sentence_boundary():
    assert query_segments("Read the [annual report](https://example.com/2026.pdf). Email the summary.") == [
        "Read the annual report", "Email the summary",
    ]


def test_standalone_url_can_be_a_source_but_not_a_compound_request():
    assert query_segments("Read and summarize the annual report. https://example.com/report.pdf") == [
        "summarize the annual report", "https://example.com/report.pdf",
    ]
    assert query_segments("https://www.youtube.com/watch?v=4JofSJIrjwU") == []


@pytest.mark.parametrize("query, source", [
    ("Get this YouTube video and summarize it https://www.youtube.com/watch?v=4JofSJIrjwU", "Get this YouTube video"),
    ("Get this YouTube video https://www.youtube.com/watch?v=4JofSJIrjwU and summarize it", "Get this YouTube video"),
])
def test_supplementary_query_keeps_the_source_and_focuses_the_followup(query, source):
    assert query_segments(query) == [source, "summarize it"]


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=4JofSJIrjwU",
    "https://youtu.be/4JofSJIrjwU",
    "www.youtube.com/watch?v=4JofSJIrjwU",
    "youtu.be/4JofSJIrjwU",
    "youtube.com/watch?v=4JofSJIrjwU",
    "m.youtube.com/watch?v=4JofSJIrjwU",
])
def test_pasted_link_keeps_the_supplementary_action_without_url_fragments(url):
    assert query_segments(f"Get this {url} and summarize it") == [f"Get this {url}", "summarize it"]
    assert query_segments(f"Get this {url} and summarize") == [f"Get this {url}", "summarize"]
    assert query_segments(f"Get this YouTube video and summarize it {url}") == [
        "Get this YouTube video", "summarize it",
    ]
    assert segment_retrieval_query(f"summarize it {url}") == "summarize it"
    assert segment_retrieval_query(f"Get this {url}", source_clause=True) == f"Get this {url}"
    assert query_segments(f"Get this {url}") == []


@pytest.mark.parametrize("first_clause", [
    "Check U.S. weather",
    "Check Seattle weather, e.g. rain tomorrow",
    "Open file report.v2.pdf",
    "Check version 2.1.3 release notes",
])
def test_dots_inside_tokens_do_not_hide_the_later_email_clause(first_clause):
    assert query_segments(f"{first_clause} and email me the summary today please") == [
        first_clause, "email me the summary today please",
    ]


def test_real_sentence_boundaries_still_obey_the_segment_limit():
    assert query_segments(
        "Read the annual report. Summarize the financial findings! Email me the summary; save a copy."
    ) == ["Read the annual report", "Summarize the financial findings", "Email me the summary"]


def test_supplementary_query_removes_markdown_link_syntax_but_keeps_label():
    url = "https://www.youtube.com/watch?v=4JofSJIrjwU"
    assert segment_retrieval_query(f"Get this YouTube video [{url}]({url})") == "Get this YouTube video"
    assert segment_retrieval_query(f"summarize [the video]({url})") == "summarize the video"


def test_action_with_a_separate_url_has_an_action_and_source_view():
    assert query_segments("Summarize the report. https://example.com/report.pdf") == [
        "Summarize the report", "https://example.com/report.pdf",
    ]
    assert query_segments("Summarize the report. <https://example.com/report.pdf>") == [
        "Summarize the report", "https://example.com/report.pdf",
    ]


def test_markdown_parentheses_and_autolinks_leave_no_delimiter_fragments():
    url = "https://example.com/report_(final).pdf"
    assert query_segments(f"Read [the report]({url}) and summarize <{url}>") == [
        "Read the report", "summarize",
    ]
    assert query_segments(f"<{url}>, summarize it") == [url, "summarize it"]


@pytest.mark.parametrize("prefix", ["", "Get this ", "Open this ", "Watch ", "Download ", "Fetch ", "Could you please open this ", "Please inspect this one "])
@pytest.mark.parametrize("separator", [" and ", " then ", ", ", ": ", "; ", ". ", "\n"])
def test_url_source_is_preserved_across_verbs_and_paste_separators(prefix, separator):
    url = "https://youtu.be/abc123"
    queries = query_segments(f"{prefix}{url}{separator}summarize it")
    assert len(queries) == 2
    assert url in queries[0]
    assert queries[1] == "summarize it"


@pytest.mark.parametrize("query", [
    "Check this out https://youtu.be/abc123. Crazy right?",
    "https://youtu.be/abc123. Hi.",
    "Hi. https://youtu.be/abc123",
    "https://youtu.be/abc123 and thanks",
    "https://youtu.be/abc123. Thanks very much!",
    "https://youtu.be/abc123. Pretty amazing, right?",
    "Hi. Thanks. https://youtu.be/abc123",
])
def test_link_with_conversational_fragments_stays_on_the_full_query(query):
    assert query_segments(query) == []


def test_chatter_is_filtered_before_it_can_spend_the_segment_limit():
    url = "https://youtu.be/abc123"
    assert query_segments(f"Hi. {url}. Crazy right? Summarize it and email the summary. Thanks!") == [
        url, "Summarize it", "email the summary",
    ]


def test_repeated_followup_queries_are_deduplicated_after_url_removal():
    assert query_segments(
        "Read this annual report https://example.com/report.pdf and "
        "email it https://example.com/one and email it https://example.com/two"
    ) == ["Read this annual report", "email it"]


def test_descriptive_source_keeps_room_for_both_followup_actions():
    assert query_segments(
        "Get this YouTube video https://youtu.be/abc123 and summarize it and email the summary"
    ) == ["Get this YouTube video", "summarize it", "email the summary"]


def test_long_dotted_filename_stays_intact_and_semicolon_still_splits_without_spaces():
    filename = "revision." * 500 + "pdf"
    assert query_segments(f"Read the annual report {filename};email the summary") == [
        f"Read the annual report {filename}", "email the summary",
    ]


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
