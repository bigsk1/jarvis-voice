"""Regression coverage for MCP CallToolResult.isError handling."""

import json

import pytest
from config_loader import config_scope
from mcp_client import MCPClient, MCPManager, MCPRemoteClient


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


@pytest.mark.parametrize("remote", [False, True], ids=["stdio", "remote"])
@pytest.mark.parametrize("with_text", [False, True])
def test_legacy_clients_preserve_structured_content_additively(remote, with_text, monkeypatch):
    client = (MCPRemoteClient("example", "https://example.test/mcp", "http") if remote
              else MCPClient("example", "unused", []))
    response = {"structuredContent": {"id": "exact", "values": [False, None]}}
    if with_text:
        response["content"] = [{"type": "text", "text": "Human readable receipt"}]
    monkeypatch.setattr(client, "_send_request", lambda *_args, **_kwargs: response)
    result = client.call_tool("lookup", {})
    assert result["ok"] is True
    assert result["data"]["structuredContent"] == response["structuredContent"]
    assert "contract" not in result["data"]
    if with_text:
        assert result["data"]["full_text"] == "Human readable receipt"
        assert result["data"]["raw"] == response["content"]


@pytest.mark.parametrize("remote", [False, True], ids=["stdio", "remote"])
@pytest.mark.parametrize("failed", [False, True])
def test_explicit_server_contract_reaches_both_clients_and_preserves_errors(tmp_path, monkeypatch, remote, failed):
    server = {"type": "http", "url": "https://example.test/mcp"} if remote else {
        "command": "unused", "args": [],
    }
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {"example": {
        **server, "result_contract": "external_result_v1",
    }}}))
    with config_scope("cloud", {"STASH_DIR": str(tmp_path / "stash")}):
        client = MCPManager(str(path)).servers["example"]
        client._tools_cache = [{"name": "lookup", "outputSchema": {
            "type": "object", "properties": {"id": {"type": "string"}},
        }}]
        response = {"content": [{"type": "text", "text": "Provider failure" if failed else "Receipt"}],
                    "structuredContent": {"id": "native-id"}, "isError": failed}
        monkeypatch.setattr(client, "_send_request", lambda *_args, **_kwargs: response)
        result = client.call_tool("lookup", {})
    assert result["ok"] is not failed
    assert result["data"]["contract"] == "external_result_v1"
    assert result["data"]["execution"]["mcp_is_error"] is failed
    assert result["data"]["result"]["value"] == {"id": "native-id"}
    assert result["data"]["source"]["provider"] == "example"
    assert result["data"]["schema"]["type"] == "object"
    assert result["data"]["raw_ref"].startswith("stash://")
    if failed:
        assert result["error"] == "Provider failure"


def test_unknown_contract_fails_closed_for_only_that_server(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {
        "invalid": {"command": "unused", "result_contract": "unknown"},
        "legacy": {"command": "unused"},
    }}))
    assert list(MCPManager(str(path)).servers) == ["legacy"]
