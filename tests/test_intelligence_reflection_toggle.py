#!/usr/bin/env python3
"""Web chat can skip reflection_queue inserts without dropping the experience."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

import intelligence_hooks
from intelligence import IntelligenceLayer
from orchestrator_v2 import Orchestrator


class ReflectionQueueToggleTests(unittest.TestCase):
    def setUp(self):
        logger_patch = patch("intelligence.get_intel_logger")
        logger_patch.start()
        self.addCleanup(logger_patch.stop)

    def _intel(self, tmpdir: str) -> IntelligenceLayer:
        intel = IntelligenceLayer(
            str(Path(tmpdir) / "intel.db"),
            load_runtime_config=False,
        )
        intel._get_embedding = lambda text, **kwargs: np.array([1.0, 0.5])
        intel._get_persistable_embedding = intel._get_embedding
        return intel

    def _orchestrator(self, queue_enabled: bool) -> Orchestrator:
        orchestrator = Orchestrator.__new__(Orchestrator)
        orchestrator.learning_enabled = True
        orchestrator.reflection_queue_enabled = queue_enabled
        orchestrator.background_context = None
        orchestrator.web_conversation_id = None
        orchestrator.session_id = None
        orchestrator._previous_experience_id_for_correction = None
        return orchestrator

    def _record(self, intel: IntelligenceLayer, queue_enabled: bool) -> int:
        orchestrator = self._orchestrator(queue_enabled)
        with patch.object(intelligence_hooks, "_get_intel", return_value=intel):
            return orchestrator._record_learning_experience(
                "what time is it",
                ["get_time"],
                {"ok": True, "speech": "noon", "raw_llm_response": "noon"},
                [],
            )

    def test_disabled_toggle_keeps_experience_and_skips_queue(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            intel = self._intel(tmpdir)
            exp_id = self._record(intel, queue_enabled=False)

            self.assertGreater(exp_id, 0)
            self.assertEqual(
                intel.conn.execute("SELECT COUNT(*) FROM experiences").fetchone()[0],
                1,
            )
            self.assertEqual(
                intel.conn.execute("SELECT COUNT(*) FROM reflection_queue").fetchone()[0],
                0,
            )

    def test_enabled_toggle_still_queues_reflection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            intel = self._intel(tmpdir)
            exp_id = self._record(intel, queue_enabled=True)

            self.assertGreater(exp_id, 0)
            row = intel.conn.execute(
                "SELECT experience_id FROM reflection_queue"
            ).fetchone()
            self.assertEqual(row[0], exp_id)


if __name__ == "__main__":
    unittest.main()
