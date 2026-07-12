#!/usr/bin/env python3
"""
Regression tests for ToolExecutor cancellation behavior.

Run:
    python3 tests/test_tool_executor_cancel.py
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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


class EmptyRegistry:
    def get_tool(self, _tool_name):
        return None

    def is_mcp_tool(self, tool_name):
        return tool_name.startswith("mcp_")


class FakeMcpClient:
    def __init__(self):
        self.calls = []

    def call_tool(self, name, args):
        self.calls.append((name, args))
        return {"ok": True, "speech": "mcp ok", "data": {"name": name, "args": args}}


class FakeMcpRegistry:
    def __init__(self, schema):
        self._schema = schema
        self.client = FakeMcpClient()
        self.mcp_clients = {"brave_search": self.client}

    def get_tool(self, tool_name):
        return self._schema if tool_name == "mcp_brave_search_brave_web_search" else None

    def is_mcp_tool(self, tool_name):
        return tool_name.startswith("mcp_")

    def get_mcp_info(self, tool_name):
        if tool_name == "mcp_brave_search_brave_web_search":
            return "brave_search", "brave_web_search"
        return None, None


class ToolExecutorCancelTests(unittest.TestCase):
    def test_home_depot_timeout_allows_two_sequential_http_calls(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(executor._get_subprocess_timeout("serpapi_home_depot"), 200)

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

    def test_large_stdout_does_not_deadlock_on_pipe_buffer(self):
        """Regression: >64KB stdout must not block until subprocess timeout."""
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "fake_long_tool.py"
            script_path.write_text(
                "#!/usr/bin/env python3\n"
                "import json\n"
                "payload = 'x' * 100000\n"
                "print(json.dumps({'ok': True, 'speech': 'big', 'data': {'payload': payload}}))\n"
            )

            executor = ToolExecutor(mode="cloud", registry=FakeRegistry(str(script_path)))
            start = time.time()
            result = executor.execute("fake_long_tool", {})
            elapsed = time.time() - start

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["data"]["payload"]), 100000)
        self.assertLess(elapsed, 5.0)

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

    def test_missing_mcp_tool_recovers_from_shared_registry(self):
        shared_registry = FakeMcpRegistry(FakeToolSchema("__mcp__brave_search__brave_web_search"))
        executor = ToolExecutor(mode="cloud", registry=EmptyRegistry())

        modules = {
            "tool_schema": SimpleNamespace(
                get_tool_registry=lambda mode=None: shared_registry,
                reset_tool_registry=lambda: None,
            )
        }
        with patch.dict(sys.modules, modules):
            result = executor.execute(
                "mcp_brave_search_brave_web_search",
                {"query": "github trending"},
            )

        self.assertTrue(result["ok"])
        self.assertIs(executor.registry, shared_registry)
        self.assertEqual(
            shared_registry.client.calls,
            [("brave_web_search", {"query": "github trending"})],
        )


if __name__ == "__main__":
    unittest.main()
