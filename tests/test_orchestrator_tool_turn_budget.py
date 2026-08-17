#!/usr/bin/env python3
"""Regression tests for in-flight tool turn budgets."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

from orchestrator_v2 import Orchestrator


class FakeExecutor:
    def __init__(self, fail_on_calls=None):
        self.calls = 0
        self.fail_on_calls = set(fail_on_calls or [])

    def set_excluded_tools(self, _tools):
        pass

    def execute(self, tool_name, arguments):
        self.calls += 1
        if self.calls not in self.fail_on_calls:
            return {
                "ok": True,
                "speech": f"{tool_name} succeeded.",
                "data": {"call": self.calls},
            }
        return {
            "ok": False,
            "error": "SerpApi error: Yelp hasn't returned any results for this query.",
            "speech": "No Yelp results.",
            "data": {},
        }


class FakeRouter:
    provider_type = "test"
    model_name = "fake-model"
    system_prompt_version = "test"
    provider = None

    def __init__(self, tool_name="serpapi_yelp_search"):
        self.calls = 0
        self.tool_name = tool_name

    def route(self, *_args, **_kwargs):
        self.calls += 1
        return {
            "intent": "tool",
            "tool_name": self.tool_name,
            "arguments": {"find_desc": f"arcade games kids {self.calls}"},
            "usage_info": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        }


class FakeStatusUpdater:
    def reset(self):
        pass

    def set_turn(self, _turn):
        pass

    def update(self, **_kwargs):
        pass

    def update_error(self, **_kwargs):
        pass

    def mark_complete(self):
        pass


class ToolTurnBudgetTests(unittest.TestCase):
    def _build_orchestrator(self, *, fail_on_calls, tool_name="serpapi_yelp_search"):
        orchestrator = Orchestrator.__new__(Orchestrator)
        orchestrator.executor = FakeExecutor(fail_on_calls=fail_on_calls)
        orchestrator.router = FakeRouter(tool_name=tool_name)
        orchestrator.status_updater = FakeStatusUpdater()
        orchestrator.max_retries = 1
        orchestrator.timezone = ZoneInfo("America/Los_Angeles")
        orchestrator.auto_context_enabled = False
        orchestrator._last_experience_id = None
        orchestrator.session_id = "test-session"
        orchestrator.web_conversation_id = "test-conv"
        orchestrator.progress_callback = None
        orchestrator.cancel_check = None
        orchestrator.learning_enabled = False

        orchestrator._try_workflow = lambda _transcript: None
        orchestrator._get_relevant_memories_bundle = lambda _transcript: {"context": "", "meta": {}}
        orchestrator._get_learning_insights = lambda _transcript, _available_tools: ("", [])
        orchestrator._format_max_turns_summary = lambda *_args: "Reached max turns."
        orchestrator._log_conversation = lambda *_args, **_kwargs: None
        orchestrator._maybe_collect_feedback = lambda result, _transcript: result
        return orchestrator

    def _run_with_max_turns_and_retries(self, orchestrator, max_turns, max_retries):
        orchestrator.max_retries = max_retries

        def fake_get_int(key, default=0):
            return max_turns if key == "MAX_TOOL_TURNS" else default

        with patch("orchestrator_v2.get_int", side_effect=fake_get_int):
            result = orchestrator.process("find local activities")
        return result

    def _run_with_max_turns(self, orchestrator, max_turns):
        return self._run_with_max_turns_and_retries(orchestrator, max_turns, orchestrator.max_retries)

    def test_tool_failure_retry_does_not_reset_max_tool_turn_budget(self):
        orchestrator = self._build_orchestrator(fail_on_calls={1})

        result = self._run_with_max_turns(orchestrator, 1)

        self.assertTrue(result["max_turns_reached"])
        self.assertEqual(orchestrator.router.calls, 1)
        self.assertEqual(orchestrator.executor.calls, 1)
        self.assertEqual(result["tool_trace"][0]["tool"], "serpapi_yelp_search")
        self.assertFalse(result["tool_trace"][0]["ok"])

    def test_web_tool_hint_wrapper_is_not_used_for_memory_retrieval(self):
        orchestrator = self._build_orchestrator(fail_on_calls=set())
        memory_queries = []
        intelligence_queries = []
        orchestrator._get_relevant_memories_bundle = lambda query: (
            memory_queries.append(query) or {"context": "", "meta": {}}
        )
        orchestrator._get_learning_insights = lambda query, _available_tools: (
            intelligence_queries.append(query) or ("", [])
        )
        prompt = (
            "[CONTEXT - Tool preference for this request]\n\n"
            "Selected tool hints: canvas.\n\n"
            "[END CONTEXT]\n\n"
            "User's request: Find local activities"
        )

        with patch(
            "orchestrator_v2.get_int",
            side_effect=lambda key, default=0: 1 if key == "MAX_TOOL_TURNS" else default,
        ):
            orchestrator.process(prompt)

        self.assertEqual(memory_queries, ["Find local activities"])
        self.assertEqual(intelligence_queries, ["Find local activities"])

    def test_mid_budget_failure_retry_uses_only_remaining_turns(self):
        orchestrator = self._build_orchestrator(fail_on_calls={3})

        result = self._run_with_max_turns(orchestrator, 5)

        self.assertTrue(result["max_turns_reached"])
        self.assertEqual(orchestrator.router.calls, 5)
        self.assertEqual(orchestrator.executor.calls, 5)
        self.assertEqual([entry["ok"] for entry in result["tool_trace"]], [True, True, False, True, True])

    def test_last_turn_failure_retry_has_no_extra_router_turn(self):
        orchestrator = self._build_orchestrator(fail_on_calls={3})

        result = self._run_with_max_turns(orchestrator, 3)

        self.assertTrue(result["max_turns_reached"])
        self.assertEqual(orchestrator.router.calls, 3)
        self.assertEqual(orchestrator.executor.calls, 3)
        self.assertEqual([entry["ok"] for entry in result["tool_trace"]], [True, True, False])

    def test_late_terminal_failure_preserves_progress_summary(self):
        orchestrator = self._build_orchestrator(fail_on_calls={3})

        result = self._run_with_max_turns_and_retries(orchestrator, 5, 0)

        self.assertFalse(result["ok"])
        self.assertEqual(orchestrator.router.calls, 3)
        self.assertEqual(orchestrator.executor.calls, 3)
        self.assertIn("Reached max turns.", result["speech"])
        self.assertIn("One final step failed", result["speech"])
        self.assertIn("Serpapi yelp search failed", result["speech"])
        self.assertEqual(result["tools_used"], ["serpapi_yelp_search", "serpapi_yelp_search"])
        self.assertEqual(result["usage"]["model_calls"], 3)
        self.assertEqual(result["usage"]["total_tokens"], 6)

    def test_single_call_terminal_failure_preserves_usage(self):
        orchestrator = self._build_orchestrator(
            fail_on_calls={1},
            tool_name="generate_image",
        )

        result = self._run_with_max_turns_and_retries(orchestrator, 5, 1)

        self.assertFalse(result["ok"])
        self.assertTrue(result["terminal_failure"])
        self.assertEqual(result["tool_name"], "generate_image")
        self.assertEqual(result["usage"]["model_calls"], 1)
        self.assertEqual(result["usage"]["total_tokens"], 2)


if __name__ == "__main__":
    unittest.main()
