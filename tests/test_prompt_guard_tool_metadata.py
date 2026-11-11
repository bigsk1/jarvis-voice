"""Guard policy bindings are trusted runtime metadata, across tool boundaries."""

import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import paths  # noqa: E402
from config_loader import config_scope  # noqa: E402
from tool_schema import ToolRegistry, ToolSchema  # noqa: E402

import orchestrator.executor as executor_module  # noqa: E402
from lib import prompt_guard as guard  # noqa: E402
from lib import prompt_guard_policy as policy  # noqa: E402
from lib import prompt_guard_tool_policy as metadata  # noqa: E402
from lib.prompt_guard_policy import (  # noqa: E402
    export_prompt_guard_context,
    workflow_prompt_guard_scope,
)


def write_manifest(path, *, name="example", policy="web_content"):
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "name": name, "description": "Example tool", "script": "example.py",
        "parameters": {"type": "object", "properties": {}},
        "prompt_guard_policy": policy,
    }
    path.write_text(json.dumps(document))
    return path


def write_policy(path, *, rules=()):
    path.write_text(json.dumps({
        "v": 2, "tools": ["example"], "summarizers": {"enabled": True},
        "policies": {"web_content": .91, "lenient": .99}, "rules": list(rules),
    }))
    return str(path)


def test_local_manifest_policy_stays_outside_every_model_schema(tmp_path):
    path = write_manifest(tmp_path / "example.tool.json")
    schema = ToolSchema.from_json_file(str(path))

    assert schema.prompt_guard_policy == "web_content"
    assert "prompt_guard_policy" not in json.dumps(schema.to_openai_format())
    assert "prompt_guard_policy" not in json.dumps(schema.to_anthropic_format())
    assert "prompt_guard_policy" not in schema.to_ollama_description()
    assert "web_content" not in schema.to_ollama_description()
    assert schema.parameters == {"type": "object", "properties": {}}


@pytest.mark.parametrize("value", [None, .95, True, "", "bad name", "a" * 94, {"threshold": .9}])
def test_invalid_manifest_metadata_keeps_ordinary_policy(tmp_path, value):
    path = write_manifest(tmp_path / "example.tool.json", policy=value)
    assert ToolSchema.from_json_file(str(path)).prompt_guard_policy is None


def test_only_operator_mcp_metadata_can_choose_a_policy():
    reported = {
        "name": "search", "description": "Remote search", "inputSchema": {"type": "object"},
        "prompt_guard_policy": "lenient",
        "annotations": {"prompt_guard_policy": "lenient"},
        "_meta": {"prompt_guard_policy": "lenient"},
    }
    client = SimpleNamespace(tool_defaults={})
    schema = ToolRegistry.schema_from_mcp_tool("example", client, {}, reported)
    assert schema.prompt_guard_policy is None

    configured = {"tool_metadata": {"search": {"prompt_guard_policy": "web_content"}}}
    schema = ToolRegistry.schema_from_mcp_tool("example", client, configured, reported)
    assert schema.prompt_guard_policy == "web_content"
    assert "prompt_guard_policy" not in json.dumps(schema.to_openai_format())
    assert reported["prompt_guard_policy"] == "lenient"


