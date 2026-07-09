#!/usr/bin/env python3
"""Regression tests for Tool RAG final schema limits."""

import os
import logging
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

from router_v2 import (  # noqa: E402
    _cap_tool_names_for_schema,
    _log_tool_rag_signal_meta,
    _resolve_tool_rag_limit,
)


class ToolRagLimitTests(unittest.TestCase):
    def test_final_cap_prioritizes_explicit_tool_and_discovery(self):
        names = [
            "search_memory",
            "update_memory",
            "semantic_recall",
            "remember",
            "canvas",
            "tool_search",
            "generate_video",
            "stash",
        ]

        capped = _cap_tool_names_for_schema(
            names,
            3,
            positive_tools={"canvas"},
            ghost_tools={
                "search_memory",
                "update_memory",
                "semantic_recall",
                "remember",
                "canvas",
                "tool_search",
            },
        )

        self.assertEqual(capped, ["canvas", "tool_search", "generate_video"])

    def test_mode_limits_are_configurable(self):
        with patch.dict(os.environ, {
            "JARVIS_OVERRIDE_CLOUD_TOOL_RAG_LIMIT": "9",
            "JARVIS_OVERRIDE_LOCAL_TOOL_RAG_LIMIT": "4",
        }):
            self.assertEqual(_resolve_tool_rag_limit("cloud"), 9)
            self.assertEqual(_resolve_tool_rag_limit("local"), 4)

    def test_local_default_covers_default_ghosts_plus_discovery(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_resolve_tool_rag_limit("local"), 6)

    def test_request_override_wins_for_one_turn(self):
        with patch.dict(os.environ, {"JARVIS_OVERRIDE_CLOUD_TOOL_RAG_LIMIT": "15"}):
            self.assertEqual(_resolve_tool_rag_limit("cloud", override=3), 3)

    def test_request_override_is_bounded(self):
        self.assertEqual(_resolve_tool_rag_limit("cloud", override=999), 50)

    def test_cap_only_signal_meta_is_logged(self):
        logger = logging.getLogger("test.tool_rag_limits")
        with self.assertLogs(logger, level="INFO") as captured:
            _log_tool_rag_signal_meta(
                logger,
                {"capped_to": ["3"], "dropped_by_cap": ["remember"]},
            )

        self.assertIn("dropped_by_cap", "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
