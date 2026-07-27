#!/usr/bin/env python3
"""Regression tests for proxy metadata in the Web tool-log stream."""

import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))

from server_package_utils import load_server_package

load_server_package(
    "jarvis_web_tool_proxy_test_server",
    PROJECT_ROOT / "jarvis-web" / "server",
)

from jarvis_web_tool_proxy_test_server.services.log_streamer import LogStreamer


class ToolProxyLogStreamerTests(unittest.TestCase):
    def test_tool_entry_exposes_proxy_route_details(self):
        streamer = LogStreamer(lambda entry: None)
        line = json.dumps({
            "timestamp": "2026-07-27T12:00:00",
            "mode": "cloud",
            "tool": "mcp_duckduckgo_search",
            "arguments": {"query": "jarvis"},
            "result": {"ok": True, "speech": "Found results"},
            "duration_ms": 42.0,
            "proxy": {
                "policy": "prefer",
                "used": True,
                "slot": "LOCAL_PROXY",
                "basis": "mcp_environment",
            },
        })

        entry = streamer._parse_tool_entry(line, "tool")

        self.assertIsNotNone(entry)
        self.assertEqual(entry.details["proxy_policy"], "prefer")
        self.assertIs(entry.details["proxy_used"], True)
        self.assertEqual(entry.details["proxy_slot"], "LOCAL_PROXY")
        self.assertEqual(entry.details["proxy_basis"], "mcp_environment")

    def test_tool_entry_labels_unmanaged_proxy_state_unknown(self):
        streamer = LogStreamer(lambda entry: None)
        line = json.dumps({
            "tool": "mcp_fetch_fetch",
            "result": {"ok": True, "speech": "Fetched"},
            "proxy": {
                "policy": "inherit",
                "used": None,
                "basis": "mcp_environment",
                "direct_reason": "unmanaged",
            },
        })

        entry = streamer._parse_tool_entry(line, "tool")

        self.assertIsNotNone(entry)
        self.assertEqual(entry.details["proxy_used"], "unknown")
        self.assertEqual(entry.details["proxy_direct_reason"], "unmanaged")


if __name__ == "__main__":
    unittest.main()
