#!/usr/bin/env python3
"""
Regression tests for orchestrator usage passthrough decisions.

Run:
    python3 tests/test_orchestrator_usage_passthrough.py
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

from orchestrator_v2 import Orchestrator


class OrchestratorUsagePassthroughTests(unittest.TestCase):
    def test_has_usage_data_when_only_tokens_are_present(self):
        usage = {
            "input_tokens": 1200,
            "output_tokens": 45,
            "cost_usd": 0.0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "cache_savings_usd": 0.0,
            "server_side_tools": {},
        }
        self.assertTrue(Orchestrator._has_usage_data(usage))

    def test_has_usage_data_when_only_server_side_tools_are_present(self):
        usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "cache_savings_usd": 0.0,
            "server_side_tools": {"SERVER_SIDE_TOOL_X_SEARCH": 2},
        }
        self.assertTrue(Orchestrator._has_usage_data(usage))

    def test_has_usage_data_false_for_empty_usage(self):
        usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "cache_savings_usd": 0.0,
            "server_side_tools": {},
        }
        self.assertFalse(Orchestrator._has_usage_data(usage))


if __name__ == "__main__":
    unittest.main()
