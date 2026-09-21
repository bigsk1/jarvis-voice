"""Tavily's API, tool output, and conversation handoff contracts."""

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills"))
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "orchestrator"))

import tavily_client
import tavily_extract
import tavily_search
import config_loader
from orchestrator.executor import ToolExecutor
from tool_child_environment import (
    RESTRICTED_ENV_MARKER,
    parse_child_environment_policy,
    restrict_child_environment,
)
from tool_schema import ToolSchema


def test_search_uses_basic_request_and_preserves_cited_sources():
    response = {
        "results": [{
            "title": "Official notes", "url": "https://example.org/notes",
            "content": "A specific release detail.", "score": 0.93,
            "published_date": "2026-09-20",
        }],
        "request_id": "request-1", "usage": {"credits": 1},
    }
    with patch("tavily_search.request_tavily", return_value=response) as request:
        result = tavily_search.search({"query": "release notes", "time_range": "week"})
    assert result["ok"] is True
    assert result["data"]["results"][0]["url"] == "https://example.org/notes"
    assert result["data"]["results"][0]["snippet"] == "A specific release detail."
    assert result["data"]["external_content_trust"] == "untrusted"
    assert request.call_args.args[0] == "search"
    body = request.call_args.args[1]
    assert body["search_depth"] == "basic"
    assert body["include_raw_content"] is False
    assert body["filter_by_published_date"] is True


def test_extract_caps_content_and_handles_per_url_failure():
    with patch("tavily_extract.request_tavily", return_value={
        "results": [{"url": "https://example.org/page", "raw_content": "x" * 1400}],
        "failed_results": [], "request_id": "request-2",
    }) as request:
        result = tavily_extract.extract({"url": "https://example.org/page", "max_chars": 1000})
    assert result["ok"] is True
    assert result["data"]["content_chars"] == 1400
    assert len(result["data"]["content"]) == 1000
    assert result["data"]["content_truncated"] is True
    assert request.call_args.args[1]["urls"] == "https://example.org/page"
    assert request.call_args.args[1]["extract_depth"] == "basic"

    with patch("tavily_extract.request_tavily", return_value={
        "results": [], "failed_results": [{"url": "https://example.org/page", "error": "blocked"}],
    }):
        failed = tavily_extract.extract({"url": "https://example.org/page"})
    assert failed["ok"] is False
    assert "could not be extracted" in failed["error"]


def test_extract_rejects_private_or_credential_urls_before_network():
    with patch("tavily_extract.request_tavily") as request:
        for url in (
            "http://127.0.0.1/", "http://localhost/", "http://192.168.1.2/",
            "https://user:secret@example.org/", "file:///etc/passwd",
        ):
            try:
                tavily_extract.extract({"url": url})
            except ValueError:
                pass
            else:
                raise AssertionError(f"Accepted non-public URL: {url}")
    request.assert_not_called()


def test_client_keeps_key_in_header_and_errors_safe():
    class Response:
        status_code = 200

        def json(self):
            return {"results": []}

    with patch("tavily_client.get_config_value", return_value="private-sentinel"), patch(
        "tavily_client.http_request", return_value=Response()
    ) as request:
        payload = tavily_client.request_tavily("search", {"query": "test"})
    assert payload == {"results": []}
    assert request.call_args.kwargs["headers"]["Authorization"] == "Bearer private-sentinel"
    assert "private-sentinel" not in request.call_args.args[1]

    class ErrorResponse:
        status_code = 401

    with patch("tavily_client.get_config_value", return_value="private-sentinel"), patch(
        "tavily_client.http_request", return_value=ErrorResponse()
    ):
        try:
            tavily_client.request_tavily("search", {"query": "test"})
        except tavily_client.TavilyError as exc:
            assert "private-sentinel" not in str(exc)
            assert "TAVILY_API_KEY" in str(exc)
        else:
            raise AssertionError("Expected TavilyError")


