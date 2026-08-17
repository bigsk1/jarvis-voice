#!/usr/bin/env python3
"""Regression tests for structured retrieval diagnostics in tool logs."""

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

import check_tool_logs as check_tool_logs_skill
from tool_logger import ToolLogger


class ToolLoggerRetrievalTests(unittest.TestCase):
    def test_check_tool_logs_reports_semantic_disabled_reason(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = ToolLogger(log_dir=tmpdir)
            logger.log_tool_call(
                tool_name="tool_search",
                arguments={"query": "yard maintenance"},
                result={
                    "ok": True,
                    "speech": "No semantic matches",
                    "retrieval_mode": "keyword_fallback",
                    "semantic_disabled_reason": "embedding fingerprint mismatch",
                },
                duration_ms=42.0,
                mode="cloud",
            )
            stdout = StringIO()
            with patch.object(
                check_tool_logs_skill,
                "ToolLogger",
                return_value=logger,
            ), patch.object(
                sys,
                "argv",
                ["check_tool_logs.py", '{"tool_name":"tool_search","limit":1}'],
            ), redirect_stdout(stdout):
                exit_code = check_tool_logs_skill.main()

            result = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertIn("semantic retrieval disabled", result["speech"])
            log = result["data"]["logs"][0]
            self.assertNotIn("fallback_embeddings", log)
            self.assertEqual(log["retrieval_mode"], "keyword_fallback")
            self.assertEqual(
                log["semantic_disabled_reason"],
                "embedding fingerprint mismatch",
            )

            raw_log = json.loads(Path(logger.log_file).read_text().strip())
            self.assertNotIn("fallback_embeddings", raw_log)

    def test_log_tool_call_persists_sanitized_proxy_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = ToolLogger(log_dir=tmpdir)
            logger.log_tool_call(
                tool_name="mcp_duckduckgo_search",
                arguments={"query": "jarvis"},
                result={"ok": True, "speech": "Found results"},
                duration_ms=12.0,
                mode="cloud",
                proxy={
                    "policy": "prefer",
                    "used": True,
                    "slot": "LOCAL_PROXY",
                    "basis": "mcp_environment",
                    "url": "http://user:secret@proxy.test:8080",
                },
            )

            entry = logger.get_recent_logs(limit=1)[0]
            self.assertEqual(
                entry["proxy"],
                {
                    "policy": "prefer",
                    "used": True,
                    "slot": "LOCAL_PROXY",
                    "basis": "mcp_environment",
                },
            )
            self.assertNotIn("secret", Path(logger.log_file).read_text())


if __name__ == "__main__":
    unittest.main()
