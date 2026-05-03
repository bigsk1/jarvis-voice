#!/usr/bin/env python3
"""Tests for LLM tool-result preview truncation (orchestrator_v2)."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

from orchestrator_v2 import Orchestrator


class ToolContextPreviewTests(unittest.TestCase):
    def setUp(self):
        self.orch = Orchestrator.__new__(Orchestrator)

    def test_url_field_allows_long_querystrings(self):
        """Regression: generic strings used to cap at 240 chars, truncating URLs."""
        long = "https://example.com/path?" + "q=" + "a" * 400
        out = self.orch._build_preview_value({"url": long, "title": "x"}, parent_key="data")
        self.assertEqual(out["url"], long)
        self.assertNotIn("[truncated]", out["url"])

    def test_non_url_string_still_short(self):
        out = self.orch._build_preview_value({"note": "x" * 500}, parent_key="data")
        self.assertIn("[truncated]", out["note"])

    def test_bookmark_search_gets_larger_preview_budget(self):
        self.assertEqual(self.orch._tool_context_max_chars("bookmark_search"), 5000)
        self.assertEqual(self.orch._tool_context_max_chars("serpapi_web_search"), 6000)


if __name__ == "__main__":
    unittest.main()
