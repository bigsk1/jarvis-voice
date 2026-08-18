#!/usr/bin/env python3
"""
Regression tests for ToolExecutor cancellation behavior.

Run:
    python3 tests/test_tool_executor_cancel.py
"""

import os
import signal
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
    def test_local_tool_progress_protocol_is_forwarded_before_final_result(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            script = Path(tmp_dir) / "progress_tool.py"
            script.write_text(
                "import json, sys\n"
                "sys.stderr.write('__JARVIS_TOOL_PROGRESS__:' + json.dumps({"
                "'event_type': 'tool_progress', 'phase': 'tool', "
                "'status': 'Working', 'sequence': 1}) + '\\n')\n"
                "sys.stderr.flush()\n"
                "print(json.dumps({'ok': True, 'speech': 'done'}))\n"
            )
            executor = ToolExecutor(
                mode="cloud",
                registry=FakeRegistry(script, tool_name="fake_long_tool"),
            )
            executor.logger = RecordingLogger()
            events = []
            executor.set_progress_callback(
                lambda event_type, **payload: events.append((event_type, payload))
            )

            result = executor.execute("fake_long_tool", {})

        self.assertTrue(result["ok"])
        self.assertEqual(events[0][0], "tool_progress")
        self.assertEqual(events[0][1]["tool"], "fake_long_tool")
        self.assertEqual(events[0][1]["status"], "Working")

    def test_opencode_inner_event_type_reaches_executor_as_tool_progress(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            script = Path(tmp_dir) / "opencode_progress_tool.py"
            script.write_text(
                "import json, sys\n"
                f"sys.path.insert(0, {str(PROJECT_ROOT)!r})\n"
                "from skills.opencode import emit_opencode_progress\n"
                "emit_opencode_progress({'event_type': 'message.part.updated', "
                "'phase': 'tool', 'status': 'OpenCode: Running tests'})\n"
                "print(json.dumps({'ok': True, 'speech': 'done'}))\n"
            )
            executor = ToolExecutor(
                mode="cloud",
                registry=FakeRegistry(script, tool_name="opencode"),
            )
            executor.logger = RecordingLogger()
            events = []
            executor.set_progress_callback(
                lambda event_type, **payload: events.append((event_type, payload))
            )

            result = executor.execute("opencode", {}, skip_permission_check=True)

        self.assertTrue(result["ok"])
        self.assertEqual(events[0][0], "tool_progress")
        self.assertEqual(events[0][1]["opencode_event_type"], "message.part.updated")
        self.assertEqual(events[0][1]["status"], "OpenCode: Running tests")

    def test_progress_callback_failure_is_reported_without_dropping_result(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            script = Path(tmp_dir) / "progress_tool.py"
            script.write_text(
                "import json, sys\n"
                "sys.stderr.write('__JARVIS_TOOL_PROGRESS__:' + json.dumps({"
                "'event_type': 'tool_progress', 'status': 'Working'}) + '\\n')\n"
                "sys.stderr.flush()\n"
                "print(json.dumps({'ok': True, 'speech': 'done'}))\n"
            )
            executor = ToolExecutor(
                mode="cloud",
                registry=FakeRegistry(script, tool_name="fake_long_tool"),
            )
            executor.logger = RecordingLogger()
            executor.set_progress_callback(
                lambda _event_type, **_payload: (_ for _ in ()).throw(
                    RuntimeError("bridge failed")
                )
            )

            with patch("sys.stderr", new_callable=__import__("io").StringIO) as stderr:
                result = executor.execute("fake_long_tool", {})

        self.assertTrue(result["ok"])
        self.assertIn("[TOOL_PROGRESS] Callback failed", stderr.getvalue())
        self.assertIn("(RuntimeError): bridge failed", stderr.getvalue())

    def test_amazon_timeout_allows_product_detail_enrichment(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(executor._get_subprocess_timeout("serpapi_amazon_search"), 90)

    def test_home_depot_timeout_allows_two_sequential_http_calls(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(executor._get_subprocess_timeout("serpapi_home_depot"), 200)

    def test_flight_search_timeout_allows_deep_search(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(executor._get_subprocess_timeout("flight_search"), 120)

    def test_travel_explore_timeout_allows_full_provider_request(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(
            executor._get_subprocess_timeout("serpapi_travel_explore"), 120
        )

    def test_google_events_timeout_allows_full_provider_request(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(executor._get_subprocess_timeout("serpapi_google_events"), 120)

    def test_document_ocr_timeout_allows_large_gpu_document_and_extraction(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(executor._get_subprocess_timeout("document_ocr"), 1200)

    def test_tripadvisor_timeout_allows_three_sequential_http_calls(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(executor._get_subprocess_timeout("serpapi_tripadvisor"), 160)

    def test_open_table_reviews_timeout_allows_full_provider_request(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(
            executor._get_subprocess_timeout("serpapi_open_table_reviews"), 90
        )

    def test_trakt_timeout_allows_bounded_related_and_video_calls(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(executor._get_subprocess_timeout("trakt_movies"), 300)
        self.assertEqual(executor._get_subprocess_timeout("trakt_tv_shows"), 300)
        self.assertEqual(executor._get_subprocess_timeout("trakt_account"), 300)

    def test_tmdb_timeout_allows_proxy_chain_and_metadata_helpers(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(executor._get_subprocess_timeout("tmdb_movies"), 300)
        self.assertEqual(executor._get_subprocess_timeout("tmdb_tv_shows"), 300)

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

    def test_google_immersive_product_timeout_allows_full_provider_request(self):
        executor = ToolExecutor(mode="cloud", registry=FakeRegistry("/tmp/fake.py"))
        self.assertEqual(
            executor._get_subprocess_timeout("serpapi_google_immersive_product"), 120
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

    def test_google_events_empty_results_uses_live_incident_context(self):
        original = {
            "ok": False,
            "speech": (
                "SerpApi Google Events error: SerpApi error: Google hasn't "
                "returned any results for this query."
            ),
            "error": (
                "SerpApi Google Events error: SerpApi error: Google hasn't "
                "returned any results for this query."
            ),
        }
        active_incident = {
            "name": "[Google Events API] Empty results for all queries",
            "status": "investigating",
            "impact": "critical",
            "shortlink": "https://stspg.io/example-events",
            "incident_updates": [
                {
                    "status": "investigating",
                    "body": "We are continuing to investigate this issue.",
                }
            ],
        }

        with patch(
            "serpapi_client.fetch_serpapi_unresolved_incidents",
            return_value=[active_incident],
        ):
            result = ToolExecutor._with_serpapi_incident_context(
                "serpapi_google_events",
                {"query": "events", "location": "Austin, Texas"},
                original,
            )

        self.assertFalse(result["ok"])
        self.assertIn("Empty results for all queries", result["speech"])
        self.assertEqual(result["error"], result["speech"])
        self.assertEqual(
            result["data"]["failure_reason"],
            "active_provider_incident",
        )
        self.assertEqual(
            result["data"]["serpapi_incident"]["engine"],
            "google_events",
        )

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

    def test_opencode_timeout_sends_sigterm_before_escalating(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            marker_path = Path(tmpdir) / "abort-handler-ran"
            script_path = Path(tmpdir) / "fake_opencode.py"
            script_path.write_text(
                "#!/usr/bin/env python3\n"
                "import signal, subprocess, sys, time\n"
                "from pathlib import Path\n"
                f"marker = Path({str(marker_path)!r})\n"
                "def stop(_signum, _frame):\n"
                "    marker.write_text('aborted')\n"
                "    raise SystemExit(143)\n"
                "signal.signal(signal.SIGTERM, stop)\n"
                "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'])\n"
                "while True:\n"
                "    time.sleep(1)\n"
            )
            executor = ToolExecutor(
                mode="cloud",
                registry=FakeRegistry(str(script_path), tool_name="opencode"),
            )
            executor.logger = RecordingLogger()

            start = time.time()
            with patch.object(executor, "_get_subprocess_timeout", return_value=0.1):
                result = executor.execute("opencode", {})
            elapsed = time.time() - start
            marker_value = marker_path.read_text()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "Timeout")
        self.assertEqual(marker_value, "aborted")
        self.assertLess(elapsed, 3.0)

    def test_opencode_process_timeout_includes_cleanup_grace(self):
        executor = ToolExecutor(
            mode="cloud",
            registry=FakeRegistry("/tmp/fake.py", tool_name="opencode"),
        )

        with patch("executor.get_int", return_value=900):
            timeout = executor._get_subprocess_timeout("opencode")

        self.assertEqual(timeout, 930)

    def test_timeout_does_not_wait_for_descendant_holding_output_pipes(self):
        child_pid = None
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                pid_path = Path(tmpdir) / "escaped-child.pid"
                script_path = Path(tmpdir) / "parent_with_escaped_child.py"
                script_path.write_text(
                    "#!/usr/bin/env python3\n"
                    "import subprocess, sys, time\n"
                    "from pathlib import Path\n"
                    f"pid_path = Path({str(pid_path)!r})\n"
                    "child = subprocess.Popen(\n"
                    "    [sys.executable, '-c', 'import time; time.sleep(20)'],\n"
                    "    start_new_session=True,\n"
                    ")\n"
                    "pid_path.write_text(str(child.pid))\n"
                    "while True:\n"
                    "    time.sleep(1)\n"
                )
                executor = ToolExecutor(
                    mode="cloud",
                    registry=FakeRegistry(str(script_path)),
                )
                executor.logger = RecordingLogger()

                start = time.time()
                with patch.object(executor, "_get_subprocess_timeout", return_value=0.1):
                    result = executor.execute("fake_long_tool", {})
                elapsed = time.time() - start
                child_pid = int(pid_path.read_text())
        finally:
            if child_pid is not None:
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "Timeout")
        self.assertLess(elapsed, 2.5)

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
