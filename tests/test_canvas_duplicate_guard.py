#!/usr/bin/env python3
"""
Regression tests for duplicate-prevention and Completion Guard canvas repair handling.

Run:
    python3 tests/test_canvas_duplicate_guard.py
"""

import sys
import types
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

fake_socketio = types.ModuleType("flask_socketio")
fake_socketio.emit = lambda *args, **kwargs: None
fake_socketio.join_room = lambda *args, **kwargs: None
fake_socketio.leave_room = lambda *args, **kwargs: None
sys.modules.setdefault("flask_socketio", fake_socketio)

fake_flask = types.ModuleType("flask")
fake_flask.request = object()
sys.modules.setdefault("flask", fake_flask)

from orchestrator.orchestrator_v2 import Orchestrator
from server.sockets.chat import ChatHandler


class _FakeProvider:
    def chat(self, context, system_prompt=None):
        return "I found an older Canvas page, but it does not answer the new mounting question yet."


class _FakeRouter:
    def __init__(self):
        self.provider = _FakeProvider()


class CanvasDuplicateGuardTests(unittest.TestCase):
    def test_completion_guard_avoids_artifact_loop_when_user_complains_about_tool_churn(self):
        handler = ChatHandler.__new__(ChatHandler)
        record = {
            "query": "search amazon using serpapi for a good birthday gift for 23 year old male who likes star wars, product can be between $100-$300",
            "raw_llm_response": "Saved results to canvas.",
        }
        note = "horrible, max out tool turns, should have had enough info after a few serpapi calls, used canvas 3 times, this is completly wrong."

        strategy = handler._classify_completion_guard_strategy(record, note)

        self.assertEqual(strategy["family"], "minimal_repair")
        self.assertIn("canvas", strategy["avoid_tools"])
        self.assertIn("answer directly", strategy["completion_hint"])

    def test_completion_guard_prefers_verification_when_canvas_is_only_context(self):
        handler = ChatHandler.__new__(ChatHandler)
        record = {
            "query": "what size pipe or pole would i use to mount it? also is there a amazon product I can also purchase with a wall mount or right angle adjustable post mount?",
            "raw_llm_response": "",
        }
        note = "The canvas update alone does not answer the user's questions."

        strategy = handler._classify_completion_guard_strategy(record, note)

        self.assertEqual(strategy["family"], "verification_repair")
        self.assertIn("brave_search", strategy["preferred_tools"])

    def test_duplicate_prevention_does_not_repeat_generic_canvas_confirmation(self):
        orchestrator = Orchestrator.__new__(Orchestrator)
        orchestrator.router = _FakeRouter()
        orchestrator._extract_useful_data = lambda data: ""

        result = orchestrator._synthesize_duplicate_prevented_response(
            user_query="what size pipe or pole would i use to mount it?",
            tools_used=["search_memory", "canvas"],
            accumulated_data={"canvas": {"title": "Ambient Weather WS-2902 Integration Options"}},
            conversation_context=[
                {
                    "tool": "canvas",
                    "speech": "Updated 'Ambient Weather WS-2902 Integration Options' in your canvas.",
                    "result": {
                        "speech": "Updated 'Ambient Weather WS-2902 Integration Options' in your canvas.",
                        "data": {
                            "title": "Ambient Weather WS-2902 Integration Options",
                            "content": "# Ambient Weather WS-2902 API & Integration Guide"
                        }
                    }
                }
            ]
        )

        self.assertNotIn("Updated 'Ambient Weather WS-2902 Integration Options' in your canvas.", result)
        self.assertTrue(
            "does not answer" in result or "repeat-tool safeguard" in result,
            result
        )


if __name__ == "__main__":
    unittest.main()
