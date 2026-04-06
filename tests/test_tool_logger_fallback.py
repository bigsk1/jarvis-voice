#!/usr/bin/env python3
"""
Regression tests for tool log fallback embedding metadata.

Run:
    python3 tests/test_tool_logger_fallback.py
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from tool_logger import ToolLogger


class ToolLoggerFallbackTests(unittest.TestCase):
    def test_log_tool_call_persists_fallback_embeddings_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = ToolLogger(log_dir=tmpdir)
            logger.log_tool_call(
                tool_name="semantic_recall",
                arguments={"query": "vpn network"},
                result={
                    "ok": True,
                    "speech": "Found 1 related memory",
                    "fallback_embeddings": True,
                },
                duration_ms=42.0,
                mode="cloud",
            )

            entries = logger.get_recent_logs(limit=1)
            self.assertEqual(len(entries), 1)
            self.assertTrue(entries[0]["fallback_embeddings"])

            raw_entry = json.loads(Path(logger.log_file).read_text().strip())
            self.assertTrue(raw_entry["fallback_embeddings"])


if __name__ == "__main__":
    unittest.main()
