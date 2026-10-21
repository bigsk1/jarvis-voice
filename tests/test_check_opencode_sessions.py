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

from check_opencode_sessions import _session_timestamp, _summarize_opencode_logs, main


class CheckOpenCodeSessionsTests(unittest.TestCase):
    def test_v2_session_summary_uses_outcome_and_tokens_without_invented_message_count(self):
        session = {
            'id': 'ses_123', 'title': 'Build example', 'agent': 'build',
            'time': {'created': 100, 'updated': 200}, 'outcome': 'succeeded',
            'tokens': {'input': 1234, 'output': 56, 'reasoning': 0, 'cache': {'read': 0, 'write': 0}},
        }
        with patch('check_opencode_sessions.sys.argv', ['check_opencode_sessions.py', '{"session_id":"ses_123"}']), \
             patch('check_opencode_sessions.OpenCodeClient') as client_type, \
             patch('check_opencode_sessions._summarize_opencode_logs', return_value={}), \
             patch('builtins.print'):
            client = client_type.return_value
            client.health_check.return_value = {'healthy': True}
            client.get_session.return_value = session
            result = main()
        self.assertTrue(result['ok'])
        self.assertIn('Last run: succeeded.', result['speech'])
        self.assertIn('1234 input, 56 output', result['speech'])
        self.assertNotIn('messages in conversation', result['speech'])
        self.assertEqual(result['data']['session'], session)

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
