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

from router_v2 import ProviderRouteInput  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
