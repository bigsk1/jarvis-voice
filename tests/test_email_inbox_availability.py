"""Inbox dependencies use shared registry availability and normal stale-row sync."""

import ast
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from config_loader import config_scope  # noqa: E402
from mcp_client import server_configuration_status  # noqa: E402
from tool_availability import check_tool_availability  # noqa: E402
from tool_schema import ToolRegistry  # noqa: E402

MANIFEST = json.loads((ROOT / "skills/email_inbox.tool.json").read_text())
REQUIRED = MANIFEST["availability"]["requires_tools"]
TOOLS = [
    {
        "name": name.removeprefix("mcp_google_workspace_"),
        "description": "Gmail tool",
        "inputSchema": {"type": "object", "properties": {}},
    }
    for name in REQUIRED
]


@pytest.fixture
def registry_factory(tmp_path, monkeypatch):
    import tool_availability
    import tool_profiles

    skills = tmp_path / "skills"
    skills.mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "config/contacts.json").write_text("{}")
    (skills / "email_inbox.tool.json").write_text(json.dumps(MANIFEST))
    (skills / "unrelated.tool.json").write_text(json.dumps({"name": "unrelated", "enabled": True}))
    mcp_path = tmp_path / "mcp.json"
    mcp_path.write_text("{}")
    monkeypatch.setattr(tool_availability, "get_project_root", lambda: tmp_path)
    client = SimpleNamespace(
        tool_defaults={}, proxy_policy="off", transport_type="http", stop=Mock()
    )

    def make(enabled="true", overrides=None, offline=False, blocked=""):
        monkeypatch.setattr(tool_profiles, "load_active_profile_overrides", lambda: overrides or {})

        def discover(registry):
            if (
                not offline
                and server_configuration_status({"enabled_env": "GOOGLE_WORKSPACE_MCP_ENABLED"})[0]
            ):
                registry._register_mcp_tools("google_workspace", client, {}, TOOLS)

        monkeypatch.setattr(ToolRegistry, "_discover_mcp_tools", discover)
        with config_scope(
            "cloud",
            overrides={
                "GOOGLE_WORKSPACE_MCP_ENABLED": enabled,
                "GOOGLE_ACCOUNT": "dedicated@example.test",
                "GOOGLE_WORKSPACE_MCP_TOKEN": "test-service-token",
                "JARVIS_TOOL_PROFILE": "default",
                "BLOCKED_TOOLS": blocked,
            },
        ):
            return ToolRegistry(str(skills), str(mcp_path))

    return make, client


@pytest.mark.parametrize("enabled", ["false", "0", "off", "", "not-a-boolean"])
def test_workspace_flag_off_hides_inbox_despite_credentials_and_contacts(registry_factory, enabled):
    make, _ = registry_factory
    registry = make(enabled=enabled)
    assert "email_inbox" not in registry.list_tools()
    assert "unrelated" in registry.list_tools()
    assert (
        "enabled: GOOGLE_WORKSPACE_MCP_ENABLED" in registry.unavailable_tools["email_inbox"].missing
    )


@pytest.mark.parametrize("dependency", REQUIRED)
def test_each_profile_disabled_gmail_tool_hides_inbox_even_when_forced_on(
    registry_factory, dependency
):
    make, _ = registry_factory
    registry = make(overrides={dependency: False, "email_inbox": True})
    assert "email_inbox" not in registry.list_tools()
    assert f"tool: {dependency}" in registry.unavailable_tools["email_inbox"].missing


def test_configured_and_discovered_dependencies_enable_inbox(registry_factory):
    make, _ = registry_factory
    registry = make()
    assert "email_inbox" in registry.list_tools()
    assert "email_inbox" not in registry.unavailable_tools


def test_blocked_dependency_hides_inbox(registry_factory):
    make, _ = registry_factory
    registry = make(blocked=REQUIRED[0])
    assert "email_inbox" not in registry.list_tools()


def test_temporary_mcp_failure_hides_inbox_and_recovery_restores_its_tool_rag_row(
    registry_factory, monkeypatch
):
    import mcp_client
    import memory_db

    make, client = registry_factory
    registry = make(offline=True)
    assert "email_inbox" not in registry.list_tools()
    registry.mcp_unavailable = {"google_workspace": "offline"}
    registry.mcp_manager = SimpleNamespace(servers={"google_workspace": client})
    registry._mcp_server_config = {
        "google_workspace": {"retry_discovery": True, "enabled_env": "GOOGLE_WORKSPACE_MCP_ENABLED"}
    }
    db = Mock()
    monkeypatch.setattr(mcp_client, "probe_remote_tools", lambda *args, **kwargs: TOOLS)
    monkeypatch.setattr(memory_db, "get_memory_db", lambda: db)
    with config_scope(
        "cloud",
        overrides={
            "GOOGLE_WORKSPACE_MCP_ENABLED": "true",
            "GOOGLE_ACCOUNT": "dedicated@example.test",
            "GOOGLE_WORKSPACE_MCP_TOKEN": "test-service-token",
            "BLOCKED_TOOLS": "",
        },
    ):
        registry.recover_unavailable_mcp()
    assert "email_inbox" in registry.list_tools()
    assert "email_inbox" not in registry.unavailable_tools
    assert "email_inbox" in {tool.name for tool in db.register_recovered_tools.call_args.args[0]}


