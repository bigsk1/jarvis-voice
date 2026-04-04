#!/usr/bin/env python3
"""
Regression tests for OpenCode tool model selection.

Run:
    python3 tests/test_opencode_tool.py
"""

import json
import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from skills import opencode


class OpenCodeToolTests(unittest.TestCase):
    def test_uses_opencode_provider_and_model_from_config(self):
        stdout = StringIO()

        class FakeClient:
            captured = None

            def health_check(self):
                return {"healthy": True}

            def execute_task(self, **kwargs):
                FakeClient.captured = kwargs
                return {
                    "ok": True,
                    "session_id": "ses_test",
                    "result": {"content": "done"},
                }

        def fake_get_config(key, default=None):
            values = {
                "OPENCODE_BASE_URL": "http://localhost:4096",
                "OPENCODE_PROVIDER": "openai",
                "OPENCODE_MODEL": "gpt-5.3-codex",
            }
            return values.get(key, default)

        with patch("skills.opencode.OpenCodeClient", return_value=FakeClient()), \
             patch("skills.opencode.load_config"), \
             patch("skills.opencode.get_config_value", side_effect=fake_get_config), \
             patch("skills.opencode.get_memory_context", return_value={}), \
             patch.object(sys, "argv", ["opencode.py", json.dumps({
                 "task": "Build a demo app",
                 "task_type": "coding",
                 "agent_mode": "build",
             })]), \
             patch("sys.stdout", stdout):
            exit_code = opencode.main()

        result = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(FakeClient.captured["model"]["providerID"], "openai")
        self.assertEqual(FakeClient.captured["model"]["modelID"], "gpt-5.3-codex")
        self.assertNotIn("memory", FakeClient.captured["context"])

    def test_memory_context_is_only_included_when_enabled(self):
        stdout = StringIO()

        class FakeClient:
            captured = None

            def health_check(self):
                return {"healthy": True}

            def execute_task(self, **kwargs):
                FakeClient.captured = kwargs
                return {
                    "ok": True,
                    "session_id": "ses_test",
                    "result": {"content": "done"},
                }

        def fake_get_config(key, default=None):
            values = {
                "OPENCODE_BASE_URL": "http://localhost:4096",
                "OPENCODE_PROVIDER": "openai",
                "OPENCODE_MODEL": "gpt-5.3-codex",
                "OPENCODE_INCLUDE_MEMORY": "true",
            }
            return values.get(key, default)

        with patch("skills.opencode.OpenCodeClient", return_value=FakeClient()), \
             patch("skills.opencode.load_config"), \
             patch("skills.opencode.get_config_value", side_effect=fake_get_config), \
             patch("skills.opencode.get_memory_context", return_value={"relevant_memories": [{"key": "x"}]}), \
             patch.object(sys, "argv", ["opencode.py", json.dumps({
                 "task": "Build a demo app",
                 "task_type": "coding",
                 "agent_mode": "build",
             })]), \
             patch("sys.stdout", stdout):
            exit_code = opencode.main()

        self.assertEqual(exit_code, 0)
        self.assertIn("memory", FakeClient.captured["context"])

    def test_condense_for_voice_prefers_project_path_and_run_hint_from_parts(self):
        result = {
            "parts": [
                {"type": "text", "text": "Implemented in `/home/boss/jarvis-workspace/projects/calculator` with a minimal terminal calculator loop and README."},
                {"type": "text", "text": "- Created `/home/boss/jarvis-workspace/projects/calculator/calculator.py`"},
                {"type": "text", "text": "- Run with `python calculator.py`"},
            ]
        }

        speech = opencode.condense_for_voice(result, "Build a calculator")

        self.assertIn("/home/boss/jarvis-workspace/projects/calculator", speech)
        self.assertIn("Created /home/boss/jarvis-workspace/projects/calculator/calculator.py", speech)
        self.assertIn("Run with python calculator.py", speech)

    def test_extract_opencode_response_text_returns_full_parts_text(self):
        result = {
            "parts": [
                {"type": "text", "text": "Implemented in `/home/boss/jarvis-workspace/projects/calculator-app`."},
                {"type": "text", "text": "Created `/home/boss/jarvis-workspace/projects/calculator-app/index.html`."},
                {"type": "text", "text": "OpenCode can also add keyboard support."},
            ]
        }

        raw = opencode.extract_opencode_response_text(result)

        self.assertIn("Implemented in `/home/boss/jarvis-workspace/projects/calculator-app`.", raw)
        self.assertIn("Created `/home/boss/jarvis-workspace/projects/calculator-app/index.html`.", raw)
        self.assertIn("OpenCode can also add keyboard support.", raw)


if __name__ == "__main__":
    unittest.main()
