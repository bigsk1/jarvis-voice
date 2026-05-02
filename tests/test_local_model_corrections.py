#!/usr/bin/env python3
"""Regression tests for lib.local_model_corrections."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from lib.local_model_corrections import correct_tool_call, normalize_brave_freshness


class LocalModelCorrectionsTests(unittest.TestCase):
    def test_normalize_brave_freshness_aliases(self):
        self.assertEqual(normalize_brave_freshness("today"), "pd")
        self.assertEqual(normalize_brave_freshness("past week"), "pw")
        self.assertEqual(normalize_brave_freshness("30 days"), "pm")
        self.assertEqual(normalize_brave_freshness("last year"), "py")

    def test_normalize_brave_freshness_date_range(self):
        self.assertEqual(
            normalize_brave_freshness("2026-05-01 to 2026-05-02"),
            "2026-05-01to2026-05-02",
        )
        self.assertEqual(
            normalize_brave_freshness("2026-05-01_to_2026-05-02"),
            "2026-05-01to2026-05-02",
        )

    def test_correct_tool_call_normalizes_brave_news_freshness_only(self):
        corrected = correct_tool_call({
            "name": "mcp_brave_search_brave_news_search",
            "arguments": {
                "query": "latest ai news",
                "freshness": "today",
            },
        })
        self.assertEqual(corrected["arguments"]["freshness"], "pd")

        untouched = correct_tool_call({
            "name": "mcp_brave_search_brave_web_search",
            "arguments": {
                "query": "latest ai news",
                "freshness": "today",
            },
        })
        self.assertEqual(untouched["arguments"]["freshness"], "today")


if __name__ == "__main__":
    unittest.main()
