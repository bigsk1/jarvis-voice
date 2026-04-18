#!/usr/bin/env python3
"""
Regression tests for intelligence-layer handling of provider-native server-side tools.

Run:
    python3 tests/test_intelligence_server_side_tools.py
"""

import sys
import types
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

fake_numpy = types.ModuleType("numpy")
fake_numpy.ndarray = list
sys.modules.setdefault("numpy", fake_numpy)

from intelligence_hooks import _evaluate_insight_helpfulness, normalize_server_side_tools_for_reflection
from intelligence import should_suppress_preferred_tool_for_native_search


class IntelligenceServerSideToolsTests(unittest.TestCase):
    def test_normalize_server_side_tools_for_reflection(self):
        normalized = normalize_server_side_tools_for_reflection({
            "SERVER_SIDE_TOOL_X_SEARCH": 2,
            "SERVER_SIDE_TOOL_VIEW_IMAGE": 1,
            "SERVER_SIDE_TOOL_CODE_INTERPRETER": 1,
        })

        self.assertEqual(
            normalized,
            ["native:x_search", "native:x_search", "native:view_image", "native:code_interpreter"]
        )

    def test_suppresses_external_search_preference_when_native_search_was_used(self):
        experience = {
            "final_tool": "mcp_brave_search_brave_web_search",
            "raw_data": '{"context":{"provider_native_tools_used":["native:x_search"]}}',
        }
        reflection = {
            "preferred_tool": "mcp_brave_search_brave_web_search",
            "insight_summary": "Use X-targeted search first for recent X media lookups.",
        }

        self.assertTrue(
            should_suppress_preferred_tool_for_native_search(reflection, experience)
        )

    def test_does_not_suppress_non_search_tool_preference(self):
        experience = {
            "final_tool": "canvas",
            "raw_data": '{"context":{"provider_native_tools_used":["native:web_search"]}}',
        }
        reflection = {
            "preferred_tool": "canvas",
            "insight_summary": "Save the final comparison to canvas after research.",
        }

        self.assertFalse(
            should_suppress_preferred_tool_for_native_search(reflection, experience)
        )

    def test_positive_insight_requires_preferred_tool_usage_when_present(self):
        insight = {
            "constraint_type": "positive",
            "preferred_tools": {"mcp_brave_search_brave_news_search": 1.0},
        }

        self.assertFalse(
            _evaluate_insight_helpfulness(
                insight,
                tools_used=["mcp_brave_search_brave_web_search"],
                outcome_success=True,
                result={"ok": True},
            )
        )

    def test_positive_insight_success_with_preferred_tool_is_helpful(self):
        insight = {
            "constraint_type": "positive",
            "preferred_tools": {"mcp_brave_search_brave_web_search": 1.0},
        }

        self.assertTrue(
            _evaluate_insight_helpfulness(
                insight,
                tools_used=["mcp_brave_search_brave_web_search"],
                outcome_success=True,
                result={
                    "ok": True,
                    "tool_trace": [
                        {"tool": "mcp_brave_search_brave_web_search", "ok": True},
                    ],
                },
            )
        )

    def test_positive_insight_with_preferred_tool_failure_is_not_helpful_after_recovery(self):
        insight = {
            "constraint_type": "positive",
            "preferred_tools": {"mcp_brave_search_brave_news_search": 1.0},
        }

        self.assertFalse(
            _evaluate_insight_helpfulness(
                insight,
                tools_used=[
                    "mcp_brave_search_brave_news_search",
                    "mcp_brave_search_brave_web_search",
                ],
                outcome_success=True,
                result={
                    "ok": True,
                    "tool_trace": [
                        {
                            "tool": "mcp_brave_search_brave_news_search",
                            "ok": False,
                            "error": "Invalid arguments for tool brave_news_search",
                        },
                        {"tool": "mcp_brave_search_brave_web_search", "ok": True},
                    ],
                },
            )
        )


if __name__ == "__main__":
    unittest.main()
