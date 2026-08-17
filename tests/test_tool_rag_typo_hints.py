#!/usr/bin/env python3
"""Unit tests for Tool RAG typo hints (Damerau–Levenshtein, ties skipped)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from tool_rag_typo_hints import (
    expand_tool_rag_query_for_typo_hints,
    optimal_string_alignment_distance,
)


class TestOptimalStringAlignment(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(optimal_string_alignment_distance("abc", "abc"), 0)

    def test_single_substitution(self):
        self.assertEqual(optimal_string_alignment_distance("bookmarks", "bookmorks"), 1)

    def test_adjacent_transpose_bookmakrs(self):
        """Common misspelling: k/r swap."""
        self.assertEqual(optimal_string_alignment_distance("bookmakrs", "bookmarks"), 1)

    def test_bookmakrs_to_bookmark_segment_distance(self):
        """Segment match for production tool name bookmark_search (full name is farther)."""
        self.assertEqual(optimal_string_alignment_distance("bookmakrs", "bookmark"), 2)
        self.assertGreater(optimal_string_alignment_distance("bookmakrs", "bookmark_search"), 2)

    def test_two_edits_when_needed(self):
        self.assertLessEqual(optimal_string_alignment_distance("cheeze", "cheese"), 2)


class TestExpandToolRagQuery(unittest.TestCase):
    def setUp(self):
        self.tools = [
            "bookmark_search",
            "weather",
            "crypto_price",
            "mcp_brave_search_web",
            "search_memory",
        ]

    def test_bookmakrs_hints_bookmark_search(self):
        """Two-edit segment guesses are now intentionally skipped."""
        q, hints = expand_tool_rag_query_for_typo_hints(
            "check my bookmakrs for cheese",
            self.tools,
            enabled=True,
            max_distance=2,
            min_token_len=4,
        )
        self.assertEqual(hints, [])
        self.assertEqual(q, "check my bookmakrs for cheese")
        self.assertTrue(q.startswith("check my bookmakrs"))

    def test_exact_tool_name_no_duplicate_hint(self):
        q, hints = expand_tool_rag_query_for_typo_hints(
            "run bookmark_search now",
            self.tools,
            enabled=True,
            max_distance=2,
            min_token_len=4,
        )
        self.assertEqual(hints, [])

    def test_exact_two_word_compound_hints_complete_tool_name(self):
        query = "Use open code to build a complex Python calculator"
        q, hints = expand_tool_rag_query_for_typo_hints(
            query,
            ["opencode", "calculator"],
            hint_source=query,
            enabled=True,
            max_distance=1,
        )
        self.assertEqual(hints, ["opencode"])
        self.assertEqual(q, f"{query} opencode")

    def test_exact_three_word_compound_hints_underscored_tool_name(self):
        query = "please check tool logs for the failure"
        q, hints = expand_tool_rag_query_for_typo_hints(
            query,
            ["check_tool_logs", "tool_search"],
            hint_source=query,
            enabled=True,
            max_distance=1,
        )
        self.assertEqual(hints, ["check_tool_logs"])
        self.assertEqual(q, f"{query} check_tool_logs")

    def test_nonadjacent_words_do_not_form_compound_hint(self):
        query = "open the source code"
        q, hints = expand_tool_rag_query_for_typo_hints(
            query,
            ["opencode"],
            enabled=True,
            max_distance=1,
        )
        self.assertEqual(hints, [])
        self.assertEqual(q, query)

    def test_ambiguous_normalized_compound_is_skipped(self):
        query = "use open code"
        q, hints = expand_tool_rag_query_for_typo_hints(
            query,
            ["opencode", "open_code"],
            enabled=True,
            max_distance=1,
        )
        self.assertEqual(hints, [])
        self.assertEqual(q, query)

    def test_longest_exact_compound_wins_over_overlapping_tool_name(self):
        query = "check tool logs"
        q, hints = expand_tool_rag_query_for_typo_hints(
            query,
            ["check_tool_logs", "tool_logs"],
            enabled=True,
            max_distance=1,
        )
        self.assertEqual(hints, ["check_tool_logs"])
        self.assertEqual(q, f"{query} check_tool_logs")

    def test_short_tokens_do_not_accidentally_form_glued_tool_names(self):
        cases = (
            ("write a handler for GET requests", ["forget"]),
            ("I need this for GET endpoints", ["forget"]),
            ("please re-call the weather API", ["recall"]),
            ("re-call that function", ["recall"]),
        )
        for query, tools in cases:
            with self.subTest(query=query):
                q, hints = expand_tool_rag_query_for_typo_hints(
                    query,
                    tools,
                    enabled=True,
                    max_distance=1,
                    min_token_len=2,
                )
                self.assertEqual(hints, [])
                self.assertEqual(q, query)

    def test_separator_tool_still_allows_short_compound_token(self):
        query = "make an API call"
        q, hints = expand_tool_rag_query_for_typo_hints(
            query,
            ["api_call"],
            enabled=True,
            max_distance=1,
        )
        self.assertEqual(hints, ["api_call"])
        self.assertEqual(q, f"{query} api_call")

    def test_compound_and_later_typo_preserve_query_order(self):
        query = "open code and check the weathr"
        q, hints = expand_tool_rag_query_for_typo_hints(
            query,
            ["opencode", "weather"],
            enabled=True,
            max_distance=1,
        )
        self.assertEqual(hints, ["opencode", "weather"])
        self.assertEqual(q, f"{query} opencode weather")

    def test_hint_source_isolates_compound_matching(self):
        query = "Context recommends open code\nCurrent request: say hello"
        q, hints = expand_tool_rag_query_for_typo_hints(
            query,
            ["opencode"],
            hint_source="say hello",
            enabled=True,
            max_distance=1,
        )
        self.assertEqual(hints, [])
        self.assertEqual(q, query)

    def test_four_token_compound_matches_complete_tool_name(self):
        query = "use MCP brave search web for this"
        q, hints = expand_tool_rag_query_for_typo_hints(
            query,
            ["mcp_brave_search_web"],
            enabled=True,
            max_distance=1,
        )
        self.assertEqual(hints, ["mcp_brave_search_web"])
        self.assertEqual(q, f"{query} mcp_brave_search_web")

    def test_short_token_skipped(self):
        q, hints = expand_tool_rag_query_for_typo_hints(
            "ab cr xzqq",
            self.tools,
            enabled=True,
            max_distance=2,
            min_token_len=4,
        )
        self.assertEqual(hints, [])

    def test_tie_multiple_tools_same_min_distance_skips(self):
        """Two tools equally close → no hint (safety)."""
        tools = ["alpha_x", "alpha_y"]
        q, hints = expand_tool_rag_query_for_typo_hints(
            "check alpha_z please",
            tools,
            enabled=True,
            max_distance=2,
            min_token_len=4,
        )
        self.assertEqual(hints, [])

    def test_long_mcp_typo_one_hint(self):
        q, hints = expand_tool_rag_query_for_typo_hints(
            "search mcp_brave_seach_web for news",
            ["mcp_brave_search_web", "weather"],
            enabled=True,
            max_distance=2,
            min_token_len=4,
        )
        self.assertEqual(hints, ["mcp_brave_search_web"])
        self.assertIn("mcp_brave_search_web", q)

    def test_disabled_returns_original(self):
        q, hints = expand_tool_rag_query_for_typo_hints(
            "bookmakrs",
            ["bookmark_search"],
            enabled=False,
        )
        self.assertEqual(q, "bookmakrs")
        self.assertEqual(hints, [])

    def test_weather_typo(self):
        q, hints = expand_tool_rag_query_for_typo_hints(
            "what is weathr in NYC",
            self.tools,
            enabled=True,
            max_distance=2,
            min_token_len=4,
        )
        self.assertEqual(hints, ["weather"])

    def test_url_stripped_no_hint_for_host_typo(self):
        """https://... removed before tokenize — weathr inside URL must not hint weather."""
        q, hints = expand_tool_rag_query_for_typo_hints(
            "check https://weathr.com now",
            ["weather"],
            enabled=True,
            max_distance=2,
            min_token_len=4,
        )
        self.assertEqual(hints, [])
        self.assertEqual(q, "check https://weathr.com now")

    def test_plain_text_weathr_still_hints(self):
        q, hints = expand_tool_rag_query_for_typo_hints(
            "check weathr in Portland",
            ["weather"],
            enabled=True,
            max_distance=2,
            min_token_len=4,
        )
        self.assertEqual(hints, ["weather"])

    def test_generic_segments_do_not_trigger_false_positive_hints(self):
        q, hints = expand_tool_rag_query_for_typo_hints(
            "find my recent tool logs",
            ["network_tools", "search_docs", "check_tool_logs"],
            enabled=True,
            max_distance=2,
            min_token_len=4,
        )
        self.assertEqual(hints, [])
        self.assertEqual(q, "find my recent tool logs")

    def test_segment_matching_is_limited_to_one_edit(self):
        q, hints = expand_tool_rag_query_for_typo_hints(
            "check my bookmakrs for cheese",
            ["bookmark_search"],
            enabled=True,
            max_distance=2,
            min_token_len=4,
        )
        self.assertEqual(hints, [])
        self.assertEqual(q, "check my bookmakrs for cheese")

    def test_hint_source_scans_user_text_only(self):
        """Orchestrator passes hint_source=raw user request; do not scan intelligence/context."""
        noisy_blob = "\n".join(
            [
                "=== LEARNED STRATEGIES ===",
                "Always convert files with convert_file and use execute_bash for shells.",
                "",
                "check my bookmakrs for anything",
            ]
        )
        q, hints = expand_tool_rag_query_for_typo_hints(
            noisy_blob,
            ["bookmark_search", "execute_bash", "convert_file", "weather"],
            hint_source="check my bookmakrs for anything",
            enabled=True,
            max_distance=2,
            min_token_len=4,
        )
        self.assertEqual(hints, [])
        self.assertNotIn("bookmark_search", q)
        self.assertTrue(q.startswith("=== LEARNED"))


if __name__ == "__main__":
    unittest.main()
