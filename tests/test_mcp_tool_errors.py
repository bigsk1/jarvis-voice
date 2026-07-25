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


@pytest.mark.parametrize(
    ("tool_name", "error_text"),
    [
        ("fetch_content", "Error: Refusing to fetch a private or loopback address"),
        ("search", "An error occurred while searching: upstream request failed"),
    ],
)
@pytest.mark.parametrize(
    "client",
    [
        MCPClient("duckduckgo", "unused", []),
        MCPRemoteClient("duckduckgo", "https://example.test/mcp", "streamable-http"),
    ],
    ids=["stdio", "remote"],
)
def test_duckduckgo_text_errors_are_normalized(client, tool_name, error_text, monkeypatch):
    monkeypatch.setattr(
        client,
        "_send_request",
        lambda *_args, **_kwargs: {
            "content": [{"type": "text", "text": error_text}],
            "isError": False,
        },
    )

    result = client.call_tool(tool_name, {})

    assert result["ok"] is False
    assert result["speech"] == error_text
    assert result["error"] == error_text
    assert result["data"]["isError"] is True


def test_non_duckduckgo_text_error_remains_successful(monkeypatch):
    client = MCPClient("another-server", "unused", [])
    monkeypatch.setattr(
        client,
        "_send_request",
        lambda *_args, **_kwargs: {
            "content": [{"type": "text", "text": "Error: valid domain-specific output"}],
            "isError": False,
        },
    )

    result = client.call_tool("fetch_content", {})

    assert result["ok"] is True
    assert result["data"]["full_text"] == "Error: valid domain-specific output"
