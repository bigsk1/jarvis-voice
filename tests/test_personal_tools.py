"""Personal manifests use the existing discovery, execution, and Tool RAG paths."""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sqlite3
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "orchestrator"))

import config_loader  # noqa: E402
import tool_availability  # noqa: E402
import tool_profiles  # noqa: E402
from tool_schema import ToolRegistry  # noqa: E402


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_tool(directory: Path, name: str, **extra) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "description": f"{name}: check my private test workshop's blue lantern.",
        "enabled": True,
        "parameters": {"type": "object", "properties": {}},
    }
    manifest.update(extra)
    path = directory / f"{name}.tool.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch):
    """No operator profile, credentials, or network-backed availability checks."""
    monkeypatch.setattr(tool_profiles, "get_active_profile_name", lambda: "test")
    monkeypatch.setattr(tool_profiles, "load_active_profile_overrides", lambda: {})
    monkeypatch.setattr(tool_profiles, "warn_missing_profile_file", lambda: None)
    monkeypatch.setattr(config_loader, "get_config_value", lambda key, default=None: default)
    monkeypatch.setattr(tool_availability, "get_config_value", lambda key, default=None: default)
    monkeypatch.setenv("JARVIS_JSON_MODE", "1")


@pytest.fixture
def tool_tree(tmp_path):
    skills = tmp_path / "skills"
    for directory, name in (
        (skills, "public_sample"),
        (skills / "auto-tools", "generated_sample"),
        (skills / "personal", "personal_sample"),
    ):
        _write_tool(directory, name)
    return skills


def test_registry_keeps_public_and_generated_tools_and_adds_personal(tool_tree):
    registry = ToolRegistry(str(tool_tree))

    assert set(registry.list_tools()) == {
        "public_sample", "generated_sample", "personal_sample",
    }
    personal = registry.get_tool("personal_sample")
    manifest = json.loads((tool_tree / "personal/personal_sample.tool.json").read_text())
    assert personal.description == manifest["description"]
    assert personal.to_openai_format()["function"]["description"] == manifest["description"]
    assert Path(personal.script_path) == tool_tree / "personal/personal_sample.py"


@pytest.mark.parametrize("explicit_script", [False, True])
def test_personal_script_executes_from_its_manifest_directory(tmp_path, monkeypatch, explicit_script):
    import executor as executor_module

    skills = tmp_path / "skills"
    personal = skills / "personal"
    script_name = "custom_runner.py" if explicit_script else "personal_echo.py"
    extra = {"script": script_name} if explicit_script else {}
    _write_tool(personal, "personal_echo", **extra)
    (personal / script_name).write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "args = json.loads(sys.argv[1])\n"
        "print(json.dumps({'ok': True, 'speech': args['message'], "
        "'data': {'script_directory': Path(__file__).parent.name}}))\n",
        encoding="utf-8",
    )
    registry = ToolRegistry(str(skills))
    logger = Mock()
    monkeypatch.setattr(executor_module, "load_config", lambda mode: None)
    monkeypatch.setattr(executor_module, "get_logger", lambda mode: logger)
    monkeypatch.setattr(
        executor_module, "export_config_environment",
        lambda mode: {"PATH": os.defpath, "JARVIS_MODE": mode},
    )
    runner = executor_module.ToolExecutor(mode="cloud", registry=registry)
    runner.skills_dir = skills

    result = runner.execute("personal_echo", {"message": "private fixture works"})

    assert result == {
        "ok": True, "speech": "private fixture works",
        "data": {"script_directory": "personal"},
    }
    logger.log_tool_call.assert_called_once()
    runner.excluded_tools = {"personal_echo"}
    assert runner.execute("personal_echo", {})["error"] == "Tool blocked for this request"
    logger.log_tool_call.assert_called_once()


