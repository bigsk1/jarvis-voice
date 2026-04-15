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
        """Production name: typo vs 'bookmark' segment → hint canonical bookmark_search."""
        q, hints = expand_tool_rag_query_for_typo_hints(
            "check my bookmakrs for cheese",
            self.tools,
            enabled=True,
            max_distance=2,
            min_token_len=4,
        )
        self.assertEqual(hints, ["bookmark_search"])
        self.assertIn("bookmark_search", q)
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
        self.assertEqual(hints, ["bookmark_search"])
        self.assertIn("bookmark_search", q)
        self.assertTrue(q.startswith("=== LEARNED"))


if __name__ == "__main__":
    unittest.main()
