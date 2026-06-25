#!/usr/bin/env python3
"""
Regression tests for check_opencode_sessions helpers.

Run:
    python3 tests/test_check_opencode_sessions.py
"""

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

from check_opencode_sessions import _session_timestamp, _summarize_opencode_logs


class CheckOpenCodeSessionsTests(unittest.TestCase):
    def test_session_timestamp_prefers_current_time_shape(self):
        session = {
            "time": {"created": 100, "updated": 200},
            "created": "legacy-created",
            "lastActivity": "legacy-updated",
        }

        self.assertEqual(_session_timestamp(session, "created"), 100)
        self.assertEqual(_session_timestamp(session, "updated"), 200)

    def test_session_timestamp_falls_back_to_legacy_shape(self):
        session = {
            "created": "legacy-created",
            "lastActivity": "legacy-updated",
        }

        self.assertEqual(_session_timestamp(session, "created"), "legacy-created")
        self.assertEqual(_session_timestamp(session, "updated"), "legacy-updated")

    def test_summarize_opencode_logs_extracts_jarvis_side_result(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            log_dir = root / "logs" / "opencode"
            log_dir.mkdir(parents=True)
            log_file = log_dir / "opencode-2026-06-25.jsonl"
            log_file.write_text(
                "\n".join([
                    '{"event":"session_start","session_id":"ses_123","task":"Build snake","task_type":"coding","model":{"providerID":"xai","modelID":"grok-build-0.1"},"context":{"jarvis_session":"20260625_033215"}}',
                    '{"event":"message_received","session_id":"ses_123","response_preview":"Project created","response_length":321,"duration_ms":1200,"has_error":false,"response_info":{"model_used":"grok-build-0.1","tokens":{"total":42}}}',
                    '{"event":"session_complete","session_id":"ses_123","success":true,"result_summary":"Task completed","error":null}',
                ])
                + "\n"
            )

            with patch("check_opencode_sessions._project_root", return_value=root):
                summary = _summarize_opencode_logs("ses_123")

        self.assertEqual(summary["task"], "Build snake")
        self.assertEqual(summary["task_type"], "coding")
        self.assertEqual(summary["jarvis_session"], "20260625_033215")
        self.assertEqual(summary["response_preview"], "Project created")
        self.assertEqual(summary["duration_ms"], 1200)
        self.assertEqual(summary["model_used"], "grok-build-0.1")
        self.assertEqual(summary["tokens"], {"total": 42})
        self.assertTrue(summary["success"])


if __name__ == "__main__":
    unittest.main()
