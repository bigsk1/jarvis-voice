#!/usr/bin/env python3
"""OpenAI Responses in-flight continuation shape tests (no live API calls)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

from router_v2 import ProviderRouteInput, _provider_continuation_meta  # noqa: E402


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
