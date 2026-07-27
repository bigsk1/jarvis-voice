#!/usr/bin/env python3
"""
Test MCP environment variable substitution
"""
import os
import sys

import pytest

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
import config_loader
from config_loader import config_scope
from mcp_client import MCPClient, MCPManager
import mcp_client
from http_client import STANDARD_PROXY_ENV_KEYS


def test_env_substitution():
    """Test that ${VAR_NAME} substitution works correctly."""
    
    # Set test environment variables
    os.environ['TEST_API_KEY'] = 'secret-api-key-12345'
    os.environ['TEST_TOKEN'] = 'token-67890'
    os.environ['ANTHROPIC_API_KEY'] = 'sk-ant-should-not-leak'
    
    # Test case 1: Simple substitution
    client1 = MCPClient(
        name="test1",
        command="echo",
        args=["test"],
        env={
            "API_KEY": "${TEST_API_KEY}",
            "TOKEN": "${TEST_TOKEN}"
        }
    )
    
    env1 = client1._build_env_with_substitution()
    assert env1["API_KEY"] == "secret-api-key-12345", f"Expected 'secret-api-key-12345', got '{env1['API_KEY']}'"
    assert env1["TOKEN"] == "token-67890", f"Expected 'token-67890', got '{env1['TOKEN']}'"
    assert "ANTHROPIC_API_KEY" not in env1, "ANTHROPIC_API_KEY should NOT be in env (security issue!)"
    print("✅ Test 1 passed: Simple substitution works")
    
    # Test case 2: Empty env (secure by default)
    client2 = MCPClient(
        name="test2",
        command="echo",
        args=["test"],
        env={}
    )
    
    env2 = client2._build_env_with_substitution()
    assert len(env2) == 0, f"Expected empty env, got {env2}"
    assert "ANTHROPIC_API_KEY" not in env2, "ANTHROPIC_API_KEY should NOT be in env (security issue!)"
    print("✅ Test 2 passed: Empty env passes nothing (secure)")
    
    # Test case 3: Variable not found (keeps ${} syntax)
    client3 = MCPClient(
        name="test3",
        command="echo",
        args=["test"],
        env={
            "MISSING": "${NONEXISTENT_VAR}"
        }
    )
    
    env3 = client3._build_env_with_substitution()
    assert env3["MISSING"] == "${NONEXISTENT_VAR}", f"Expected '${{NONEXISTENT_VAR}}', got '{env3['MISSING']}'"
    print("✅ Test 3 passed: Missing variables keep ${} syntax")
    
    # Test case 4: Multiple substitutions in one value
    client4 = MCPClient(
        name="test4",
        command="echo",
        args=["test"],
        env={
            "COMBINED": "prefix-${TEST_API_KEY}-middle-${TEST_TOKEN}-suffix"
        }
    )
    
    env4 = client4._build_env_with_substitution()
    expected = "prefix-secret-api-key-12345-middle-token-67890-suffix"
    assert env4["COMBINED"] == expected, f"Expected '{expected}', got '{env4['COMBINED']}'"
    print("✅ Test 4 passed: Multiple substitutions in one value")
    
    # Test case 5: Non-string values are converted to strings
    client5 = MCPClient(
        name="test5",
        command="echo",
        args=["test"],
        env={
            "NUMBER": 12345,
            "BOOL": True
        }
    )
    
    env5 = client5._build_env_with_substitution()
    assert env5["NUMBER"] == "12345", f"Expected '12345', got '{env5['NUMBER']}'"
    assert env5["BOOL"] == "True", f"Expected 'True', got '{env5['BOOL']}'"
    print("✅ Test 5 passed: Non-string values converted")
    
    print("\n🎉 All tests passed!")
    print("\n🔒 Security verification:")
    print(f"   • Empty env = {len(env2)} variables (should be 0)")
    print(f"   • ANTHROPIC_API_KEY leaked? {'❌ YES (BAD!)' if 'ANTHROPIC_API_KEY' in env2 else '✅ NO (GOOD!)'}")
    print(f"   • Only explicit vars passed? ✅ YES")


