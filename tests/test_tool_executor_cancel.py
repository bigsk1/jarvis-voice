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


if __name__ == "__main__":
    unittest.main()
