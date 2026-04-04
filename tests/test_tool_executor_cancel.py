#!/usr/bin/env python3
"""
Regression tests for ToolExecutor cancellation behavior.

Run:
    python3 tests/test_tool_executor_cancel.py
"""

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

from executor import ToolExecutor


class FakeToolSchema:
    def __init__(self, script_path):
        self.script_path = script_path

    def requires_confirmation(self):
        return False


class FakeRegistry:
    def __init__(self, script_path):
        self._schema = FakeToolSchema(script_path)

    def get_tool(self, tool_name):
        return self._schema if tool_name == "fake_long_tool" else None

    def is_mcp_tool(self, tool_name):
        return False


class ToolExecutorCancelTests(unittest.TestCase):
    def test_cancellation_stops_long_running_tool_promptly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "fake_long_tool.py"
            script_path.write_text(
                "#!/usr/bin/env python3\n"
                "import json, sys, time\n"
                "time.sleep(10)\n"
                "print(json.dumps({'ok': True, 'speech': 'finished'}))\n"
            )

            executor = ToolExecutor(mode="cloud", registry=FakeRegistry(str(script_path)))
            executor.set_cancel_check(lambda: True)

            start = time.time()
            result = executor.execute("fake_long_tool", {})
            elapsed = time.time() - start

        self.assertTrue(result["ok"])
        self.assertTrue(result["cancelled"])
        self.assertLess(elapsed, 3.0)

    def test_session_context_is_passed_to_tool_environment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "fake_long_tool.py"
            script_path.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os\n"
                "print(json.dumps({\n"
                "  'ok': True,\n"
                "  'speech': 'done',\n"
                "  'data': {\n"
                "    'jarvis_session': os.environ.get('JARVIS_SESSION_ID'),\n"
                "    'web_conversation_id': os.environ.get('JARVIS_WEB_CONVERSATION_ID')\n"
                "  }\n"
                "} ))\n"
            )

            executor = ToolExecutor(mode="cloud", registry=FakeRegistry(str(script_path)))
            executor.set_session_context(
                jarvis_session_id="20260404_123456",
                web_conversation_id="6dbf22ca"
            )
            result = executor.execute("fake_long_tool", {})

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["jarvis_session"], "20260404_123456")
        self.assertEqual(result["data"]["web_conversation_id"], "6dbf22ca")


if __name__ == "__main__":
    unittest.main()
