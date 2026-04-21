#!/usr/bin/env python3
"""
Regression tests for orchestrator usage passthrough decisions.

Run:
    python3 tests/test_orchestrator_usage_passthrough.py
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

from orchestrator_v2 import Orchestrator


class OrchestratorUsagePassthroughTests(unittest.TestCase):
    def test_has_usage_data_when_only_tokens_are_present(self):
        usage = {
            "input_tokens": 1200,
            "output_tokens": 45,
            "cost_usd": 0.0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "cache_savings_usd": 0.0,
            "server_side_tools": {},
        }
        self.assertTrue(Orchestrator._has_usage_data(usage))

    def test_has_usage_data_when_only_server_side_tools_are_present(self):
        usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "cache_savings_usd": 0.0,
            "server_side_tools": {"SERVER_SIDE_TOOL_X_SEARCH": 2},
        }
        self.assertTrue(Orchestrator._has_usage_data(usage))

    def test_has_usage_data_false_for_empty_usage(self):
        usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "cache_savings_usd": 0.0,
            "server_side_tools": {},
        }
        self.assertFalse(Orchestrator._has_usage_data(usage))

    def test_log_conversation_metadata_includes_xai_native_search_usage(self):
        handler = Orchestrator.__new__(Orchestrator)
        handler.mode = "cloud"
        handler.session_id = "session-1"
        handler.web_conversation_id = "conv-1"
        handler.router = SimpleNamespace(
            provider_type="xai",
            model_name="grok-4-1-fast-non-reasoning-latest",
        )

        captured = {}

        class FakeDb:
            def log_conversation(self, **kwargs):
                captured.update(kwargs)

            def close(self):
                pass

        token_info = {
            "input_tokens": 100,
            "output_tokens": 20,
            "cost_usd": 0.01,
            "server_side_tools": {"SERVER_SIDE_TOOL_WEB_SEARCH": 8},
        }

        with patch("orchestrator_v2.get_memory_db", return_value=FakeDb()):
            handler._log_conversation(
                "fresh movie search",
                "found showtimes",
                ["canvas"],
                token_info=token_info,
            )

        metadata = captured["metadata"]
        self.assertEqual(metadata["web_conversation_id"], "conv-1")
        self.assertEqual(metadata["tool_count"], 1)
        self.assertEqual(metadata["server_side_tools"], {"SERVER_SIDE_TOOL_WEB_SEARCH": 8})
        self.assertEqual(metadata["server_side_tool_calls"], 8)
        self.assertEqual(metadata["xai_search_calls"], 8)
        self.assertEqual(metadata["xai_search_tools"], ["SERVER_SIDE_TOOL_WEB_SEARCH"])


if __name__ == "__main__":
    unittest.main()