def test_manifests_are_key_gated_and_followups_keep_source_context():
    for name in ("tavily_search", "tavily_extract"):
        manifest = json.loads((ROOT / "skills" / f"{name}.tool.json").read_text())
        assert manifest["availability"]["all_of_env"] == ["TAVILY_API_KEY"]
        assert manifest["proxy_policy"] == "off"
        assert manifest["parameters"]["additionalProperties"] is False

    load_server_package("tavily_followup_server", ROOT / "jarvis-web" / "server")
    path = ROOT / "jarvis-web" / "server" / "services" / "followup_extractor.py"
    spec = importlib.util.spec_from_file_location(
        "tavily_followup_server.services.followup_extractor", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.extract_followup_data({
        "tavily_search": {"data": {
            "query": "release notes", "results": [{
                "title": "Official notes", "url": "https://example.org/notes",
                "snippet": "Specific detail.",
            }],
        }},
        "tavily_extract": {"data": {
            "url": "https://example.org/notes", "content": "A deeper detail.",
        }},
    })
    assert result["tavily_search"]["candidates"][0]["url"] == "https://example.org/notes"
    assert result["tavily_extract"]["content_excerpt"] == "A deeper detail."


def test_extract_cli_loads_mode_config(monkeypatch, capsys):
    loaded = []
    monkeypatch.setattr(tavily_extract, "load_config", lambda: loaded.append(True))
    monkeypatch.setattr(sys, "argv", ["tavily_extract.py", '{"url":"http://127.0.0.1/"}'])
    assert tavily_extract.main() == 1
    assert loaded == [True]
    assert "public webpage URL" in json.loads(capsys.readouterr().out)["error"]


def test_restricted_tool_env_excludes_other_mode_secrets_and_preserves_selected_key():
    source = {
        "PATH": "/usr/bin", "JARVIS_MODE": "cloud",
        "TAVILY_API_KEY": "mode-key",
        "JARVIS_OVERRIDE_TAVILY_API_KEY": "selected-key",
        "OPENAI_API_KEY": "other-secret", "BRAVE_API_KEY": "another-secret",
        "LOCAL_PROXY": "http://proxy-secret", "JARVIS_OVERRIDE_LOCAL_PROXY": "",
    }
    schema = ToolSchema.from_json_file(str(ROOT / "skills" / "tavily_search.tool.json"))
    assert schema.child_environment_names == frozenset({"TAVILY_API_KEY"})
    child = restrict_child_environment(
        source, schema.child_environment_names, home="/tmp/jarvis-test-home", proxy_policy="off"
    )
    assert child["TAVILY_API_KEY"] == "selected-key"
    assert child["JARVIS_MODE"] == "cloud"
    assert child[RESTRICTED_ENV_MARKER] == "1"
    assert child["HOME"] == "/tmp/jarvis-test-home"
    assert not ({"OPENAI_API_KEY", "BRAVE_API_KEY", "LOCAL_PROXY",
                 "JARVIS_OVERRIDE_TAVILY_API_KEY"} & child.keys())


def test_restricted_loader_does_not_rehydrate_mode_file(monkeypatch):
    monkeypatch.setenv(RESTRICTED_ENV_MARKER, "1")
    monkeypatch.setenv("TAVILY_API_KEY", "selected-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(config_loader, "_load_mode_config", lambda *_: (_ for _ in ()).throw(
        AssertionError("restricted child must not reload a mode file")))
    loaded = config_loader.load_config()
    assert loaded["TAVILY_API_KEY"] == "selected-key"
    assert "OPENAI_API_KEY" not in loaded
    assert config_loader.get_config_value("TAVILY_API_KEY") == "selected-key"


