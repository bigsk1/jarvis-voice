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
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from paths import get_jarvis_workspace

from skills import opencode


class OpenCodeToolTests(unittest.TestCase):
    def test_memory_context_accepts_keyword_only_hybrid_rows_without_fake_cosine(self):
        class FakeMemoryDb:
            closed = False

            def semantic_search(self, query, limit):
                self.asserted = (query, limit)
                return [
                    {
                        "key": "dense_context",
                        "value": "Use typed Python.",
                        "category": "preference",
                        "similarity": 0.61,
                        "retrieval_score": 0.92,
                        "retrieval_channels": ["dense", "keyword"],
                    },
                    {
                        "key": "exact_identifier",
                        "value": "The project code is Atlas-7.",
                        "category": "fact",
                        "retrieval_score": 0.55,
                        "retrieval_channels": ["keyword"],
                        "keyword_match_mode": "precise",
                    },
                    {
                        "key": "weak_dense",
                        "value": "Do not include this.",
                        "category": "fact",
                        "similarity": 0.49,
                        "retrieval_score": 0.99,
                        "retrieval_channels": ["dense", "keyword"],
                    },
                ]

            def recall(self, query, limit=None):
                return []

            def close(self):
                self.closed = True

        fake_db = FakeMemoryDb()
        with patch("skills.opencode.MemoryDB", return_value=fake_db):
            context = opencode.get_memory_context("Work on Atlas-7", "cloud")

        self.assertTrue(fake_db.closed)
        self.assertEqual(
            [item["key"] for item in context["relevant_memories"]],
            ["dense_context", "exact_identifier"],
        )
        self.assertEqual(
            context["relevant_memories"][0]["relevance_basis"],
            "semantic_similarity",
        )
        self.assertEqual(context["relevant_memories"][0]["relevance"], "61%")
        self.assertEqual(context["relevant_memories"][0]["match_type"], "hybrid")
        self.assertEqual(
            context["relevant_memories"][1]["relevance_basis"],
            "keyword_retrieval_score",
        )
        self.assertEqual(context["relevant_memories"][1]["relevance"], "55%")
        self.assertEqual(context["relevant_memories"][1]["match_type"], "keyword_exact")

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
                "OPENCODE_PROVIDER": "xai",
                "OPENCODE_MODEL": "grok-build-0.1",
            }
            return values.get(key, default)

        with patch("skills.opencode.OpenCodeClient", return_value=FakeClient()), \
             patch("skills.opencode.load_config"), \
             patch("skills.opencode.get_config_value", side_effect=fake_get_config), \
             patch("config_loader.get_config_value", side_effect=fake_get_config), \
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
        self.assertEqual(FakeClient.captured["model"]["providerID"], "xai")
        self.assertEqual(FakeClient.captured["model"]["modelID"], "grok-build-0.1")
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
                "OPENCODE_PROVIDER": "xai",
                "OPENCODE_MODEL": "grok-build-0.1",
                "OPENCODE_INCLUDE_MEMORY": "true",
            }
            return values.get(key, default)

        with patch("skills.opencode.OpenCodeClient", return_value=FakeClient()), \
             patch("skills.opencode.load_config"), \
             patch("skills.opencode.get_config_value", side_effect=fake_get_config), \
             patch("config_loader.get_config_value", side_effect=fake_get_config), \
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
        calc = str((get_jarvis_workspace() / "projects" / "calculator").resolve())
        calc_py = str((get_jarvis_workspace() / "projects" / "calculator" / "calculator.py").resolve())
        result = {
            "parts": [
                {"type": "text", "text": f"Implemented in `{calc}` with a minimal terminal calculator loop and README."},
                {"type": "text", "text": f"- Created `{calc_py}`"},
                {"type": "text", "text": "- Run with `python calculator.py`"},
            ]
        }

        speech = opencode.condense_for_voice(result, "Build a calculator")

        self.assertIn(calc, speech)
        self.assertIn(f"Created {calc_py}", speech)
        self.assertIn("Run with python calculator.py", speech)

    def test_extract_opencode_response_text_returns_full_parts_text(self):
        app_dir = str((get_jarvis_workspace() / "projects" / "calculator-app").resolve())
        index_html = str((get_jarvis_workspace() / "projects" / "calculator-app" / "index.html").resolve())
        result = {
            "parts": [
                {"type": "text", "text": f"Implemented in `{app_dir}`."},
                {"type": "text", "text": f"Created `{index_html}`."},
                {"type": "text", "text": "OpenCode can also add keyboard support."},
            ]
        }

        raw = opencode.extract_opencode_response_text(result)

        self.assertIn(f"Implemented in `{app_dir}`.", raw)
        self.assertIn(f"Created `{index_html}`.", raw)
        self.assertIn("OpenCode can also add keyboard support.", raw)


if __name__ == "__main__":
    unittest.main()
