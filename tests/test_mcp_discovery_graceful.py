#!/usr/bin/env python3
"""MCP discovery should fail fast without auto-restart loops."""

import sys
import json
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


class TestMCPDiscoveryGraceful(unittest.TestCase):
    def _build_registry(self, client):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "mcp-servers.json"
            config_path.write_text(
                json.dumps({"mcpServers": {client.name: {"enabled": True}}}),
                encoding="utf-8",
            )
            manager = FakeManager(client)
            with (
                patch("mcp_client.MCPManager", return_value=manager),
                patch("tool_schema.ToolRegistry._discover_tools"),
                patch("time.sleep"),
                patch("tool_profiles.get_active_profile_name", return_value="default"),
                patch("tool_profiles.load_active_profile_overrides", return_value={}),
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


if __name__ == "__main__":
    unittest.main()
