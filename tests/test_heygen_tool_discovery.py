"""Web discovery hides opt-in HeyGen metadata without stale-cache resurrection."""

import importlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
HEYGEN_NAMES = {"heygen", "generate_avatar_video"}


@pytest.fixture
def discovery(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.syspath_prepend(str(ROOT / "lib"))
    load_server_package("heygen_discovery_test_server", ROOT / "jarvis-web/server")
    module = importlib.import_module("heygen_discovery_test_server.services.tool_discovery")
    import memory_db
    import tool_availability
    import tool_manifest_files
    from config_loader import get_active_config_mode

    raw = {name: json.loads((ROOT / "skills" / f"{name}.tool.json").read_text())
           for name in (*HEYGEN_NAMES, "generate_video")}
    raw["unavailable_other"] = {
        "name": "unavailable_other", "enabled": True, "description": "Keep credential diagnostics",
        "availability": {"all_of_env": ["OTHER_KEY"], "setup_hint": "Set OTHER_KEY"},
    }
    state = {"keys": {"cloud": "", "local": ""}, "provider_keys": {"XAI_API_KEY": "test-xai"},
             "blocked": [], "profiles": {"cloud": {}, "local": {}}}
    db = Mock()
    db.get_enabled_tool_names.return_value = [*HEYGEN_NAMES, "generate_video", "unavailable_other", "mcp_demo_lookup"]
    db.get_tool_definition.side_effect = lambda name: {"description": f"Stale database {name}"}
    manifests = Mock(side_effect=lambda _: iter((tmp_path / f"{name}.tool.json", value) for name, value in raw.items()))
    monkeypatch.setattr(memory_db, "get_memory_db", Mock(return_value=db))
    monkeypatch.setattr(tool_manifest_files, "iter_tool_manifests", manifests)
    monkeypatch.setattr(module, "get_web_setting", lambda *_: state["blocked"])
    monkeypatch.setattr(module, "_tool_profile_overrides", lambda: state["profiles"][get_active_config_mode()])

    def config_value(key, default=""):
        if key == "HEYGEN_API_KEY":
            return state["keys"][get_active_config_mode()]
        return {"VIDEO_TOOL_PROVIDER": "xai", **state["provider_keys"]}.get(key, default)

    monkeypatch.setattr(tool_availability, "get_config_value", config_value)
    module.reset_tool_services()
    yield SimpleNamespace(module=module, state=state, raw=raw, db=db, manifests=manifests, path=tmp_path)
    module.reset_tool_services()


def _names(tools):
    return {tool["name"] for tool in tools}


def test_key_absent_hides_optional_tools_on_every_surface_but_keeps_other_diagnostics(discovery):
    service = discovery.module.ToolDiscoveryService(discovery.path, mode="cloud")
    for tools in (service.get_tools(), service.get_tools_summary(), service.get_local_tools(),
                  service.get_mcp_tools(), service.get_blocked_tools()):
        assert not (_names(tools) & HEYGEN_NAMES)
    assert all(service.get_tool(name) is None for name in HEYGEN_NAMES)
    assert service.get_stats() == {"total": 3, "local": 2, "mcp": 1, "enabled": 2, "blocked": 0, "unavailable": 1}
    assert service.get_tool_count() == 2
    assert service.get_tool_count(include_blocked=True) == 3
    other = service.get_tool("unavailable_other")
    assert other["enabled"] is False and other["available"] is False
    assert other["missing"] == ["OTHER_KEY"]
    assert other["setup_hint"] == "Set OTHER_KEY"
    assert other["source"] == "local"
    assert "Stale" not in other["description"]


def test_missing_manifests_do_not_resurrect_key_absent_optional_db_rows(discovery):
    for name in HEYGEN_NAMES:
        discovery.raw.pop(name)
    service = discovery.module.ToolDiscoveryService(discovery.path, mode="cloud")
    assert not (_names(service.get_tools()) & HEYGEN_NAMES)


def test_key_absent_video_projection_removes_only_appended_provider_guidance(discovery):
    before = deepcopy(discovery.raw["generate_video"])
    service = discovery.module.ToolDiscoveryService(discovery.path, mode="cloud")
    video = service.get_tool("generate_video")
    assert video["parameters"]["properties"]["provider"]["enum"] == ["xai", "gemini"]
    assert "heygen" not in json.dumps(video).lower()
    assert video["description"].endswith("Videos save to stash for use with other tools.")
    properties = video["parameters"]["properties"]
    assert "21:9" not in properties["aspect_ratio"]["enum"]
    assert not ({"768p", "2k"} & set(properties["resolution"]["enum"]))
    assert properties["provider"]["description"].endswith("uses VIDEO_TOOL_PROVIDER from config.")
    assert properties["duration"]["description"].endswith("Default: 5 seconds.")
    assert "Gemini supports '16:9'" in properties["aspect_ratio"]["description"]
    assert "Gemini Omni Flash: 720p only." in properties["resolution"]["description"]
    for name in ("prompt", "image_url", "video_url", "negative_prompt", "save", "model"):
        assert properties[name] == before["parameters"]["properties"][name]
    assert discovery.raw["generate_video"] == before


def test_cached_snapshot_refreshes_both_key_transitions_without_key_value_storage(discovery):
    service = discovery.module.ToolDiscoveryService(discovery.path, mode="cloud")
    loads = discovery.manifests.call_count
    discovery.state["keys"]["cloud"] = "test-heygen"
    assert HEYGEN_NAMES <= _names(service.get_tools_summary())
    assert "heygen" in service.get_tool("generate_video")["parameters"]["properties"]["provider"]["enum"]
    properties = service.get_tool("generate_video")["parameters"]["properties"]
    assert "21:9" in properties["aspect_ratio"]["enum"]
    assert {"768p", "2k"} <= set(properties["resolution"]["enum"])
    assert discovery.manifests.call_count == loads + 1
    assert service.get_stats()["total"] == 5
    # Changing the secret itself does not rebuild metadata or retain that secret.
    discovery.state["keys"]["cloud"] = "replacement-secret"
    assert service.get_tool("heygen")["enabled"] is True
    assert discovery.manifests.call_count == loads + 1
    assert "replacement-secret" not in json.dumps(service.get_tools())
    discovery.state["keys"]["cloud"] = ""
    assert service.get_tool("heygen") is None
    assert service.get_stats()["total"] == 3
    assert discovery.manifests.call_count == loads + 2
    assert "heygen" not in json.dumps(service.get_tool("generate_video")).lower()
    properties = service.get_tool("generate_video")["parameters"]["properties"]
    assert "21:9" not in properties["aspect_ratio"]["enum"]
    assert not ({"768p", "2k"} & set(properties["resolution"]["enum"]))


def test_no_video_keys_keeps_only_existing_provider_diagnostics_without_mutating_raw_manifest(discovery):
    discovery.state["provider_keys"].clear()
    before = deepcopy(discovery.raw["generate_video"])
    service = discovery.module.ToolDiscoveryService(discovery.path, mode="cloud")
    video = service.get_tool("generate_video")
    assert video["available"] is False
    assert video["missing"] == ["any provider of: gemini, xai"]
    assert "heygen" not in json.dumps(video).lower()
    assert "heygen" not in json.dumps(service.get_tools_summary()).lower()
    assert discovery.raw["generate_video"] == before
    assert "heygen" in before["availability"]["provider_requirements"]


@pytest.mark.parametrize("getter", ["get_tools", "get_tool", "get_tools_summary", "get_stats", "get_tool_count",
                                    "get_mcp_tools", "get_local_tools", "get_blocked_tools"])
def test_every_getter_refreshes_key_gate_before_using_cached_metadata(discovery, getter):
    discovery.state["keys"]["cloud"] = "test-key"
    service = discovery.module.ToolDiscoveryService(discovery.path, mode="cloud")
    discovery.state["keys"]["cloud"] = ""
    method = getattr(service, getter)
    method("heygen") if getter == "get_tool" else method()
    assert not (set(service.tools) & HEYGEN_NAMES)


def test_cloud_local_snapshots_and_manifest_projection_never_leak(discovery):
    from config_loader import config_scope

    discovery.state["keys"]["cloud"] = "cloud-test-key"
    # Pass explicit paths to construction without changing production defaults.
    cloud = discovery.module.ToolDiscoveryService(discovery.path, mode="cloud")
    local = discovery.module.ToolDiscoveryService(discovery.path, mode="local")
    with config_scope("local"):
        assert HEYGEN_NAMES <= _names(cloud.get_tools())
        assert not (_names(local.get_tools()) & HEYGEN_NAMES)
    with config_scope("cloud"):
        assert "heygen" in cloud.get_tool("generate_video")["parameters"]["properties"]["provider"]["enum"]
        assert "heygen" not in local.get_tool("generate_video")["parameters"]["properties"]["provider"]["enum"]
    discovery.state["keys"].update(cloud="", local="local-test-key")
    assert cloud.get_tool("heygen") is None
    assert local.get_tool("heygen")["enabled"] is True
    assert "heygen" in discovery.raw["generate_video"]["parameters"]["properties"]["provider"]["enum"]


def test_profile_and_blocked_semantics_survive_key_gate(discovery):
    discovery.state["keys"]["cloud"] = "test-key"
    discovery.state["profiles"]["cloud"] = {"heygen": False}
    discovery.state["blocked"] = ["generate_avatar_video"]
    service = discovery.module.ToolDiscoveryService(discovery.path, mode="cloud")
    assert service.get_tool("heygen") is None  # Stale DB row cannot bypass profile ownership.
    avatar = service.get_tool("generate_avatar_video")
    assert avatar["blocked"] is True and avatar["enabled"] is False
    assert avatar["available"] is True
    assert "generate_avatar_video" not in _names(service.get_tools(include_blocked=False))
    discovery.state["keys"]["cloud"] = ""
    assert not (_names(service.get_blocked_tools()) & HEYGEN_NAMES)
    assert service.get_stats()["blocked"] == 0


def test_web_tools_and_required_workflow_follow_current_key_gate(discovery, monkeypatch):
    from flask import Flask

    api = importlib.import_module("heygen_discovery_test_server.routes.api")
    services = {mode: discovery.module.ToolDiscoveryService(discovery.path, mode=mode)
                for mode in ("cloud", "local")}
    from config_loader import get_active_config_mode

    monkeypatch.setattr(api, "get_tool_service", lambda mode=None: services[get_active_config_mode(mode)])
    workflow = {"id": "heygen_probe", "name": "Optional video workflow",
                "triggers": {"explicit": ["/heygen_probe"]},
                "steps": [{"step": 1, "tool": "heygen", "inputs": {"action": "account"}}]}
    loader = SimpleNamespace(workflows={"heygen_probe": workflow}, get_workflow=lambda _: workflow)
    monkeypatch.setitem(sys.modules, "workflow_loader", SimpleNamespace(WorkflowLoader=lambda **_: loader))
    app = Flask(__name__)
    app.register_blueprint(api.api_bp)
    client = app.test_client()

    summary = client.get("/api/tools?summary=true&mode=cloud").get_json()
    assert not (_names(summary["tools"]) & HEYGEN_NAMES)
    assert summary["stats"]["total"] == 3
    assert client.get("/api/tools/heygen?mode=cloud").status_code == 404
    assert client.get("/api/tools/generate_avatar_video?mode=cloud").status_code == 404
    assert client.get("/api/workflows?mode=cloud").get_json()["count"] == 0
    assert client.get("/api/workflows/heygen_probe?mode=cloud").status_code == 409

    discovery.state["keys"]["cloud"] = "cloud-test-key"
    assert HEYGEN_NAMES <= _names(client.get("/api/tools?summary=true&mode=cloud").get_json()["tools"])
    assert client.get("/api/tools/heygen?mode=cloud").status_code == 200
    assert client.get("/api/workflows?mode=cloud").get_json()["count"] == 1
    assert client.get("/api/workflows/heygen_probe?mode=cloud").status_code == 200
    assert client.get("/api/workflows?mode=local").get_json()["count"] == 0

    discovery.state["keys"]["cloud"] = ""
    assert client.get("/api/workflows?mode=cloud").get_json()["count"] == 0
    assert not (_names(client.get("/api/tools?mode=cloud").get_json()["tools"]) & HEYGEN_NAMES)
