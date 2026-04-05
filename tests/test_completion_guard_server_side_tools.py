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
    def test_normalize_server_side_tool_names(self):
        tools = ChatHandler._normalize_server_side_tool_names({
            "SERVER_SIDE_TOOL_X_SEARCH": 2,
            "SERVER_SIDE_TOOL_WEB_SEARCH": 1,
        })

        self.assertEqual(
            tools,
            ["native:x_search", "native:x_search", "native:web_search"]
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


if __name__ == "__main__":
    unittest.main()