@pytest.mark.parametrize("subdirectory", ["", "auto-tools", "personal"])
def test_same_manifest_profile_and_availability_gates(tmp_path, monkeypatch, subdirectory):
    skills = tmp_path / "skills"
    directory = skills / subdirectory
    _write_tool(directory, "manifest_disabled", enabled=False)
    _write_tool(directory, "profile_disabled")
    _write_tool(directory, "profile_enabled", enabled=False)
    _write_tool(
        directory, "missing_configuration", enabled=False,
        availability={"all_of_env": ["PERSONAL_TEST_MISSING_KEY"]},
    )
    monkeypatch.setattr(tool_profiles, "load_active_profile_overrides", lambda: {
        "profile_disabled": False,
        "profile_enabled": True,
        "missing_configuration": True,
    })

    registry = ToolRegistry(str(skills))

    assert registry.list_tools() == ["profile_enabled"]
    assert set(registry.unavailable_tools) == {"missing_configuration"}
    assert registry.unavailable_tools["missing_configuration"].missing == [
        "PERSONAL_TEST_MISSING_KEY",
    ]


def test_manage_tools_lists_and_toggles_personal_manifest(tool_tree, monkeypatch, capsys):
    manage = _load_script("personal_tools_manage_test", ROOT / "bin/manage-tools.py")
    monkeypatch.setattr(manage, "get_skills_dir", lambda: tool_tree)
    personal_manifest = tool_tree / "personal/personal_sample.tool.json"

    assert manage.resolve_tool_file(tool_tree, "personal_sample") == personal_manifest
    assert len(list(manage.iter_tool_files(tool_tree))) == 3
    manage.list_tools()
    output = capsys.readouterr().out
    assert all(name in output for name in ("public_sample", "generated_sample", "personal_sample"))
    manage.disable_tool("personal_sample")
    assert json.loads(personal_manifest.read_text())["enabled"] is False
    assert "personal_sample" not in ToolRegistry(str(tool_tree)).list_tools()
    manage.enable_tool("personal_sample")
    assert json.loads(personal_manifest.read_text())["enabled"] is True
    assert "personal_sample" in ToolRegistry(str(tool_tree)).list_tools()


def test_web_discovery_exposes_personal_description_and_existing_blocking(tool_tree, monkeypatch):
    from server_package_utils import load_server_package

    load_server_package("jarvis_web_personal_tools_test", ROOT / "jarvis-web/server")
    web = importlib.import_module("jarvis_web_personal_tools_test.services.tool_discovery")
    monkeypatch.setitem(sys.modules, "memory_db", SimpleNamespace(
        get_memory_db=lambda: SimpleNamespace(get_enabled_tool_names=lambda: []),
    ))
    monkeypatch.setattr(web.ToolDiscoveryService, "_run_in_mode_scope", lambda self: nullcontext())
    monkeypatch.setattr(web, "get_web_setting", lambda key, default: ["personal_sample"])

    service = web.ToolDiscoveryService(skills_path=tool_tree, mode="cloud")
    personal = service.get_tool("personal_sample")

    assert personal["source"] == "local"
    assert personal["file"] == str(tool_tree / "personal/personal_sample.tool.json")
    assert "private test workshop" in personal["description"]
    assert personal["blocked"] is True
    assert personal["enabled"] is False
    monkeypatch.setattr(web, "get_web_setting", lambda key, default: [])
    service.refresh()
    assert service.get_tool("personal_sample")["enabled"] is True


@pytest.mark.parametrize("owner_directory", ["", "auto-tools"])
@pytest.mark.parametrize("owner_enabled", [False, True])
def test_collision_owner_agrees_across_runtime_web_and_management(
    tmp_path, monkeypatch, caplog, owner_directory, owner_enabled,
):
    from server_package_utils import load_server_package

    skills = tmp_path / "skills"
    owner = _write_tool(skills / owner_directory, "same_name", enabled=owner_enabled)
    duplicate = _write_tool(skills / "personal", "same_name", description="PRIVATE_DUPLICATE")
    duplicate_before = duplicate.read_bytes()
    _write_tool(skills / "personal/nested", "nested_tool")
    registry = ToolRegistry(str(skills))
    assert (registry.get_tool("same_name") is not None) is owner_enabled
    if owner_enabled:
        assert Path(registry.get_tool("same_name").script_path).parent == owner.parent
    assert registry.get_tool("nested_tool") is None
    assert "Ignoring duplicate tool name" in caplog.text

    load_server_package("jarvis_web_personal_tools_test", ROOT / "jarvis-web/server")
    web = importlib.import_module("jarvis_web_personal_tools_test.services.tool_discovery")
    monkeypatch.setitem(sys.modules, "memory_db", SimpleNamespace(
        get_memory_db=lambda: SimpleNamespace(
            get_enabled_tool_names=lambda: ["same_name"],
            get_tool_definition=lambda name: {"description": "STALE_PRIVATE_DUPLICATE"},
        ),
    ))
    monkeypatch.setattr(web.ToolDiscoveryService, "_run_in_mode_scope", lambda self: nullcontext())
    monkeypatch.setattr(web, "get_web_setting", lambda key, default: [])
    service = web.ToolDiscoveryService(skills_path=skills, mode="cloud")
    assert service.get_tool("nested_tool") is None
    if owner_enabled:
        assert service.get_tool("same_name")["file"] == str(owner)
    else:
        assert service.get_tool("same_name") is None  # Stale DB cannot revive it.

    manage = _load_script("personal_collision_manage_test", ROOT / "bin/manage-tools.py")
    monkeypatch.setattr(manage, "get_skills_dir", lambda: skills)
    assert manage.resolve_tool_file(skills, "same_name") == owner
    manage.enable_tool("same_name")
    assert json.loads(owner.read_text())["enabled"] is True
    manage.disable_tool("same_name")
    assert json.loads(owner.read_text())["enabled"] is False
    assert duplicate.read_bytes() == duplicate_before


