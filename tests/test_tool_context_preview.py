#!/usr/bin/env python3
"""Tests for LLM tool-result preview truncation (orchestrator_v2)."""

import sys
import unittest
import json
from pathlib import Path
from zoneinfo import ZoneInfo

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

    def test_search_preview_lifts_exact_source_candidates(self):
        long_blob = "x" * 9000
        result = {
            "ok": True,
            "speech": "Found 2 YouTube results.",
            "data": {
                "engine": "youtube",
                "search_query": "cheddar cheese video",
                "top_url": "https://www.youtube.com/watch?v=abc123",
                "next_page_token": long_blob,
                "results": [
                    {
                        "title": "Cheddar explained",
                        "url": "https://www.youtube.com/watch?v=abc123",
                        "video_id": "abc123",
                        "channel": "Cheese Channel",
                        "duration": "2:00",
                    },
                    {
                        "title": "Cheddar factory tour",
                        "url": "https://www.youtube.com/watch?v=def456",
                        "video_id": "def456",
                        "channel": "Food Channel",
                        "duration": "5:00",
                    },
                ],
            },
        }

        preview, _total, _shown, truncated = self.orch._build_llm_result_context_preview(
            "serpapi_youtube_search",
            result,
        )

        parsed = json.loads(preview)
        candidates = parsed["llm_context_preview"]["source_candidates"]
        self.assertTrue(truncated)
        self.assertEqual(candidates[0]["url"], "https://www.youtube.com/watch?v=abc123")
        self.assertEqual(candidates[1]["video_id"], "def456")
        self.assertIn("Cheddar factory tour", preview)

    def test_turn_context_marks_truncated_arguments_as_display_only(self):
        self.orch.timezone = ZoneInfo("America/Los_Angeles")
        context = self.orch._build_turn_context(
            "update bugs intel",
            [
                {
                    "tool": "manage_intel",
                    "arguments": {
                        "action": "append",
                        "path": "2026-garden-bugs.md",
                        "content": "Widow Skimmer\n" + ("details " * 200) + "Hoverfly",
                    },
                    "result": {"ok": True, "speech": "Append complete", "data": {}},
                    "meta": {},
                }
            ],
        )

        self.assertIn("Arguments Meta: arguments_truncated=true", context)
        self.assertIn("complete arguments were sent to the tool", context)
        self.assertIn("does not indicate partial execution", context)

    def test_provider_result_marks_truncated_arguments(self):
        assembler = self.orch._get_context_assembler()
        message, metadata = assembler.build_provider_tool_result_message(
            tool_name="manage_intel",
            arguments={"action": "append", "path": "bugs.md", "content": "x" * 2000},
            result={"ok": True, "speech": "Append complete", "data": {"appended": True}},
            max_chars=1800,
        )

        self.assertTrue(metadata["arguments_truncated"])
        self.assertIn("arguments_truncated=true", message)
        self.assertIn("preview does not indicate partial execution", message)

    def test_provider_result_marks_complete_arguments_untruncated(self):
        assembler = self.orch._get_context_assembler()
        message, metadata = assembler.build_provider_tool_result_message(
            tool_name="manage_intel",
            arguments={"action": "read", "path": "bugs.md"},
            result={"ok": True, "speech": "Read complete", "data": {"size_bytes": 42}},
            max_chars=1800,
        )

        self.assertFalse(metadata["arguments_truncated"])
        self.assertIn("arguments_truncated=false", message)


if __name__ == "__main__":
    unittest.main()
