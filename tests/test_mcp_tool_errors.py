"""Regression coverage for MCP CallToolResult.isError handling."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from mcp_client import MCPClient, MCPRemoteClient


@pytest.mark.parametrize(
    "client",
    [
        MCPClient("stdio-test", "unused", []),
        MCPRemoteClient("remote-test", "https://example.test/mcp", "streamable-http"),
    ],
    ids=["stdio", "remote"],
)
def test_call_tool_surfaces_mcp_execution_error(client, monkeypatch):
    monkeypatch.setattr(
        client,
        "_send_request",
        lambda *_args, **_kwargs: {
            "content": [{"type": "text", "text": "Rate limit exceeded"}],
            "isError": True,
        },
    )

    result = client.call_tool("search", {"query": "test"})

    assert result["ok"] is False
    assert result["speech"] == "Rate limit exceeded"
    assert result["error"] == "Rate limit exceeded"
    assert result["data"]["isError"] is True
