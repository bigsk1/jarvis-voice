#!/usr/bin/env python3
"""
Regression tests for intelligence-layer handling of provider-native server-side tools.

Run:
    python3 tests/test_intelligence_server_side_tools.py
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from intelligence_hooks import normalize_server_side_tools_for_reflection


class IntelligenceServerSideToolsTests(unittest.TestCase):
    def test_normalize_server_side_tools_for_reflection(self):
        normalized = normalize_server_side_tools_for_reflection({
            "SERVER_SIDE_TOOL_X_SEARCH": 2,
            "SERVER_SIDE_TOOL_CODE_INTERPRETER": 1,
        })

        self.assertEqual(
            normalized,
            ["native:x_search", "native:x_search", "native:code_interpreter"]
        )


if __name__ == "__main__":
    unittest.main()
