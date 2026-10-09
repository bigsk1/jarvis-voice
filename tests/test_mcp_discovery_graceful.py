#!/usr/bin/env python3
"""MCP discovery should fail fast without auto-restart loops."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from mcp_client import MCPClient  # noqa: E402
from tool_schema import ToolRegistry  # noqa: E402


class FakeManager:
    def __init__(self, client):
        self.servers = {client.name: client}

    def stop_all(self):
        for client in self.servers.values():
            client.stop()


class FakeStdioClient:
    def __init__(self):
        self.name = "brave_search"
        self._auto_restart = True
        self.process = MagicMock()
        self.process.poll.return_value = 9
        self.start_auto_restart = None
        self.list_auto_restart = None
        self.stopped = False

    def start(self):
        self.start_auto_restart = self._auto_restart

    def list_tools(self):
        self.list_auto_restart = self._auto_restart
        return []

    def stop(self):
        self.stopped = True


class FakeRemoteClient:
    """Remote clients intentionally do not expose a process attribute."""

    def __init__(self):
        self.name = "remote_docs"
        self.stopped = False

    def start(self):
        pass

    def list_tools(self):
        return [
            {
                "name": "search",
                "description": "Search remote docs",
                "inputSchema": {"type": "object", "properties": {}},
            }
        ]

    def stop(self):
        self.stopped = True


class FakeSearchAndFetchClient(FakeRemoteClient):
    def list_tools(self):
        return [
            {"name": name, "description": name, "inputSchema": {"type": "object", "properties": {}}}
            for name in ("search", "fetch")
        ]


class TestMCPDiscoveryGraceful(unittest.TestCase):
    def _build_registry(self, client, tool_metadata=None, server_options=None, profile_overrides=None):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "mcp-servers.json"
            config_path.write_text(
                json.dumps({"mcpServers": {client.name: {
                    "enabled": True,
                    "tool_metadata": tool_metadata or {},
                    **(server_options or {}),
                }}}),
                encoding="utf-8",
            )
            manager = FakeManager(client)
            with (
                patch("mcp_client.MCPManager", return_value=manager),
                patch("tool_schema.ToolRegistry._discover_tools"),
                patch("time.sleep"),
                patch("tool_profiles.get_active_profile_name", return_value="default"),
                patch("tool_profiles.load_active_profile_overrides", return_value=profile_overrides or {}),
                patch("tool_profiles.warn_missing_profile_file"),
            ):
                return ToolRegistry(str(root), str(config_path))

    def test_check_health_skips_restart_when_auto_restart_disabled(self):
        client = MCPClient("brave_search", "docker", ["run", "mcp/brave-search"])
        client._auto_restart = False
        client.process = MagicMock()
        client.process.poll.return_value = 9

        with patch.object(client, "start") as mock_start:
            healthy = client._check_health()

        self.assertFalse(healthy)
        mock_start.assert_not_called()

    def test_check_health_still_restarts_when_auto_restart_enabled(self):
        client = MCPClient("brave_search", "docker", ["run", "mcp/brave-search"])
        client.process = MagicMock()
        client.process.poll.return_value = 9

        with patch.object(client, "start") as mock_start:
            mock_start.side_effect = RuntimeError("still broken")
            healthy = client._check_health()

        self.assertFalse(healthy)
        mock_start.assert_called_once()

    def test_registry_disables_restart_before_start_and_restores_it(self):
        client = FakeStdioClient()

        registry = self._build_registry(client)

        self.assertFalse(client.start_auto_restart)
        self.assertFalse(client.list_auto_restart)
        self.assertTrue(client._auto_restart)
        self.assertTrue(client.stopped)
        self.assertIn("brave_search", registry.mcp_unavailable)

    def test_registry_discovers_remote_client_without_process_attribute(self):
        client = FakeRemoteClient()

        registry = self._build_registry(client)

        self.assertIn("mcp_remote_docs_search", registry.tools)
        self.assertIs(registry.mcp_clients["remote_docs"], client)
        self.assertFalse(client.stopped)

    def test_mcp_web_search_flag_applies_to_discovered_tool_only(self):
        client = FakeSearchAndFetchClient()
        registry = self._build_registry(
            client,
            tool_metadata={"search": {"web_search": True}},
        )

        self.assertTrue(registry.get_tool("mcp_remote_docs_search").web_search)
        self.assertFalse(registry.get_tool("mcp_remote_docs_fetch").web_search)
        self.assertFalse(registry.mcp_unavailable)

    def test_server_allowlist_excludes_other_tools_even_if_profile_enables_them(self):
        client = FakeSearchAndFetchClient()
        registry = self._build_registry(
            client,
            server_options={"allowed_tools": ["search"]},
            profile_overrides={"mcp_remote_docs_fetch": True},
        )
        self.assertEqual(set(registry.tools), {"mcp_remote_docs_search"})
        self.assertIsNone(registry.get_tool("mcp_remote_docs_fetch"))
        self.assertEqual(registry.get_mcp_info("mcp_remote_docs_search"), ("remote_docs", "search"))

    def test_empty_server_allowlist_exposes_no_tools(self):
        registry = self._build_registry(
            FakeRemoteClient(), server_options={"allowed_tools": []},
        )
        self.assertFalse(registry.tools)

    def test_all_profile_disabled_tools_close_client_without_becoming_unavailable(self):
        client = FakeSearchAndFetchClient()
        registry = self._build_registry(client, profile_overrides={
            'mcp_remote_docs_search': False, 'mcp_remote_docs_fetch': False,
        })
        self.assertFalse(registry.tools)
        self.assertTrue(client.stopped)
        self.assertFalse(registry.mcp_unavailable)

    def test_blocking_one_tool_keeps_shared_client_but_blocking_all_stops_it(self):
        client = FakeSearchAndFetchClient()
        registry = self._build_registry(client)
        registry.stop_disallowed_mcp({'mcp_remote_docs_search'})
        self.assertFalse(client.stopped)
        registry.stop_disallowed_mcp({'mcp_remote_docs_search', 'mcp_remote_docs_fetch'})
        self.assertTrue(client.stopped)
        self.assertIsNotNone(registry.get_tool('mcp_remote_docs_search'))  # Unblocking can reuse its schema.

    def test_active_mode_block_list_closes_client_after_discovery(self):
        from config_loader import config_scope
        client = FakeSearchAndFetchClient()
        with config_scope('local', overrides={'BLOCKED_TOOLS': 'mcp_remote_docs_search,mcp_remote_docs_fetch'}):
            registry = self._build_registry(client)
        self.assertTrue(client.stopped)
        self.assertFalse(registry.mcp_unavailable)

    def test_new_block_list_does_not_interrupt_active_call(self):
        from threading import Lock
        client = FakeSearchAndFetchClient()
        registry = self._build_registry(client)
        client.lock = Lock()
        blocked = {'mcp_remote_docs_search', 'mcp_remote_docs_fetch'}
        with client.lock:
            registry.stop_disallowed_mcp(blocked)
            self.assertFalse(client.stopped)
        registry.stop_disallowed_mcp(blocked)
        self.assertTrue(client.stopped)

    def test_unlisted_tool_cannot_execute_through_registry_recovery(self):
        from orchestrator.executor import ToolExecutor

        registry = self._build_registry(
            FakeSearchAndFetchClient(), server_options={"allowed_tools": ["search"]},
        )
        executor = ToolExecutor.__new__(ToolExecutor)
        executor.registry = registry
        executor.mode = "cloud"
        executor.excluded_tools = set()
        with (
            patch("tool_schema.get_tool_registry", return_value=registry),
            patch("tool_schema.reset_tool_registry"),
            patch.object(executor, "_execute_mcp_tool") as call,
        ):
            result = executor.execute("mcp_remote_docs_fetch", {}, skip_permission_check=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "Tool not found")
        call.assert_not_called()

    def test_invalid_server_allowlist_fails_closed(self):
        for invalid in (None, "search", {"search": True}, [False], [""]):
            with self.subTest(allowed_tools=invalid):
                client = FakeRemoteClient()
                registry = self._build_registry(
                    client, server_options={"allowed_tools": invalid},
                )
                self.assertFalse(registry.tools)
                self.assertTrue(client.stopped)
                self.assertIn("allowed_tools", registry.mcp_unavailable[client.name])

    def test_shipped_malwarebytes_exposes_only_reviewed_lookup_tools(self):
        config = json.loads(
            (Path(__file__).resolve().parent.parent / "config/mcp-servers.json").read_text()
        )["mcpServers"]["malwarebytes"]
        expected = {
            "reputation-check_link", "reputation-check_phone", "reputation-check_email",
            "reputation-whois", "reputation-scan_all",
        }
        self.assertEqual(set(config["allowed_tools"]), expected)
        self.assertEqual(config["type"], "http")
        self.assertTrue(config["enabled"])
        client = FakeRemoteClient()
        client.name = "malwarebytes"
        client.list_tools = lambda: [
            {"name": name, "inputSchema": {"type": "object", "properties": {}}}
            for name in sorted(expected | {"reputation-report", "future_write_tool"})
        ]
        registry = self._build_registry(client, server_options=config)
        self.assertEqual(set(registry.tools), {f"mcp_malwarebytes_{name}" for name in expected})
        for name in expected:
            self.assertEqual(registry.get_mcp_info(f"mcp_malwarebytes_{name}"), (client.name, name))


if __name__ == "__main__":
    unittest.main()


def test_startup_missing_http_recovery_keeps_profile_allowlist_and_healthy_client(monkeypatch, tmp_path):
    from threading import Lock
    from unittest.mock import Mock
    client = FakeSearchAndFetchClient()
    client.transport_type = 'http'
    client.start = Mock()
    registry = ToolRegistry.__new__(ToolRegistry)
    registry.tools = {}
    registry.mcp_clients = {'healthy': Mock()}
    healthy = registry.mcp_clients['healthy']
    registry.mcp_manager = FakeManager(client)
    registry.mcp_unavailable = {client.name: 'offline'}
    registry._mcp_recovery_lock = Lock()
    registry._mcp_retry_after = {}
    registry._mcp_server_config = {client.name: {'allowed_tools': ['search'], 'retry_discovery': True}}
    registry._profile_overrides = {}
    db = Mock()
    monkeypatch.setattr('memory_db.get_memory_db', lambda: db)
    assert registry.get_tool('mcp_remote_docs_search') is None
    registry.list_tools()
    client.start.assert_not_called()
    registry.recover_unavailable_mcp()
    assert registry.get_tool('mcp_remote_docs_search') is not None
    assert registry.get_tool('mcp_remote_docs_fetch') is None
    assert registry.mcp_unavailable == {}
    client.start.assert_called_once()
    healthy.start.assert_not_called()
    assert [t.name for t in db.register_recovered_tools.call_args.args[0]] == ['mcp_remote_docs_search']
    registry.mcp_unavailable[client.name] = 'offline again'
    registry.get_tool('mcp_remote_docs_search')
    client.start.assert_called_once()  # Cooldown applies to repeated probes.
    registry._mcp_retry_after = {}
    registry._profile_overrides = {'mcp_remote_docs_search': False}
    registry.tools = {}
    registry.recover_unavailable_mcp()
    assert registry.tools == {}


def test_failed_recovery_is_bounded_and_stdio_is_not_started(monkeypatch):
    from threading import Lock
    from unittest.mock import Mock

    from mcp_client import _remote_call_budget
    client = FakeRemoteClient()
    client.transport_type = 'http'
    observed = []
    def start():
        observed.append(_remote_call_budget.get().deadline)
        raise OSError('offline')
    client.start = start
    stdio = FakeStdioClient()
    stdio.start = Mock()
    registry = ToolRegistry.__new__(ToolRegistry)
    registry.tools = {}
    registry.mcp_clients = {}
    registry.mcp_manager = FakeManager(client)
    registry.mcp_manager.servers[stdio.name] = stdio
    registry.mcp_unavailable = {client.name: 'offline', stdio.name: 'offline'}
    registry._mcp_recovery_lock = Lock()
    registry._mcp_retry_after = {}
    registry._mcp_server_config = {client.name: {'retry_discovery': True}}
    registry._profile_overrides = {}
    registry.recover_unavailable_mcp()
    registry.recover_unavailable_mcp()
    assert len(observed) == 1
    stdio.start.assert_not_called()
    assert _remote_call_budget.get() is None


def test_opted_in_docker_recovery_uses_isolated_client_and_normal_permissions(monkeypatch):
    from threading import Lock
    from unittest.mock import Mock

    import mcp_client
    old = MCPClient('brave_search', 'docker', ['run', '-i', 'image'])
    registry = ToolRegistry.__new__(ToolRegistry)
    registry.tools = {}
    registry.mcp_clients = {}
    registry.mcp_manager = FakeManager(old)
    registry.mcp_unavailable = {old.name: 'startup failed'}
    registry._mcp_server_config = {old.name: {
        'enabled': True, 'retry_discovery': True, 'allowed_tools': ['search'],
        'tool_metadata': {'search': {'web_search': True}},
    }}
    registry._mcp_recovery_lock = Lock()
    registry._mcp_retry_after = {}
    registry._profile_overrides = {}
    probes = []
    def probe(client, timeout_seconds):
        assert client is not old
        assert timeout_seconds == 3
        probes.append(client)
        return FakeSearchAndFetchClient().list_tools()
    monkeypatch.setattr(mcp_client, 'probe_stdio_tools', probe)
    db = Mock()
    monkeypatch.setattr('memory_db.get_memory_db', lambda: db)
    assert registry.get_tool('mcp_brave_search_search') is None
    assert probes == []
    registry.recover_unavailable_mcp()
    assert set(registry.tools) == {'mcp_brave_search_search'}
    assert registry.tools['mcp_brave_search_search'].web_search
    assert registry.mcp_manager.servers[old.name] is probes[0]
    assert registry.mcp_unavailable == {}
    assert [t.name for t in db.register_recovered_tools.call_args.args[0]] == ['mcp_brave_search_search']
    registry.mcp_unavailable[old.name] = 'failed again'
    registry.recover_unavailable_mcp()
    assert len(probes) == 1  # Thirty-second retry cooldown.


def test_mcp_description_supplement_and_prerequisite_are_local_and_profile_scoped():
    registry = TestMCPDiscoveryGraceful()._build_registry(FakeSearchAndFetchClient(), tool_metadata={
        'fetch': {'description_prefix': 'Fetch a previously located remote document.',
                  'prerequisite_tools': ['mcp_remote_docs_search']},
    })
    fetch = registry.get_tool('mcp_remote_docs_fetch')
    assert fetch.description.startswith('Fetch a previously located remote document.')
    assert fetch.description.endswith('fetch')
    assert fetch.prerequisite_tools == ['mcp_remote_docs_search']
    assert registry.get_tool('mcp_remote_docs_search').description == 'search'
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'orchestrator'))
    from router_v2 import expand_prerequisite_tool_names
    names, _ = expand_prerequisite_tool_names(['mcp_remote_docs_fetch'], registry, registry.list_tools())
    assert names == ['mcp_remote_docs_search', 'mcp_remote_docs_fetch']
    names, _ = expand_prerequisite_tool_names(['mcp_remote_docs_fetch'], registry, ['mcp_remote_docs_fetch'])
    assert names == ['mcp_remote_docs_fetch']


def test_default_http_servers_never_retry_during_lookup_or_selection(monkeypatch):
    from threading import Lock
    from unittest.mock import Mock
    registry = ToolRegistry.__new__(ToolRegistry)
    client = FakeRemoteClient()
    client.transport_type = 'http'
    client.start = Mock()
    registry.tools = {}
    registry.mcp_manager = FakeManager(client)
    registry.mcp_unavailable = {client.name: 'offline'}
    registry._mcp_server_config = {client.name: {'enabled': True}}
    registry._mcp_recovery_lock = Lock()
    registry._mcp_retry_after = {}
    assert registry.get_tool('native_tool') is None
    assert registry.list_tools() == []
    registry.recover_unavailable_mcp()
    client.start.assert_not_called()


def test_concurrent_selectors_wait_for_one_recovery_and_see_same_catalog(monkeypatch):
    import time
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Lock
    from unittest.mock import Mock
    client = FakeSearchAndFetchClient()
    client.transport_type = 'http'
    client.start = Mock(side_effect=lambda: time.sleep(.03))
    registry = ToolRegistry.__new__(ToolRegistry)
    registry.tools = {}
    registry.mcp_clients = {}
    registry.mcp_manager = FakeManager(client)
    registry.mcp_unavailable = {client.name: 'offline'}
    registry._mcp_server_config = {client.name: {'retry_discovery': True}}
    registry._mcp_recovery_lock = Lock()
    registry._mcp_retry_after = {}
    registry._profile_overrides = {}
    monkeypatch.setattr('memory_db.get_memory_db', lambda: Mock())
    barrier = Barrier(2)
    def select(_):
        barrier.wait()
        registry.recover_unavailable_mcp()
        return registry.list_tools()
    with ThreadPoolExecutor(max_workers=2) as pool:
        catalogs = list(pool.map(select, range(2)))
    assert catalogs[0] == catalogs[1] == ['mcp_remote_docs_search', 'mcp_remote_docs_fetch']
    client.start.assert_called_once()


def test_discovery_probe_has_outer_deadline_even_if_transport_never_completes():
    import time
    from threading import Event
    from unittest.mock import Mock

    from mcp_client import probe_remote_tools
    release = Event()
    client = FakeRemoteClient()
    client.start = lambda: release.wait(.5)
    client._force_restart = Mock()
    started = time.monotonic()
    try:
        assert probe_remote_tools(client, timeout_seconds=.02) == []
        assert time.monotonic() - started < .15
        client._force_restart.assert_called_once()
    finally:
        release.set()
