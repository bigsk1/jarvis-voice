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
from zoneinfo import ZoneInfo

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

class _DuplicateProvider:
    def __init__(self):
        self.context = ""

    def chat(self, context, system_prompt=None):
        self.context = context
        return "The transcript says Opus 4.7 is presented as a strong coding and multimodal upgrade, with pricing discussed as expensive relative to cheaper models."


class _FakeRouter:
    def __init__(self):
        self.provider = _FakeProvider()


class _SummaryExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, tool_name, args, skip_permission_check=False):
        self.calls.append((tool_name, args, skip_permission_check))
        return {
            "ok": True,
            "speech": "Summary: Opus 4.7 improves coding and multimodal work.",
            "data": {
                "summary": "Opus 4.7 improves coding and multimodal work, with pricing tradeoffs called out.",
                "summary_meta": {"summary_method": "llm", "llm_used": True},
                "source": {"stash_ref": args["stash_ref"]},
            },
        }


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

    def test_duplicate_prevention_ignores_duplicate_guard_speech(self):
        orchestrator = Orchestrator.__new__(Orchestrator)
        provider = _DuplicateProvider()
        orchestrator.router = types.SimpleNamespace(provider=provider)

        result = orchestrator._synthesize_duplicate_prevented_response(
            user_query="analyze and recap this transcript",
            tools_used=["youtube_transcript", "stash"],
            accumulated_data={
                "youtube_transcript": {
                    "video_title": "Claude Opus 4.7 Is INSANE - Is This the Best Model Yet",
                    "srt_saved": True,
                    "md_saved": True,
                },
                "stash": {
                    "name": "transcript.md",
                    "ref": "stash://space_example/f_example",
                    "content": "Claude Opus 4.7 was released. It improves coding, vision, and agentic work. Pricing is $5 input and $25 output per million tokens.",
                },
            },
            conversation_context=[
                {
                    "tool": "stash",
                    "speech": "Read transcript.md",
                    "result": {"ok": True, "speech": "Read transcript.md", "data": {}},
                },
                {
                    "tool": "duplicate_guard",
                    "speech": "Blocked duplicate tool call for stash.",
                    "result": {
                        "ok": False,
                        "speech": "Blocked duplicate tool call for stash.",
                        "error": "Duplicate guard blocked tool 'stash' (exact duplicate).",
                    },
                },
            ],
        )

        self.assertNotIn("Blocked duplicate tool call", result)
        self.assertIn("Opus 4.7", result)
        self.assertIn("content_excerpt", provider.context)

    def test_turn_context_hints_text_summarizer_for_truncated_stash_text(self):
        orchestrator = Orchestrator.__new__(Orchestrator)
        orchestrator.timezone = ZoneInfo("America/Los_Angeles")

        long_content = "Claude Opus 4.7 improves coding and multimodal work. " * 120
        context = orchestrator._build_turn_context(
            "analyze and recap this transcript",
            [
                {
                    "tool": "stash",
                    "arguments": {
                        "action": "read",
                        "space_id": "space_example",
                        "file_id": "f_example",
                        "mode": "text",
                    },
                    "result": {
                        "ok": True,
                        "speech": "Read transcript.md",
                        "data": {
                            "ref": "stash://space_example/f_example",
                            "name": "transcript.md",
                            "content": long_content,
                        },
                    },
                    "meta": {},
                }
            ],
        )

        self.assertIn("Do NOT call stash.read again", context)
        self.assertIn("text_summarizer", context)
        self.assertIn("stash://space_example/f_example", context)

    def test_auto_summarizes_long_stash_read_with_text_summarizer(self):
        orchestrator = Orchestrator.__new__(Orchestrator)
        orchestrator.executor = _SummaryExecutor()
        orchestrator.progress_callback = None

        summary_args, summary_result = orchestrator._maybe_auto_summarize_stash_result(
            {
                "ok": True,
                "data": {
                    "ref": "stash://space_example/f_example",
                    "name": "transcript.md",
                    "content": "Claude Opus 4.7 improves coding and multimodal work. " * 120,
                },
            },
            {"action": "read"},
            "analyze and recap this transcript",
            {},
        )

        self.assertIsNotNone(summary_result)
        self.assertEqual(summary_args["stash_ref"], "stash://space_example/f_example")
        self.assertEqual(summary_args["operation"], "summarize")
        self.assertEqual(orchestrator.executor.calls[0][0], "text_summarizer")
        self.assertTrue(orchestrator.executor.calls[0][2])

    def test_extract_useful_data_prefers_text_summary_over_stash_excerpt(self):
        orchestrator = Orchestrator.__new__(Orchestrator)
        long_content = "middle content that should not be injected into synthesis. " * 200

        extracted = orchestrator._extract_useful_data({
            "stash": {
                "name": "transcript.md",
                "ref": "stash://space_example/f_example",
                "content": long_content,
            },
            "text_summarizer": {
                "summary": "The transcript says Opus 4.7 improves coding, vision, and agentic workflows.",
                "summary_meta": {"summary_method": "llm", "llm_used": True},
                "source": {"stash_ref": "stash://space_example/f_example"},
            },
        })

        self.assertIn("content_summary_available", extracted)
        self.assertIn("The transcript says Opus 4.7", extracted)
        self.assertNotIn("middle omitted for fallback synthesis", extracted)


if __name__ == "__main__":
    unittest.main()