def test_child_env_policy_supports_optional_keys_and_rejects_invalid_metadata():
    policy = parse_child_environment_policy(
        {"mode": "restricted", "from_availability": True, "allow": ["OPTIONAL_SETTING"]},
        {"all_of_env": ["TAVILY_API_KEY"]},
    )
    assert policy == frozenset({"TAVILY_API_KEY", "OPTIONAL_SETTING"})
    child = restrict_child_environment(
        {"OPTIONAL_SETTING": "on", "LOCAL_PROXY": "http://proxy", "NO_PROXY": "localhost",
         "JARVIS_TOOL_PROXY_POLICY": "inherit", "JARVIS_OVERRIDE_JARVIS_TOOL_PROXY_POLICY": "require",
         "JARVIS_OVERRIDE_LOCAL_PROXY": "http://selected-proxy", "UNRELATED_KEY": "secret"},
        policy, home="/tmp/jarvis-test-home",
    )
    assert child["OPTIONAL_SETTING"] == "on"
    assert child["LOCAL_PROXY"] == "http://selected-proxy"
    assert child["NO_PROXY"] == "localhost"
    assert child["JARVIS_TOOL_PROXY_POLICY"] == "require"
    assert "UNRELATED_KEY" not in child
    with pytest.raises(ValueError, match="Provider-specific availability"):
        parse_child_environment_policy(
            {"mode": "restricted", "from_availability": True},
            {"provider_requirements": {"x": ["API_KEY"]}},
        )
    with pytest.raises(ValueError, match="invalid environment variable name"):
        parse_child_environment_policy({"mode": "restricted", "allow": ["BAD-NAME"]})


def test_executor_passes_restricted_env_to_tavily_child(monkeypatch):
    schema = ToolSchema.from_json_file(str(ROOT / "skills" / "tavily_search.tool.json"))

    class Registry:
        def get_tool(self, name):
            return schema if name == "tavily_search" else None

        def is_mcp_tool(self, name):
            return False

    source = {"PATH": "/usr/bin", "JARVIS_MODE": "cloud", "TAVILY_API_KEY": "mode-key",
              "JARVIS_OVERRIDE_TAVILY_API_KEY": "selected-key",
              "OPENAI_API_KEY": "other-secret", "LOCAL_PROXY": "http://proxy-secret"}
    monkeypatch.setattr("orchestrator.executor.export_config_environment", lambda *_: source)
    executor = ToolExecutor(mode="cloud", registry=Registry(), load_runtime_config=False)
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs["tool_env"])
        assert Path(captured["HOME"]).is_dir()
        return json.dumps({"ok": True, "speech": "done", "data": {}}), "", False

    with patch("tool_process.run_local_process", side_effect=fake_run):
        result = executor.execute("tavily_search", {"query": "test"}, skip_permission_check=True)
    assert result["ok"] is True
    assert captured[RESTRICTED_ENV_MARKER] == "1"
    assert captured["TAVILY_API_KEY"] == "selected-key"
    assert not ({"OPENAI_API_KEY", "LOCAL_PROXY", "JARVIS_OVERRIDE_TAVILY_API_KEY"}
                & captured.keys())
    assert not Path(captured["HOME"]).exists()


def test_legacy_tool_without_policy_keeps_existing_environment(monkeypatch):
    schema = ToolSchema("legacy", "Test", {"type": "object", "properties": {}},
                        str(ROOT / "skills" / "tavily_search.py"))

    class Registry:
        def get_tool(self, name):
            return schema if name == "legacy" else None

        def is_mcp_tool(self, name):
            return False

    source = {"PATH": "/usr/bin", "JARVIS_MODE": "cloud", "OPENAI_API_KEY": "legacy-key"}
    monkeypatch.setattr("orchestrator.executor.export_config_environment", lambda *_: source)
    executor = ToolExecutor(mode="cloud", registry=Registry(), load_runtime_config=False)
    with patch("tool_process.run_local_process", return_value=(
        json.dumps({"ok": True, "speech": "done"}), "", False
    )) as run:
        result = executor.execute("legacy", {}, skip_permission_check=True)
    assert result["ok"] is True
    child = run.call_args.kwargs["tool_env"]
    assert child["OPENAI_API_KEY"] == "legacy-key"
    assert RESTRICTED_ENV_MARKER not in child