@pytest.mark.parametrize("tool_name", ["search-actors", "fetch-actor-details"])
@pytest.mark.parametrize("configured,expected", [
    ({"prompt_guard_policy": "web_content"}, "web_content"),
    ({"prompt_guard_policy": "web_content", "tool_metadata": {
        "search-actors": {"prompt_guard_policy": "lenient"},
        "fetch-actor-details": {"prompt_guard_policy": "lenient"},
    }}, "lenient"),
    ({"prompt_guard_policy": "web_content", "tool_metadata": {
        "search-actors": {"prompt_guard_policy": "invalid policy"},
        "fetch-actor-details": {"prompt_guard_policy": None},
    }}, "web_content"),
    ({"prompt_guard_policy": "web_content", "tool_metadata": []}, "web_content"),
    ({"prompt_guard_policy": 0.95, "tool_metadata": {
        "search-actors": {"prompt_guard_policy": "lenient"},
        "fetch-actor-details": {"prompt_guard_policy": "lenient"},
    }}, "lenient"),
    ({"prompt_guard_policy": "future_policy"}, "future_policy"),
    ({"prompt_guard_policy": {"threshold": 0.95}}, None),
    ({}, None),
])
def test_mcp_registry_and_standalone_resolution_share_trusted_server_inheritance(
    tmp_path, monkeypatch, tool_name, configured, expected,
):
    monkeypatch.setattr(paths, "get_project_root", lambda: tmp_path)
    path = tmp_path / "config/mcp-servers.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"mcpServers": {"example_server": {"enabled": True, **configured}}}))
    reported = {
        "name": tool_name, "description": "Remote search", "inputSchema": {"type": "object"},
        "prompt_guard_policy": "REMOTE_UNTRUSTED_POLICY",
        "annotations": {"prompt_guard_policy": "REMOTE_UNTRUSTED_POLICY"},
        "_meta": {"prompt_guard_policy": "REMOTE_UNTRUSTED_POLICY"},
    }
    schema = ToolRegistry.schema_from_mcp_tool(
        "example_server", SimpleNamespace(tool_defaults={}), configured, reported,
    )
    assert schema.prompt_guard_policy == expected
    assert metadata.resolve_tool_policy_name(f"mcp_example_server_{tool_name}") == expected
    assert "prompt_guard_policy" not in json.dumps(schema.to_openai_format())
    assert "prompt_guard_policy" not in json.dumps(schema.to_anthropic_format())
    assert "REMOTE_UNTRUSTED_POLICY" not in schema.to_ollama_description()


def test_standalone_mcp_server_default_hot_reloads_and_matches_configured_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "get_project_root", lambda: tmp_path)
    path = tmp_path / "config/mcp-servers.json"
    path.parent.mkdir()
    document = {"mcpServers": {
        "example": {"enabled": True, "prompt_guard_policy": "short_server_policy"},
        "example_server": {"enabled": True, "prompt_guard_policy": "long_server_policy"},
    }}
    path.write_text(json.dumps(document))
    assert metadata.resolve_tool_policy_name("mcp_example_search-actors") == "short_server_policy"
    assert metadata.resolve_tool_policy_name("mcp_example_server_search-actors") == "long_server_policy"
    assert metadata.resolve_tool_policy_name("mcp_example_server_") is None
    assert metadata.resolve_tool_policy_name("mcp_exampleserver_search-actors") is None
    document["mcpServers"]["example_server"] = {"enabled": True}
    path.write_text(json.dumps(document))
    assert metadata.resolve_tool_policy_name("mcp_example_server_search-actors") is None
    document["mcpServers"]["example_server"]["prompt_guard_policy"] = "changed"
    path.write_text(json.dumps(document))
    assert metadata.resolve_tool_policy_name("mcp_example_server_search-actors") == "changed"


@pytest.mark.parametrize("longer_activation,expected", [
    ({"enabled": False}, "web_content"),
    ({}, "high_risk"),
    ({"enabled": True}, "high_risk"),
])
def test_disabled_longer_mcp_server_cannot_shadow_active_shorter_owner(
    tmp_path, monkeypatch, longer_activation, expected,
):
    monkeypatch.setattr(paths, "get_project_root", lambda: tmp_path)
    path = tmp_path / "config/mcp-servers.json"
    path.parent.mkdir()
    shorter = {"enabled": True, "prompt_guard_policy": "web_content"}
    longer = {**longer_activation, "prompt_guard_policy": "high_risk"}
    path.write_text(json.dumps({"mcpServers": {
        "example": shorter, "example_server": longer,
    }}))
    # The same composed name can mean example/server_search or
    # example_server/search; only discoverable owners may claim it.
    owner, tool, config = (
        ("example_server", "search", longer) if longer_activation.get("enabled", True)
        else ("example", "server_search", shorter)
    )
    foreground = ToolRegistry.schema_from_mcp_tool(
        owner, SimpleNamespace(tool_defaults={}), config,
        {"name": tool, "description": "Example search", "inputSchema": {"type": "object"}},
    )
    assert foreground.name == "mcp_example_server_search"
    assert foreground.prompt_guard_policy == expected
    assert metadata.resolve_tool_policy_name(foreground.name) == expected