def test_stdio_env_and_args_follow_request_config_scope(monkeypatch):
    """MCP stdio substitution must not retain the startup mode's value."""
    key = "ZZ_MCP_SCOPED_KEY"
    unrelated = "ZZ_MCP_UNRELATED_SECRET"
    monkeypatch.setenv(key, "stale-startup-value")
    monkeypatch.setenv(unrelated, "must-not-leak")

    client = MCPClient(
        name="scoped",
        command="echo",
        args=["--token", f"${{{key}}}"],
        env={"DECLARED_TOKEN": f"${{{key}}}"},
    )

    with config_scope("cloud", overrides={key: "cloud-value"}):
        assert client._build_env_with_substitution() == {
            "DECLARED_TOKEN": "cloud-value"
        }
        assert client._expand_args() == ["--token", "cloud-value"]

    with config_scope("local", overrides={key: "local-value"}):
        child_env = client._build_env_with_substitution()
        assert child_env == {"DECLARED_TOKEN": "local-value"}
        assert unrelated not in child_env
        assert client._expand_args() == ["--token", "local-value"]


def test_stdio_env_uses_selected_mode_env_file(tmp_path, monkeypatch):
    """A declared placeholder resolves from cloud.env or local.env by mode."""
    key = "ZZ_MCP_MODE_FILE_KEY"
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cloud.env").write_text(f"{key}=cloud-file-value\n")
    (config_dir / "local.env").write_text(f"{key}=local-file-value\n")
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)
    monkeypatch.setenv(key, "stale-startup-value")

    client = MCPClient("mode-file", "echo", [], {"TOKEN": f"${{{key}}}"})
    with config_scope("cloud"):
        assert client._build_env_with_substitution() == {
            "TOKEN": "cloud-file-value"
        }
    with config_scope("local"):
        assert client._build_env_with_substitution() == {
            "TOKEN": "local-file-value"
        }


def test_remote_headers_follow_request_config_scope(tmp_path, monkeypatch):
    """HTTP/SSE headers use the same scoped, explicit-placeholder resolver."""
    key = "ZZ_MCP_REMOTE_SCOPED_KEY"
    monkeypatch.setenv(key, "stale-startup-value")
    config_path = tmp_path / "mcp-servers.json"
    config_path.write_text(
        "{\n"
        '  "mcpServers": {\n'
        '    "remote": {\n'
        '      "type": "http",\n'
        '      "url": "https://example.invalid/mcp",\n'
        f'      "headers": {{"Authorization": "Bearer ${{{key}}}"}}\n'
        "    }\n"
        "  }\n"
        "}\n"
    )

    with config_scope("cloud", overrides={key: "cloud-header"}):
        cloud_manager = MCPManager(str(config_path))
        assert cloud_manager.servers["remote"].headers == {
            "Authorization": "Bearer cloud-header"
        }

    with config_scope("local", overrides={key: "local-header"}):
        local_manager = MCPManager(str(config_path))
        assert local_manager.servers["remote"].headers == {
            "Authorization": "Bearer local-header"
        }


def test_prefer_policy_passes_only_declared_and_derived_proxy_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-leak")
    monkeypatch.setattr(
        mcp_client,
        "get_proxy_url_chain",
        lambda respect_policy=False: [
            "http://proxy-one.test:8001",
            "http://proxy-two.test:8002",
        ],
    )
    monkeypatch.setattr(
        mcp_client,
        "select_reachable_proxy_url",
        lambda urls: (urls[1], "LOCAL_PROXY2"),
    )
    client = MCPClient(
        "duckduckgo",
        "docker",
        ["run", "-i", "image"],
        {"DDG_REGION": "us-en"},
        proxy_policy="prefer",
    )

    child_env = client._build_env_with_substitution()

    assert child_env["DDG_REGION"] == "us-en"
    assert set(child_env) == {"DDG_REGION", *STANDARD_PROXY_ENV_KEYS}
    assert all(
        child_env[key] == "http://proxy-two.test:8002"
        for key in STANDARD_PROXY_ENV_KEYS
    )
    assert "LOCAL_PROXY" not in child_env
    assert "LOCAL_PROXY2" not in child_env
    assert "ANTHROPIC_API_KEY" not in child_env
    assert client._selected_proxy_slot == "LOCAL_PROXY2"


