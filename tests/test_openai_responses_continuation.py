#!/usr/bin/env python3
"""OpenAI Responses in-flight continuation shape tests (no live API calls)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

from router_v2 import ProviderRouteInput, _provider_continuation_meta  # noqa: E402


class _OpenAIContinuationRouter:
    provider_type = "openai"
    model_name = "gpt-5.4-nano"
    system_prompt_version = "test"
    provider = None

    def __init__(self):
        self.calls = []

    def route(self, payload, **_kwargs):
        self.calls.append(payload)
        if len(self.calls) == 1:
            return {
                "intent": "tool",
                "tool_name": "tool_search",
                "arguments": {"query": "brave local search web search events", "limit": 6},
                "usage_info": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                "response_id": "resp_1",
                "tool_call_id": "call_1",
                "response_model": self.model_name,
            }
        return {
            "intent": "qa",
            "text_response": "done",
            "usage_info": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        }


class _ToolSearchExecutor:
    def set_excluded_tools(self, _tools):
        pass

    def execute(self, tool_name, _arguments):
        self.tool_name = tool_name
        return {
            "ok": True,
            "speech": "I found 2 matching tools: mcp_brave_search_brave_local_search, serpapi_maps_search.",
            "data": {
                "selected_tool_hints": [
                    "mcp_brave_search_brave_local_search",
                    "serpapi_maps_search",
                ],
                "matches": [],
            },
        }


class _StatusUpdater:
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


class OpenAIContinuationShapeTests(unittest.TestCase):
    def test_provider_route_carries_structural_outputs(self) -> None:
        items = [
            {"type": "function_call_output", "call_id": "call_1", "output": "{}"},
            {"role": "user", "content": "delta"},
        ]
        pri = ProviderRouteInput(
            tool_retrieval_query="look up btc",
            messages=[],
            system_prompt=None,
            previous_response_id="resp_xyz",
            continuation_mode="responses_with_delta",
            responses_continuation_input=items,
        )
        self.assertEqual(pri.previous_response_id, "resp_xyz")
        self.assertEqual(len(pri.responses_continuation_input or []), 2)

    def test_orchestrator_builds_openai_route_input(self) -> None:
        from orchestrator_v2 import Orchestrator  # noqa: E402

        orch = Orchestrator.__new__(Orchestrator)

        orch.timezone = __import__(
            "zoneinfo",
        ).ZoneInfo(
            "America/Los_Angeles",
        )

        orch.router = mock.MagicMock()
        orch.router.model_name = "gpt-5-nano"

        def _truthy_setting(name: str, default: bool = False) -> bool:
            return name == "OPENAI_RESPONSES_CONTINUATION_DELTA_MESSAGE"

        with mock.patch.object(orch, "_config_bool", side_effect=_truthy_setting):
            route_input = orch._build_openai_responses_route_input(
                retrieval_query="compact query",
                continuation={
                    "response_id": "resp_42",
                    "tool_call_id": "call_z",
                    "result_message": "Jarvis ok",
                },
            )
        self.assertIsInstance(route_input, ProviderRouteInput)
        payload = route_input.responses_continuation_input or []
        self.assertGreaterEqual(len(payload), 2)
        self.assertEqual(payload[0]["type"], "function_call_output")

    def test_orchestrator_keeps_openai_shape_with_turn_notice_when_delta_off(self) -> None:
        from orchestrator_v2 import Orchestrator  # noqa: E402

        orch = Orchestrator.__new__(Orchestrator)

        with mock.patch.object(orch, "_config_bool", return_value=False):
            route_input = orch._build_openai_responses_route_input(
                retrieval_query="compact query",
                continuation={
                    "response_id": "resp_42",
                    "tool_call_id": "call_z",
                    "result_message": "Jarvis ok",
                },
                turn_notice="[TURN 8/12 - 5 turns remaining. Prioritize finishing.]",
            )

        payload = route_input.responses_continuation_input or []
        self.assertEqual(route_input.continuation_mode, "responses_structural")
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["type"], "function_call_output")
        self.assertIn("[TURN 8/12 - 5 turns remaining", payload[0]["output"])

    def test_orchestrator_adds_openai_delta_message_when_enabled(self) -> None:
        from orchestrator_v2 import Orchestrator  # noqa: E402

        orch = Orchestrator.__new__(Orchestrator)

        with mock.patch.object(orch, "_config_bool", return_value=True):
            route_input = orch._build_openai_responses_route_input(
                retrieval_query="compact query",
                continuation={
                    "response_id": "resp_42",
                    "tool_call_id": "call_z",
                    "result_message": "Jarvis ok",
                },
                turn_notice="[TURN 8/12 - 5 turns remaining. Prioritize finishing.]",
            )

        payload = route_input.responses_continuation_input or []
        self.assertEqual(route_input.continuation_mode, "responses_with_delta")
        self.assertEqual(payload[1]["role"], "user")
        self.assertNotIn("[TURN 8/12", payload[0]["output"])
        self.assertIn("[TURN 8/12 - 5 turns remaining", payload[1]["content"])
        self.assertIn("Continue the original Jarvis request", payload[1]["content"])

    def test_openai_structural_continuation_tool_rag_sees_tool_search_hints(self) -> None:
        from orchestrator_v2 import Orchestrator  # noqa: E402

        orch = Orchestrator.__new__(Orchestrator)
        orch.executor = _ToolSearchExecutor()
        orch.router = _OpenAIContinuationRouter()
        orch.status_updater = _StatusUpdater()
        orch.max_retries = 0
        orch.timezone = ZoneInfo("America/Los_Angeles")
        orch.auto_context_enabled = False
        orch._last_experience_id = None
        orch.session_id = "test-session"
        orch.web_conversation_id = "test-conv"
        orch.progress_callback = None
        orch.cancel_check = None
        orch.learning_enabled = False

        orch._try_workflow = lambda _transcript: None
        orch._get_relevant_memories_bundle = lambda _transcript: {"context": "", "meta": {}}
        orch._get_learning_insights = lambda _transcript, _available_tools: ("", [])
        orch._log_conversation = lambda *_args, **_kwargs: None
        orch._maybe_collect_feedback = lambda result, _transcript: result
        orch._openai_responses_tracking_enabled = lambda: True
        orch._openai_native_continuation_allowed = lambda: True

        def fake_get_int(key, default=0):
            return 2 if key == "MAX_TOOL_TURNS" else default

        with mock.patch("orchestrator_v2.get_int", side_effect=fake_get_int), \
             mock.patch.object(orch, "_config_bool", return_value=False):
            result = orch.process("find local activities")

        self.assertTrue(result["ok"])
        self.assertEqual(len(orch.router.calls), 2)
        continuation_payload = orch.router.calls[1]
        self.assertIsInstance(continuation_payload, ProviderRouteInput)
        self.assertIn(
            "Selected tool hints: mcp_brave_search_brave_local_search, serpapi_maps_search.",
            continuation_payload.tool_retrieval_query,
        )
        self.assertEqual(continuation_payload.messages, [])
        self.assertEqual(
            continuation_payload.responses_continuation_input[0]["type"],
            "function_call_output",
        )

    def test_turn_limit_notice_has_light_and_near_limit_forms(self) -> None:
        from orchestrator_v2 import Orchestrator  # noqa: E402

        self.assertIsNone(Orchestrator._build_turn_limit_notice(0, 12))
        self.assertEqual(Orchestrator._build_turn_limit_notice(2, 12), "[Turn 3/12]")
        self.assertIn(
            "5 turns remaining",
            Orchestrator._build_turn_limit_notice(7, 12),
        )

    def test_openai_continuation_meta_does_not_emit_xai_aliases(self) -> None:
        meta = _provider_continuation_meta(
            provider_type="openai",
            continuation_mode="responses_structural",
            continuation_fallback_reason=None,
            previous_response_id="resp_42",
            provider_shape={"count": 0, "roles": {}},
            responses_continuation_payload_items=1,
        )

        self.assertEqual(meta["provider_continuation_mode"], "responses_structural")
        self.assertTrue(meta["provider_previous_response_id_used"])
        self.assertEqual(meta["openai_responses_continuation_mode"], "responses_structural")
        self.assertNotIn("xai_previous_response_id_used", meta)

    def test_xai_continuation_meta_keeps_xai_aliases(self) -> None:
        meta = _provider_continuation_meta(
            provider_type="xai",
            continuation_mode="stored_structural",
            continuation_fallback_reason=None,
            previous_response_id="resp_42",
            provider_shape={"count": 1, "roles": {"tool": 1}},
            responses_continuation_payload_items=0,
        )

        self.assertEqual(meta["provider_continuation_mode"], "stored_structural")
        self.assertTrue(meta["xai_previous_response_id_used"])
        self.assertNotIn("openai_responses_continuation_payload_items", meta)
        self.assertNotIn("openai_responses_previous_id_used", meta)


if __name__ == "__main__":
    unittest.main()
