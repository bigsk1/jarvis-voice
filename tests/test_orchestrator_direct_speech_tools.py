#!/usr/bin/env python3
"""
Regression tests for authoritative tool speech passthrough.

Run:
    python3 tests/test_orchestrator_direct_speech_tools.py
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

from orchestrator_v2 import Orchestrator


class OrchestratorDirectSpeechToolTests(unittest.TestCase):
    def test_create_reminder_uses_direct_speech(self):
        self.assertIn("create_reminder", Orchestrator.DIRECT_SPEECH_TOOLS)


if __name__ == "__main__":
    unittest.main()