def test_docker_proxy_forwarding_is_limited_to_standard_proxy_env():
    client = MCPClient(
        "duckduckgo",
        "docker",
        ["run", "-i", "-e", "DDG_REGION", "image"],
        proxy_policy="prefer",
    )
    child_env = {
        "DDG_REGION": "us-en",
        "UNRELATED_SECRET": "no",
        **{key: "http://proxy.test:8080" for key in STANDARD_PROXY_ENV_KEYS},
    }

    args = client._inject_docker_proxy_env(client.args, child_env)
    declared = client._declared_docker_env_names(args)

    assert set(STANDARD_PROXY_ENV_KEYS).issubset(declared)
    assert "DDG_REGION" in declared
    assert "UNRELATED_SECRET" not in declared


def test_require_policy_rejects_unreachable_proxy_chain(monkeypatch):
    monkeypatch.setattr(
        mcp_client,
        "get_proxy_url_chain",
        lambda respect_policy=False: ["http://proxy.test:8080"],
    )
    monkeypatch.setattr(mcp_client, "select_reachable_proxy_url", lambda urls: None)
    client = MCPClient("required", "echo", [], proxy_policy="require")

    with pytest.raises(RuntimeError, match="requires a proxy"):
        client._build_env_with_substitution()


def test_proxy_log_metadata_reports_route_without_proxy_url():
    client = MCPClient("ddg", "echo", [], proxy_policy="prefer")
    client._selected_proxy_url = "http://user:secret@proxy.test:8080"
    client._selected_proxy_slot = "LOCAL_PROXY2"

    metadata = client.get_proxy_log_metadata()

    assert metadata == {
        "policy": "prefer",
        "used": True,
        "basis": "mcp_environment",
        "slot": "LOCAL_PROXY2",
    }
    assert "secret" not in str(metadata)
    assert "proxy.test" not in str(metadata)


def test_proxy_log_metadata_reports_prefer_direct_fallback():
    client = MCPClient("ddg", "echo", [], proxy_policy="prefer")

    assert client.get_proxy_log_metadata() == {
        "policy": "prefer",
        "used": False,
        "basis": "mcp_environment",
        "direct_reason": "no_reachable_proxy",
    }


def test_dead_selected_proxy_is_restarted_before_tool_timeout(monkeypatch):
    client = MCPClient("ddg", "echo", [], proxy_policy="prefer")
    client._selected_proxy_url = "http://proxy-one.test:8001"
    client._selected_proxy_slot = "LOCAL_PROXY"
    monkeypatch.setattr(mcp_client, "select_reachable_proxy_url", lambda urls, timeout: None)
    restarted = []
    monkeypatch.setattr(client, "_force_restart", lambda reason: restarted.append(reason))

    client._ensure_proxy_listener()

    assert restarted == ["LOCAL_PROXY listener unavailable before tools/call"]


def test_manager_parses_proxy_policy(tmp_path):
    config_path = tmp_path / "mcp-servers.json"
    config_path.write_text(
        '{"mcpServers":{"ddg":{"command":"echo","proxy_policy":"prefer"}}}\n'
    )

    manager = MCPManager(str(config_path))

    assert manager.servers["ddg"].proxy_policy == "prefer"


if __name__ == "__main__":
    try:
        test_env_substitution()
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