@pytest.mark.parametrize("mode", ["cloud", "local"])
@pytest.mark.parametrize("activation,overrides,enabled", [
    ({}, {}, True),
    ({"enabled": True}, {}, True),
    ({"enabled": False}, {}, False),
    ({"enabled_env": "TEST_MCP_ENABLE"}, {"TEST_MCP_ENABLE": "false"}, False),
    ({"enabled_env": "TEST_MCP_ENABLE"}, {"TEST_MCP_ENABLE": "true"}, True),
    ({"required_env": ["TEST_MCP_TOKEN"]}, {"TEST_MCP_TOKEN": ""}, False),
    ({"required_env": ["TEST_MCP_TOKEN"]}, {"TEST_MCP_TOKEN": "temporary-token"}, True),
])
def test_mcp_enabled_defaults_match_direct_lookup_and_manager_env_gates_stay_enforced(
    tmp_path, monkeypatch, mode, activation, overrides, enabled,
):
    import mcp_client
    import tool_profiles

    monkeypatch.setattr(paths, "get_project_root", lambda: tmp_path)
    path = tmp_path / "config/mcp-servers.json"
    path.parent.mkdir()
    configured = {
        "type": "http", "url": "http://unused-mcp.test", "prompt_guard_policy": "web_content",
        **activation,
    }
    path.write_text(json.dumps({"mcpServers": {"example": configured}}))
    policy_path = write_policy(tmp_path / "guard.json")
    events = []

    class Client:
        def __init__(self, name, *_args, **_kwargs):
            self.name = name
            self.tool_defaults = {}
            events.append("constructed")

        def start(self):
            events.append("started")

        def list_tools(self):
            events.append("discovered")
            return [{"name": "search", "description": "Search", "inputSchema": {"type": "object"}}]

        def stop(self):
            events.append("stopped")

    monkeypatch.setattr(mcp_client, "MCPRemoteClient", Client)
    monkeypatch.setattr(mcp_client.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(ToolRegistry, "_discover_tools", lambda _registry: None)
    monkeypatch.setattr(tool_profiles, "get_active_profile_name", lambda: "default")
    monkeypatch.setattr(tool_profiles, "load_active_profile_overrides", lambda: {})
    monkeypatch.setattr(tool_profiles, "warn_missing_profile_file", lambda: None)
    with config_scope(mode, {"PROMPT_GUARD_POLICY_FILE": policy_path, **overrides}):
        assert mcp_client.server_configuration_status(configured)[0] is enabled
        registry = ToolRegistry(str(tmp_path / "skills"), str(path))
        assert ("example" in registry.mcp_manager.servers) is enabled
        schema = registry.get_tool("mcp_example_search")
        assert (schema is not None) is enabled
        if "enabled_env" not in configured and "required_env" not in configured:
            # Direct metadata lookup shares enabled's default, while the
            # manager separately owns its existing runtime configuration gates.
            assert metadata.resolve_tool_policy_name("mcp_example_search") == (
                "web_content" if enabled else None
            )
            assert policy.is_tool_selected("mcp_example_search") is enabled
        if schema is not None:
            assert schema.prompt_guard_policy == "web_content"
    assert events == (["constructed", "started", "discovered"] if enabled else [])


def test_direct_mcp_policy_lookup_supports_package_only_import_without_lib_path(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {"example": {"prompt_guard_policy": "web_content"}}}))
    code = (
        "import sys; from pathlib import Path; "
        f"sys.path.insert(0, {str(ROOT)!r}); "
        "from lib.prompt_guard_tool_policy import _mcp_policy_name; "
        f"assert {str(ROOT / 'lib')!r} not in sys.path; "
        "print(_mcp_policy_name('mcp_example_search', Path(sys.argv[1])))"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(path)], cwd=tmp_path,
        check=True, text=True, capture_output=True, timeout=10,
    )
    assert result.stdout.strip() == "web_content"


def test_standalone_resolution_uses_same_manifest_owner_and_stash_alias(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "get_project_root", lambda: tmp_path)
    write_manifest(tmp_path / "skills/a.tool.json", name="example", policy="first")
    write_manifest(tmp_path / "skills/auto-tools/b.tool.json", name="example", policy="second")
    write_manifest(tmp_path / "skills/stash.tool.json", name="stash", policy="saved_content")

    assert metadata.resolve_tool_policy_name("example") == "first"
    assert metadata.resolve_tool_policy_name("stash_summary") == "saved_content"
    assert metadata.resolve_tool_policy_name("absent") is None
    assert metadata.resolve_tool_policy_name("../example") is None
    write_manifest(tmp_path / "skills/a.tool.json", name="example", policy="changed")
    assert metadata.resolve_tool_policy_name("example") == "changed"