def test_dependency_metadata_needs_a_catalog_and_respects_mode_scope():
    manifest = {
        "availability": {"enabled_env": "TEST_WORKSPACE_FLAG", "requires_tools": ["read_mail"]}
    }
    with config_scope("cloud", overrides={"TEST_WORKSPACE_FLAG": "true"}):
        assert check_tool_availability(manifest).status == "unknown"
        assert check_tool_availability(manifest, available_tools={"read_mail"}).available
        with config_scope("local", overrides={"TEST_WORKSPACE_FLAG": "false"}):
            assert not check_tool_availability(manifest, available_tools={"read_mail"}).available


@pytest.mark.parametrize(
    "metadata",
    [
        {"enabled_env": []},
        {"enabled_env": ""},
        {"requires_tools": []},
        {"requires_tools": "read_mail"},
    ],
)
def test_malformed_dependency_metadata_fails_closed(metadata):
    assert not check_tool_availability(
        {"availability": metadata}, available_tools={"read_mail"}
    ).available


def test_sync_disables_stale_inbox_row_using_the_actual_filtered_registry(registry_factory):
    make, _ = registry_factory
    registry = make(enabled="false")
    # Load only the existing deterministic SQL cleanup helper, without importing
    # or invoking the production-only embedding/sync CLI in the development venv.
    tree = ast.parse((ROOT / "bin/sync-tools.py").read_text())
    node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_disable_stale_tools"
    )
    namespace = {}
    exec(
        compile(ast.Module(body=[node], type_ignores=[]), "sync-stale-tools-test", "exec"),
        namespace,
    )
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(
        "CREATE TABLE tool_definitions(name TEXT PRIMARY KEY, enabled INTEGER, updated_at TEXT)"
    )
    db.executemany(
        "INSERT INTO tool_definitions VALUES (?,1,NULL)", [("email_inbox",), ("unrelated",)]
    )
    assert (
        namespace["_disable_stale_tools"](
            SimpleNamespace(conn=db), set(registry.list_tools()), False
        )
        == 1
    )
    assert dict(db.execute("SELECT name,enabled FROM tool_definitions")) == {
        "email_inbox": 0,
        "unrelated": 1,
    }
    db.close()


def test_unknown_requirement_typo_cannot_be_hidden_by_valid_credentials():
    with config_scope("cloud", overrides={"TEST_CREDENTIAL": "configured"}):
        result = check_tool_availability(
            {
                "availability": {
                    "all_of_env": ["TEST_CREDENTIAL"],
                    "require_tools": ["missing"],
                }
            }
        )
    assert result.status == "unavailable"
    assert "<invalid availability metadata>" in result.missing


def test_request_exclusions_hide_dependent_without_mutating_shared_registry(registry_factory):
    from executor import ToolExecutor

    make, client = registry_factory
    registry = make()
    executor = ToolExecutor.__new__(ToolExecutor)
    executor.registry = registry
    executor.allowed_tools = None
    executor.excluded_tools = {REQUIRED[0]}
    assert "email_inbox" in executor._effective_exclusions()
    assert not executor.execute("email_inbox", {"action": "poll"})["ok"]
    assert "email_inbox" in registry.list_tools()
    client.stop.assert_not_called()
    executor.excluded_tools = set()
    with config_scope(
        "cloud",
        overrides={
            "GOOGLE_WORKSPACE_MCP_ENABLED": "true",
            "GOOGLE_ACCOUNT": "dedicated@example.test",
            "GOOGLE_WORKSPACE_MCP_TOKEN": "test-service-token",
        },
    ):
        assert "email_inbox" not in executor._effective_exclusions()


def test_dependency_chains_resolve_but_cycles_do_not():
    from tool_availability import resolve_tool_dependencies

    manifests = {
        "first": {"availability": {"requires_tools": ["base"]}},
        "second": {"availability": {"requires_tools": ["first"]}},
        "self": {"availability": {"requires_tools": ["self"]}},
        "cycle_a": {"availability": {"requires_tools": ["cycle_b"]}},
        "cycle_b": {"availability": {"requires_tools": ["cycle_a"]}},
    }
    results = resolve_tool_dependencies(manifests, {"base", *manifests})
    assert {name for name, result in results.items() if result.available} == {"first", "second"}
    assert all(
        not result.available
        for result in resolve_tool_dependencies(manifests, set(manifests)).values()
    )
