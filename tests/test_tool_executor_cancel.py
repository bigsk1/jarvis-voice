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
    def __init__(self, script_path, proxy_policy="inherit"):
        self.script_path = script_path
        self.proxy_policy = proxy_policy

    def requires_confirmation(self):
        return False


class FakeRegistry:
    def __init__(self, script_path, proxy_policy="inherit", tool_name="fake_long_tool"):
        self._schema = FakeToolSchema(script_path, proxy_policy=proxy_policy)
        self.tool_name = tool_name

    def get_tool(self, tool_name):
        return self._schema if tool_name == self.tool_name else None

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

    def get_proxy_log_metadata(self):
        return {
            "policy": "prefer",
            "used": True,
            "slot": "LOCAL_PROXY2",
            "basis": "mcp_environment",
        }


class RecordingLogger:
    def __init__(self):
        self.calls = []

    def log_tool_call(self, **kwargs):
        self.calls.append(kwargs)


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
    def test_amazon_timeout_allows_product_detail_enrichment(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(executor._get_subprocess_timeout("serpapi_amazon_search"), 90)

    def test_home_depot_timeout_allows_two_sequential_http_calls(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(executor._get_subprocess_timeout("serpapi_home_depot"), 200)

    def test_flight_search_timeout_allows_deep_search(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(executor._get_subprocess_timeout("flight_search"), 120)

    def test_tripadvisor_timeout_allows_three_sequential_http_calls(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(executor._get_subprocess_timeout("serpapi_tripadvisor"), 160)

    def test_trakt_timeout_allows_bounded_related_and_video_calls(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(executor._get_subprocess_timeout("trakt_movies"), 300)

    def test_tmdb_timeout_allows_proxy_chain_and_metadata_helpers(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(executor._get_subprocess_timeout("tmdb_movies"), 300)

    def test_search_index_timeout_allows_deep_recall_request(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(executor._get_subprocess_timeout("serpapi_search_index"), 120)

    def test_google_news_light_timeout_allows_full_provider_request(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(
            executor._get_subprocess_timeout("serpapi_google_news_light"), 120
        )

    def test_google_shopping_light_timeout_allows_full_provider_request(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(
            executor._get_subprocess_timeout("serpapi_google_shopping_light"), 120
        )

    def test_google_sports_timeout_allows_resolver_and_provider_requests(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(executor._get_subprocess_timeout("serpapi_google_sports"), 200)

    def test_google_images_light_timeout_allows_full_provider_request(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(
            executor._get_subprocess_timeout("serpapi_google_images_light"), 160
        )

    def test_google_local_timeout_allows_full_provider_request(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(executor._get_subprocess_timeout("serpapi_google_local"), 120)

    def test_google_local_services_timeout_allows_cid_resolution_and_provider_request(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(
            executor._get_subprocess_timeout("serpapi_google_local_services"), 200
        )

    def test_google_trends_timeout_allows_full_provider_request(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(executor._get_subprocess_timeout("serpapi_google_trends"), 120)

    def test_google_trending_now_timeout_allows_full_provider_request(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(executor._get_subprocess_timeout("serpapi_google_trending_now"), 120)

    def test_final_serpapi_failure_adds_matching_incident_context(self):
        diagnosis = {
            "speech": "SerpApi is reporting a matching Home Depot incident.",
            "data": {
                "failure_reason": "active_provider_incident",
                "serpapi_incident": {"engine": "home_depot"},
            },
        }
        original = {
            "ok": False,
            "speech": "SerpApi Home Depot search timed out.",
            "error": "Timeout",
            "data": {"existing": True},
        }

        with patch("executor.diagnose_serpapi_tool_failure", return_value=diagnosis) as diagnose:
            result = ToolExecutor._with_serpapi_incident_context(
                "serpapi_home_depot",
                {"query": "cordless drill"},
                original,
            )

        diagnose.assert_called_once()
        self.assertFalse(result["ok"])
        self.assertEqual(result["speech"], diagnosis["speech"])
        self.assertEqual(result["error"], diagnosis["speech"])
        self.assertTrue(result["data"]["existing"])
        self.assertEqual(result["data"]["serpapi_incident"]["engine"], "home_depot")

    def test_successful_tool_does_not_check_serpapi_status(self):
        output = {"ok": True, "speech": "done"}
        with patch("executor.diagnose_serpapi_tool_failure") as diagnose:
            result = ToolExecutor._with_serpapi_incident_context(
                "serpapi_home_depot",
                {"query": "cordless drill"},
                output,
            )

        self.assertIs(result, output)
        diagnose.assert_not_called()

    def test_subprocess_timeout_is_diagnosed_before_final_response(self):
        diagnosis = {
            "speech": "SerpApi is reporting a matching Home Depot incident.",
            "data": {"failure_reason": "active_provider_incident"},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "slow_serpapi.py"
            script_path.write_text("import time\ntime.sleep(10)\n")
            executor = ToolExecutor(
                mode="cloud",
                registry=FakeRegistry(
                    str(script_path),
                    tool_name="serpapi_home_depot",
                ),
            )
            executor.logger = RecordingLogger()

            with patch.object(executor, "_get_subprocess_timeout", return_value=1), patch(
                "executor.diagnose_serpapi_tool_failure",
                return_value=diagnosis,
            ) as diagnose:
                result = executor.execute(
                    "serpapi_home_depot",
                    {"query": "cordless drill"},
                )

        self.assertEqual(result["speech"], diagnosis["speech"])
        self.assertEqual(result["data"]["failure_reason"], "active_provider_incident")
        self.assertTrue(diagnose.call_args.kwargs["force"])
        self.assertEqual(executor.logger.calls[-1]["result"], result)

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

    def test_off_proxy_policy_reaches_child_without_proxy_secrets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "fake_long_tool.py"
            script_path.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os\n"
                "print(json.dumps({\n"
                "  'ok': True,\n"
                "  'speech': 'done',\n"
                "  'data': {\n"
                "    'policy': os.environ.get('JARVIS_TOOL_PROXY_POLICY'),\n"
                "    'local_proxy': os.environ.get('LOCAL_PROXY'),\n"
                "    'local_proxy2': os.environ.get('LOCAL_PROXY2'),\n"
                "    'http_proxy_present': 'HTTP_PROXY' in os.environ,\n"
                "    'https_proxy_present': 'HTTPS_PROXY' in os.environ\n"
                "  }\n"
                "} ))\n"
            )

            executor = ToolExecutor(
                mode="cloud",
                registry=FakeRegistry(str(script_path), proxy_policy="off"),
            )
            result = executor.execute("fake_long_tool", {})

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["policy"], "off")
        self.assertEqual(result["data"]["local_proxy"], "")
        self.assertEqual(result["data"]["local_proxy2"], "")
        self.assertFalse(result["data"]["http_proxy_present"])
        self.assertFalse(result["data"]["https_proxy_present"])

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

    def test_mcp_tool_log_records_proxy_route_for_that_call(self):
        registry = FakeMcpRegistry(FakeToolSchema("__mcp__brave_search__brave_web_search"))
        executor = ToolExecutor(mode="cloud", registry=registry)
        executor.logger = RecordingLogger()

        result = executor.execute(
            "mcp_brave_search_brave_web_search",
            {"query": "github trending"},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(len(executor.logger.calls), 1)
        self.assertEqual(
            executor.logger.calls[0]["proxy"],
            {
                "policy": "prefer",
                "used": True,
                "slot": "LOCAL_PROXY2",
                "basis": "mcp_environment",
            },
        )


if __name__ == "__main__":
    unittest.main()
