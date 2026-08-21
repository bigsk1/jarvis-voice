#!/usr/bin/env python3
"""Regression tests for feedback handling of OpenAI hosted search."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

import feedback  # noqa: E402


class _PromptCaptureProvider:
    def __init__(self):
        self.prompt = ""

    def chat(self, prompt, system_prompt=None):
        self.prompt = prompt
        return '{"rating": 5, "summary": "ok", "issues": [], "suggestions": []}'


class FeedbackOpenAINativeSearchTests(unittest.TestCase):
    def _collector(self, provider):
        collector = feedback.FeedbackCollector.__new__(feedback.FeedbackCollector)
        collector.mode = "cloud"
        collector.provider_name = "openai"
        collector.model_name = "test-model"
        collector.provider = provider
        return collector

    def test_openai_responses_web_search_marks_native_search_enabled(self):
        provider = _PromptCaptureProvider()
        collector = self._collector(provider)

        def fake_config(key, default=""):
            return {
                "LLM_PROVIDER": "openai",
                "OPENAI_API_MODE": "responses",
                "OPENAI_RESPONSES_SERVER_SIDE_TOOLS": "true",
                "OPENAI_RESPONSES_WEB_SEARCH": "true",
            }.get(key, default)

        with patch.object(feedback, "get_config_value", side_effect=fake_config), \
             patch.object(collector, "_log_feedback"):
            collector.collect(
                query="what happened today?",
                result={"ok": True, "speech": "Found it.", "raw_llm_response": "Found it."},
                tools_used=[],
                config_context="Mode: cloud",
            )

        self.assertIn("NATIVE SEARCH CHECK - READ FIRST: 🟢 ENABLED", provider.prompt)
        self.assertIn("HAS BUILT-IN WEB SEARCH", provider.prompt)

    def test_openai_server_side_metadata_marks_native_search_enabled(self):
        provider = _PromptCaptureProvider()
        collector = self._collector(provider)

        def fake_config(key, default=""):
            return {
                "LLM_PROVIDER": "openai",
                "OPENAI_API_MODE": "chat",
                "OPENAI_RESPONSES_SERVER_SIDE_TOOLS": "false",
                "OPENAI_RESPONSES_WEB_SEARCH": "false",
            }.get(key, default)

        with patch.object(feedback, "get_config_value", side_effect=fake_config), \
             patch.object(collector, "_log_feedback"):
            collector.collect(
                query="what happened today?",
                result={
                    "ok": True,
                    "speech": "Found it.",
                    "raw_llm_response": "Found it.",
                    "server_side_tools": {"SERVER_SIDE_TOOL_WEB_SEARCH": 1},
                },
                tools_used=[],
                config_context="Mode: cloud",
            )

        self.assertIn("NATIVE SEARCH CHECK - READ FIRST: 🟢 ENABLED", provider.prompt)

    def test_workflow_grading_receives_recipe_attribution_context(self):
        provider = _PromptCaptureProvider()
        collector = self._collector(provider)

        with patch.object(feedback, "get_config_value", return_value=""), \
             patch.object(collector, "_log_feedback"):
            collector.collect(
                query="research AI agents",
                result={
                    "ok": True,
                    "speech": "Research report complete.",
                    "tools_used": ["workflow", "workflow"],
                    "data": {
                        "workflow": [
                            {"action": "search"},
                            {
                                "action": "run",
                                "workflow_id": "research_report",
                                "workflow_started": True,
                                "workflow_completed": True,
                                "component_tools_used": [
                                    "search_docs",
                                    "canvas",
                                ],
                            },
                        ]
                    },
                },
                tools_used=["workflow", "workflow"],
                config_context="Mode: cloud",
            )

        self.assertIn('"selected_workflow_id": "research_report"', provider.prompt)
        self.assertIn(
            "rate discovery and selection of the specific workflow",
            provider.prompt,
        )
        self.assertIn(
            "Component order is owned by the deterministic workflow recipe",
            provider.prompt,
        )


if __name__ == "__main__":
    unittest.main()
