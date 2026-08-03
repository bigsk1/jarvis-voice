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
        self.assertEqual(self.orch._tool_context_max_chars("workflow"), 8000)

    def test_workflow_preview_keeps_late_step_handles_and_omits_variables_graph(self):
        steps = []
        for index in range(1, 14):
            data = {
                "content": f"step {index} " + ("large payload " * 700),
                "status": "complete",
            }
            if index == 1:
                data["stash_ref"] = "stash://research/source-1"
            if index == 13:
                data["page_id"] = "page_final_13"
                data["url"] = "https://jarvis.example/canvas/page_final_13"
            steps.append(
                {
                    "step": index,
                    "tool": "canvas" if index == 13 else "stash",
                    "ok": True,
                    "data": data,
                    "duration_ms": index * 10,
                }
            )

        result = {
            "ok": True,
            "speech": "Workflow complete.",
            "data": {
                "action": "run",
                "workflow_id": "deep_research",
                "workflow_name": "Deep Research",
                "execution": "foreground",
                "workflow_started": True,
                "workflow_completed": True,
                "steps_completed": 13,
                "component_tools_used": ["stash", "canvas"],
                "results": steps,
                "variables": {"huge": "do not expose " * 5000},
            },
        }

        preview, total, shown, truncated = self.orch._build_llm_result_context_preview(
            "workflow",
            result,
        )

        parsed = json.loads(preview)
        step_results = parsed["llm_context_preview"]["step_results"]
        self.assertTrue(truncated)
        self.assertGreater(total, shown)
        self.assertLessEqual(shown, 8000)
        self.assertEqual(len(step_results), 13)
        self.assertIn("stash://research/source-1", preview)
        self.assertIn("page_final_13", preview)
        self.assertNotIn("do not expose", preview)

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

    def test_hotel_preview_keeps_compact_prices_pet_status_and_urls(self):
        result = {
            "ok": True,
            "speech": "Found 6 hotel options. Lowest returned price is $113 total.",
            "data": {
                "engine": "google_hotels",
                "destination": "Mesa, Arizona",
                "raw": {"large_provider_payload": "x" * 12000},
                "top_results": [
                    {
                        "title": f"Mesa Hotel {index}",
                        "url": f"https://hotels.example/{index}",
                        "rating": 4.0 + (index / 10),
                        "price_total": f"${110 + index}",
                        "price_per_night": f"${55 + index}",
                        "amenities": (
                            ["Free Wi-Fi", "Pet-friendly"]
                            if index % 2
                            else ["Free Wi-Fi", "Pool"]
                        ),
                        "description": "details " * 200,
                    }
                    for index in range(1, 7)
                ],
            },
        }

        preview, _total, shown, truncated = self.orch._build_llm_result_context_preview(
            "serpapi_hotel_search",
            result,
        )

        parsed = json.loads(preview)
        candidates = parsed["llm_context_preview"]["source_candidates"]
        self.assertTrue(truncated)
        self.assertLessEqual(shown, 6000)
        self.assertEqual(len(candidates), 5)
        self.assertEqual(candidates[0]["price_total"], "$111")
        self.assertEqual(candidates[0]["price_per_night"], "$56")
        self.assertEqual(candidates[0]["rating"], 4.1)
        self.assertTrue(candidates[0]["pet_friendly"])
        self.assertFalse(candidates[1]["pet_friendly"])
        self.assertEqual(candidates[4]["url"], "https://hotels.example/5")
        self.assertNotIn("amenities", candidates[0])

    def test_yelp_preview_keeps_compact_business_identity_and_details(self):
        result = {
            "ok": True,
            "speech": "Found 6 Yelp options.",
            "data": {
                "engine": "yelp",
                "find_desc": "coffee shops",
                "find_loc": "Hillsboro, OR",
                "raw": {"large_provider_payload": "x" * 12000},
                "results": [
                    {
                        "title": f"Hillsboro Cafe {index}",
                        "url": f"https://www.yelp.com/biz/hillsboro-cafe-{index}",
                        "place_id": f"place-{index}",
                        "rating": 4.0 + (index / 10),
                        "reviews": index * 100,
                        "price": "$$",
                        "categories": ["Coffee & Tea", "Cafes"],
                        "neighborhoods": "Hillsboro",
                        "open_state": "Open until 8:00 PM",
                        "snippet": "A locally grounded Yelp snippet. " * 20,
                        "service_options": {"takeout": True},
                    }
                    for index in range(1, 7)
                ],
            },
        }

        preview, _total, shown, truncated = self.orch._build_llm_result_context_preview(
            "serpapi_yelp_search",
            result,
        )

        parsed = json.loads(preview)
        candidates = parsed["llm_context_preview"]["source_candidates"]
        self.assertTrue(truncated)
        self.assertLessEqual(shown, 6000)
        self.assertEqual(len(candidates), 5)
        self.assertEqual(candidates[0]["place_id"], "place-1")
        self.assertEqual(candidates[0]["reviews"], 100)
        self.assertEqual(candidates[0]["categories"], ["Coffee & Tea", "Cafes"])
        self.assertEqual(candidates[0]["neighborhoods"], "Hillsboro")
        self.assertEqual(candidates[0]["open_state"], "Open until 8:00 PM")
        self.assertIn("locally grounded", candidates[0]["snippet"])
        self.assertEqual(
            candidates[4]["url"],
            "https://www.yelp.com/biz/hillsboro-cafe-5",
        )
        self.assertNotIn("service_options", candidates[0])

    def test_flight_preview_keeps_compact_option_identity_including_flight_numbers(self):
        result = {
            "ok": True,
            "speech": "Found 2 round-trip flight options from PDX to PHX.",
            "data": {
                "provider": "serpapi",
                "trip_type": "round_trip",
                "departure_id": "PDX",
                "arrival_id": "PHX",
                "outbound_date": "2099-09-15",
                "return_date": "2099-09-20",
                "currency": "USD",
                "results_count": 2,
                "cheapest_price": 257,
                "price_basis": "round_trip_total",
                "booking_url": "https://www.google.com/travel/flights",
                "results": [
                    {
                        "price": 257 + index,
                        "airlines": ["Alaska"],
                        "flight_numbers": [f"AS {1349 + index}"],
                        "departure_airport": "PDX",
                        "departure_time": f"2099-09-15 0{7 + index}:03",
                        "arrival_airport": "PHX",
                        "arrival_time": f"2099-09-15 {9 + index:02d}:51",
                        "duration_display": "2h 48m",
                        "stops_label": "Nonstop",
                        "segments": [{"flight_number": f"AS {1349 + index}"}],
                    }
                    for index in range(2)
                ],
            },
        }

        preview, total, shown, truncated = self.orch._build_llm_result_context_preview(
            "flight_search",
            result,
        )

        parsed = json.loads(preview)
        candidates = parsed["llm_context_preview"]["source_candidates"]
        self.assertTrue(truncated)
        self.assertGreater(total, shown)
        self.assertEqual(candidates[0]["airlines"], ["Alaska"])
        self.assertEqual(candidates[0]["departure_time"], "2099-09-15 07:03")
        self.assertEqual(candidates[0]["arrival_time"], "2099-09-15 09:51")
        self.assertEqual(candidates[0]["price"], 257)
        self.assertEqual(candidates[0]["flight_numbers"], ["AS 1349"])
        self.assertIn("AS 1349", preview)
        self.assertNotIn("segments", candidates[0])

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
