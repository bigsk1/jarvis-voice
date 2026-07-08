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

    def test_has_usage_data_when_only_router_prompt_provenance_is_present(self):
        self.assertTrue(Orchestrator._has_usage_data({"router_prompt_version": "v1"}))

    def test_attaches_router_prompt_version_without_replacing_initial_version(self):
        handler = Orchestrator.__new__(Orchestrator)
        handler.router = SimpleNamespace(system_prompt_version="v2")

        usage = handler._attach_router_prompt_usage({"input_tokens": 10})
        continued_usage = handler._attach_router_prompt_usage({"router_prompt_version": "v1"})

        self.assertEqual(usage["router_prompt_version"], "v2")
        self.assertEqual(continued_usage["router_prompt_version"], "v1")

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

    def test_previous_experience_id_from_history_uses_latest_assistant_id(self):
        handler = Orchestrator.__new__(Orchestrator)

        exp_id = handler._previous_experience_id_from_history([
            {"role": "assistant", "content": "older", "experience_id": 101},
            {"role": "user", "content": "next"},
            {"role": "assistant", "content": "newer", "experience_id": "202"},
        ])

        self.assertEqual(exp_id, 202)

    def test_log_conversation_metadata_includes_experience_id(self):
        handler = Orchestrator.__new__(Orchestrator)
        handler.mode = "cloud"
        handler.session_id = "session-1"
        handler.web_conversation_id = None
        handler.router = SimpleNamespace(
            provider_type="xai",
            model_name="grok-4.3",
        )

        captured = {}

        class FakeDb:
            def log_conversation(self, **kwargs):
                captured.update(kwargs)

            def close(self):
                pass

        with patch("orchestrator_v2.get_memory_db", return_value=FakeDb()):
            handler._log_conversation(
                "follow up question",
                "updated answer",
                ["weather"],
                experience_id=515,
            )

        self.assertEqual(captured["metadata"]["experience_id"], 515)

    def test_resolve_previous_experience_id_for_auto_context(self):
        handler = Orchestrator.__new__(Orchestrator)
        handler.session_id = "wake-1"

        class FakeDb:
            def get_previous_experience_id_from_recent_conversations(self, within_minutes, session_id):
                self.within_minutes = within_minutes
                self.session_id = session_id
                return 909

            def close(self):
                pass

        fake_db = FakeDb()
        with patch("orchestrator_v2.get_memory_db", return_value=fake_db), patch(
            "orchestrator_v2.get_int", return_value=10
        ):
            exp_id = handler._resolve_previous_experience_id_for_auto_context()

        self.assertEqual(exp_id, 909)
        self.assertEqual(fake_db.session_id, "wake-1")
        self.assertEqual(fake_db.within_minutes, 10)

    def test_resolve_previous_experience_id_for_auto_context_falls_back_to_global_recent(self):
        handler = Orchestrator.__new__(Orchestrator)
        handler.session_id = "fresh-wake-session"

        class FakeDb:
            def __init__(self):
                self.calls = []

            def get_previous_experience_id_from_recent_conversations(self, within_minutes, session_id):
                self.calls.append((within_minutes, session_id))
                if session_id == "fresh-wake-session":
                    return None
                return 808

            def close(self):
                pass

        fake_db = FakeDb()
        with patch("orchestrator_v2.get_memory_db", return_value=fake_db), patch(
            "orchestrator_v2.get_int", return_value=10
        ):
            exp_id = handler._resolve_previous_experience_id_for_auto_context()

        self.assertEqual(exp_id, 808)
        self.assertEqual(fake_db.calls, [(10, "fresh-wake-session"), (10, None)])

    def test_log_conversation_metadata_includes_xai_native_search_usage(self):
        handler = Orchestrator.__new__(Orchestrator)
        handler.mode = "cloud"
        handler.session_id = "session-1"
        handler.web_conversation_id = "conv-1"
        handler.router = SimpleNamespace(
            provider_type="xai",
            model_name="grok-4.3",
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
