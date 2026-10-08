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
