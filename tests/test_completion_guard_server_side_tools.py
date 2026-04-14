#!/usr/bin/env python3
"""
Regression tests for Completion Guard handling of provider-native server-side tools.

Run:
    python3 tests/test_completion_guard_server_side_tools.py
"""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))

fake_socketio = types.ModuleType("flask_socketio")
fake_socketio.emit = lambda *args, **kwargs: None
fake_socketio.join_room = lambda *args, **kwargs: None
fake_socketio.leave_room = lambda *args, **kwargs: None
sys.modules.setdefault("flask_socketio", fake_socketio)

fake_flask = types.ModuleType("flask")
fake_flask.request = object()
sys.modules.setdefault("flask", fake_flask)

from server.sockets.chat import ChatHandler


class CompletionGuardServerSideToolsTests(unittest.TestCase):
    def test_completion_guard_location_context_uses_default_location(self):
        with patch("config_loader.load_config"), patch(
            "config_loader.get_config_value", return_value="Hillsboro, Oregon"
        ):
            context = ChatHandler._get_completion_guard_location_context("cloud")

        self.assertIn("Configured default location:\nHillsboro, Oregon", context)
        self.assertIn('location-relative question like "near me"', context)
        self.assertIn("allowed fallback", context)

    def test_normalize_server_side_tool_names(self):
        tools = ChatHandler._normalize_server_side_tool_names({
            "SERVER_SIDE_TOOL_X_SEARCH": 2,
            "SERVER_SIDE_TOOL_VIEW_IMAGE": 1,
            "SERVER_SIDE_TOOL_WEB_SEARCH": 1,
        })

        self.assertEqual(
            tools,
            ["native:x_search", "native:x_search", "native:view_image", "native:web_search"]
        )

    def test_feedback_context_counts_native_tools_as_real_usage(self):
        record = {
            "tools_used": [],
            "server_side_tools": {"SERVER_SIDE_TOOL_X_SEARCH": 1},
            "repair_result": {"tools_used": [], "server_side_tools": {}},
            "speech": "Found results.",
            "raw_llm_response": "Found results with native search."
        }

        context = ChatHandler._build_completion_guard_feedback_context(record, "cancelled")

        self.assertEqual(context["combined_tools_used"], ["native:x_search"])
        self.assertEqual(context["original_response"]["tools_used"], ["native:x_search"])

    def test_compute_effective_evidence_rebuilds_for_native_server_side_tools(self):
        handler = ChatHandler.__new__(ChatHandler)

        ev = handler._compute_effective_evidence(
            "conv1",
            {"raw_llm_response": "Found results with native search."},
            [],
            {"SERVER_SIDE_TOOL_WEB_SEARCH": 1, "SERVER_SIDE_TOOL_VIEW_IMAGE": 1},
            "msg-web-1",
            "find restaurants near me",
        )

        self.assertEqual(
            ev["supporting_tools_used"],
            ["native:web_search", "native:view_image"],
        )
        native = ev["supporting_tool_results"]["native_tools"]
        self.assertEqual(native["server_side_tools"]["SERVER_SIDE_TOOL_WEB_SEARCH"], 1)
        self.assertEqual(
            native["normalized_tools"],
            ["native:web_search", "native:view_image"],
        )
        self.assertFalse(ev["derived_from_prior"])

    def test_completion_guard_eval_prompt_includes_default_location_context(self):
        handler = ChatHandler.__new__(ChatHandler)
        captured = {}

        class _FakeProvider:
            def chat(self, prompt, system_prompt=None, max_tokens=None):
                captured["prompt"] = prompt
                return """{
  "recommended_action": "accept",
  "task_status": "complete",
  "risk_level": "low",
  "repair_worthwhile": false,
  "failure_types": [],
  "missing_requirements": [],
  "unsupported_claims": [],
  "contradictions": [],
  "evidence_gaps": [],
  "reason": "supported",
  "suggested_note": ""
}"""

        handler._create_completion_guard_eval_provider = lambda **kwargs: ("openai", "test-model", _FakeProvider())

        record = {
            "mode": "cloud",
            "query": "what are some of the best places to eat near me?",
            "raw_llm_response": "Top-rated restaurants in Hillsboro, OR (default location).",
            "speech": "Top-rated restaurants in Hillsboro, OR.",
            "tools_used": ["mcp_brave_search_brave_local_search"],
            "server_side_tools": {},
            "available_tools": ["mcp_brave_search_brave_local_search"],
            "data": {"sample": "value"},
            "completion_guard": {},
        }

        with patch("config_loader.load_config"), patch(
            "config_loader.get_config_value", return_value="Hillsboro, Oregon"
        ):
            parsed = handler._evaluate_completion_guard_auto(record)

        self.assertEqual(parsed["recommended_action"], "accept")
        self.assertIn("Configured default location:\nHillsboro, Oregon", captured["prompt"])
        self.assertIn('location-relative question like "near me"', captured["prompt"])
        self.assertIn("allowed fallback", captured["prompt"])

    def test_tighten_instead_of_substantive_repair_when_same_tools_and_similar_answer(self):
        delta = {
            "operational_correction": True,
            "tool_path_delta": False,
            "evidence_delta": True,
            "answer_similarity": 0.91,
        }
        self.assertTrue(ChatHandler._completion_guard_tighten_instead_of_substantive_repair(delta))

    def test_substantive_repair_when_tool_path_changes(self):
        delta = {
            "operational_correction": True,
            "tool_path_delta": True,
            "answer_similarity": 0.95,
        }
        self.assertFalse(ChatHandler._completion_guard_tighten_instead_of_substantive_repair(delta))

    def test_substantive_repair_when_answer_diverges(self):
        delta = {
            "operational_correction": True,
            "tool_path_delta": False,
            "answer_similarity": 0.5,
        }
        self.assertFalse(ChatHandler._completion_guard_tighten_instead_of_substantive_repair(delta))


if __name__ == "__main__":
    unittest.main()