def test_invalid_private_manifest_and_reserved_mcp_name_do_not_load(tmp_path, caplog):
    skills = tmp_path / "skills"
    personal = skills / "personal"
    _write_tool(personal, "mcp_example_tool")
    _write_tool(personal, "valid_private_tool")
    (personal / "malformed.tool.json").write_text("not JSON")
    registry = ToolRegistry(str(skills))
    assert registry.list_tools() == ["valid_private_tool"]
    assert "reserved for MCP tools" in caplog.text
    assert "Skipping invalid tool manifest" in caplog.text


class _ToolSyncDB:
    """Only the sync DB contract, with no embedding provider or persistent files."""

    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            "CREATE TABLE tool_definitions (name TEXT PRIMARY KEY, description TEXT, "
            "schema_json TEXT, enabled INTEGER, updated_at TEXT)"
        )

    def upsert_tool(self, *, name, description, schema_json, enabled, **kwargs):
        self.conn.execute(
            "INSERT OR REPLACE INTO tool_definitions "
            "(name, description, schema_json, enabled) VALUES (?, ?, ?, ?)",
            (name, description, schema_json, enabled),
        )
        return "updated"


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_sync_indexes_personal_description_and_disables_removed_tools(tool_tree, monkeypatch, mode):
    db = _ToolSyncDB()
    get_db = Mock(return_value=db)
    monkeypatch.setitem(sys.modules, "memory_db", SimpleNamespace(get_memory_db=get_db))
    # Only this imported, fully isolated test module bypasses the operator-venv
    # guard. Its real registry sees temporary manifests; its DB never embeds.
    with monkeypatch.context() as guard:
        guard.setenv("JARVIS_VENV", sys.prefix)
        sync = _load_script("personal_tools_sync_test", ROOT / "bin/sync-tools.py")
    monkeypatch.setattr(sync, "__file__", str(tool_tree.parent / "bin/sync-tools.py"))
    monkeypatch.setattr(sync, "load_config", lambda active_mode: None)
    monkeypatch.setattr(sync, "get_int", lambda key, default: default)
    monkeypatch.setattr(sync, "get_float", lambda key, default: default)

    try:
        assert sync.sync_tools(mode, verbose=False) == {}
        get_db.assert_called_once_with(mode)
        rows = {row["name"]: row for row in db.conn.execute("SELECT * FROM tool_definitions")}
        assert set(rows) == {"public_sample", "generated_sample", "personal_sample"}
        personal = rows["personal_sample"]
        assert personal["enabled"] == 1
        assert "private test workshop" in personal["description"]
        assert json.loads(personal["schema_json"])["function"]["description"] == personal["description"]

        (tool_tree / "personal/personal_sample.tool.json").unlink()
        sync.sync_tools(mode, verbose=False)
        assert db.conn.execute(
            "SELECT enabled FROM tool_definitions WHERE name = 'personal_sample'",
        ).fetchone()["enabled"] == 0
        assert db.conn.execute(
            "SELECT COUNT(*) FROM tool_definitions WHERE enabled = 1",
        ).fetchone()[0] == 2
    finally:
        db.conn.close()