def test_standalone_mcp_resolution_reads_operator_config_without_discovery(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "get_project_root", lambda: tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    path = config_dir / "mcp-servers.json"
    path.write_text(json.dumps({"mcpServers": {
        "example_server": {
            "enabled": True,
            "tool_metadata": {"search_items": {"prompt_guard_policy": "web_content"}},
        },
    }}))
    assert metadata.resolve_tool_policy_name("mcp_example_server_search_items") == "web_content"
    assert metadata.resolve_tool_policy_name("mcp_example_server_other") is None
    path.write_text("not JSON")
    assert metadata.resolve_tool_policy_name("mcp_example_server_search_items") is None


@pytest.fixture
def scanner(monkeypatch):
    captured = []

    class Response:
        status_code = 200
        headers = {"Content-Type": "application/json"}

        def __init__(self, threshold):
            self.threshold = threshold

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def iter_content(self, _size):
            yield json.dumps({
                "status": "ok", "injection_score": .1, "flagged": False,
                "threshold": self.threshold,
                "coverage": {"complete": True, "truncated": False,
                             "windows_scanned": 1, "windows_total": 1},
            }).encode()

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def post(self, _url, **kwargs):
            captured.append(kwargs["json"])
            return Response(kwargs["json"]["threshold"])

    monkeypatch.setattr(guard.requests, "Session", Session)
    with guard._state_lock:
        guard._states.clear()
    return captured


def scanner_settings(policy):
    return {
        "PROMPT_GUARD_ENABLED": "true", "PROMPT_GUARD_URL": "http://scanner.test:8188",
        "PROMPT_GUARD_API_KEY": "test-only-token", "PROMPT_GUARD_POLICY_FILE": policy,
        "PROMPT_GUARD_THRESHOLD": ".8",
    }


@pytest.mark.parametrize("source_type,source_name", [
    ("tool_result", "example"), ("model_input", "text_summarizer"),
    ("model_input", "stash_summary"), ("tool_result", "mcp_example_search"),
])
def test_result_and_internal_input_scans_share_trusted_policy_fallback(
    tmp_path, monkeypatch, scanner, source_type, source_name,
):
    policy_path = write_policy(tmp_path / "policy.json")
    requested = []
    monkeypatch.setattr(guard, "resolve_tool_policy_name", lambda name: requested.append(name) or "web_content")
    with config_scope("cloud", overrides=scanner_settings(policy_path)):
        result = guard.scan_text("ordinary saved source", source_type=source_type, source_name=source_name)
    assert result.status == "scanned" and result.threshold == .91
    assert requested == [source_name]
    assert scanner[0]["threshold"] == .91


@pytest.mark.parametrize("mode", ["cloud", "local"])
@pytest.mark.parametrize("server_policy,tool_policy,threshold,policy_id", [
    ("web_content", None, .91, "policy:web_content"),
    ("web_content", "lenient", .99, "policy:lenient"),
    ("future_policy", None, .8, "configured_default"),
])
def test_standalone_mcp_scans_resolve_server_defaults_overrides_and_unknown_names(
    tmp_path, monkeypatch, scanner, mode, server_policy, tool_policy, threshold, policy_id,
):
    monkeypatch.setattr(paths, "get_project_root", lambda: tmp_path)
    path = tmp_path / "config/mcp-servers.json"
    path.parent.mkdir()
    configured = {"enabled": True, "prompt_guard_policy": server_policy}
    if tool_policy is not None:
        configured["tool_metadata"] = {"search-actors": {"prompt_guard_policy": tool_policy}}
    path.write_text(json.dumps({"mcpServers": {"example_server": configured}}))
    policy_path = write_policy(tmp_path / "policy.json")
    with config_scope(mode, overrides=scanner_settings(policy_path)):
        result = guard.scan_text(
            "ordinary returned source", source_type="tool_result",
            source_name="mcp_example_server_search-actors",
        )
    assert result.status == "scanned" and result.threshold == threshold
    assert result.policy_id == policy_id
    assert scanner[0]["threshold"] == threshold


def test_exact_operator_rule_beats_manifest_policy(tmp_path, monkeypatch, scanner):
    policy_path = write_policy(tmp_path / "policy.json", rules=[{
        "id": "specific", "source_type": "model_input", "source_name": "text_summarizer",
        "threshold": .94,
    }])
    monkeypatch.setattr(guard, "resolve_tool_policy_name", lambda _name: "web_content")
    with config_scope("cloud", overrides=scanner_settings(policy_path)):
        result = guard.scan_text("ordinary source", source_type="model_input", source_name="text_summarizer")
    assert result.status == "scanned" and result.threshold == .94
    assert result.policy_id == "specific"


def test_child_scan_restores_workflow_exception_and_mode_boundary(tmp_path, monkeypatch, scanner):
    policy_path = write_policy(tmp_path / "policy.json", rules=[{
        "id": "rss_input", "source_type": "model_input", "source_name": "text_summarizer",
        "workflow_id": "rss_digest", "profile": "ai_status", "threshold": .96,
    }])
    monkeypatch.setattr(guard, "resolve_tool_policy_name", lambda _name: "web_content")
    with config_scope("cloud"), workflow_prompt_guard_scope(
        mode="cloud", workflow_id="rss_digest", profile="ai_status",
    ):
        snapshot = export_prompt_guard_context()
    monkeypatch.setenv("JARVIS_INTERNAL_PROMPT_GUARD_CONTEXT", snapshot)
    for mode, threshold in (("cloud", .96), ("local", .91)):
        with config_scope(mode, overrides=scanner_settings(policy_path)):
            result = guard.scan_text("source", source_type="model_input", source_name="text_summarizer")
            assert result.status == "scanned" and result.threshold == threshold
            assert export_prompt_guard_context() is None


@pytest.mark.parametrize("restricted", [False, True])
@pytest.mark.parametrize("workflow", [False, True])
def test_executor_owns_child_context_and_result_policy(tmp_path, monkeypatch, restricted, workflow):
    monkeypatch.syspath_prepend(str(ROOT / "orchestrator"))
    script = tmp_path / "example.py"
    script.write_text("# execution is mocked\n")
    schema = ToolSchema(
        "example", "Example", {"type": "object", "properties": {}}, str(script),
        prompt_guard_policy="web_content",
        child_environment={"mode": "restricted"} if restricted else None,
    )
    registry = SimpleNamespace(get_tool=lambda _name: schema, is_mcp_tool=lambda _name: False)
    monkeypatch.setattr(executor_module, "get_logger", lambda _mode: SimpleNamespace(log_tool_call=lambda **_: None))
    monkeypatch.setattr(executor_module, "export_config_environment", lambda _mode: {
        "PATH": "/usr/bin", "HOME": str(tmp_path), "JARVIS_MODE": "cloud",
        "JARVIS_INTERNAL_PROMPT_GUARD_CONTEXT": "forged ambient context",
        "JARVIS_OVERRIDE_JARVIS_INTERNAL_PROMPT_GUARD_CONTEXT": "forged override",
    })
    captured = {}

    def run(*_args, **kwargs):
        captured.update(kwargs["tool_env"])
        return json.dumps({"ok": True, "data": {"value": "ordinary result"}}), "", False

    reviews = []

    def review(_name, result, **kwargs):
        reviews.append(kwargs)
        return result

    monkeypatch.setattr("tool_process.run_local_process", run)
    monkeypatch.setattr(executor_module, "review_tool_result", review)
    executor = executor_module.ToolExecutor(mode="cloud", registry=registry, load_runtime_config=False)

    @contextmanager
    def scope():
        with config_scope("cloud"), workflow_prompt_guard_scope(
            mode="cloud", workflow_id="rss_digest" if workflow else None, profile="ai_status",
        ):
            yield

    with scope():
        result = executor.execute("example", {
            "prompt_guard_policy": "lenient", "workflow_id": "forged", "profile": "forged",
        })
    assert result["ok"] is True
    assert reviews[0]["policy_name"] == "web_content"
    assert "JARVIS_OVERRIDE_JARVIS_INTERNAL_PROMPT_GUARD_CONTEXT" not in captured
    if workflow:
        assert json.loads(captured["JARVIS_INTERNAL_PROMPT_GUARD_CONTEXT"]) == {
            "v": 1, "mode": "cloud", "workflow_id": "rss_digest", "profile": "ai_status",
        }
    else:
        assert "JARVIS_INTERNAL_PROMPT_GUARD_CONTEXT" not in captured
