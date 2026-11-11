"""Trusted assignments select screening without duplicate tool-list registration."""

import json
import logging
import threading
from collections import OrderedDict
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import config_loader
import paths
import pytest
from config_loader import config_scope, get_active_config_mode
from test_prompt_guard import Response, payload
from tool_schema import ToolRegistry, ToolSchema

from lib import paths as package_paths
from lib import prompt_guard as scanner
from lib import prompt_guard_observer as observer
from lib import prompt_guard_policy as policy


def write_policy(path, *, tools=(), policies=None, rules=()):
    path.write_text(json.dumps({
        "v": 2, "tools": list(tools), "summarizers": {"enabled": True},
        "policies": {"web_content": 0.8, "strict_content": 0.6} if policies is None else policies,
        "rules": list(rules),
    }))


def write_manifest(root, name, assignment=None):
    directory = root / "skills"
    directory.mkdir(exist_ok=True)
    document = {
        "name": name, "description": "Read external source content.",
        "script": f"{name}.py", "parameters": {"type": "object", "properties": {}},
    }
    if assignment is not None:
        document["prompt_guard_policy"] = assignment
    path = directory / f"{name}.tool.json"
    path.write_text(json.dumps(document))
    return path


def write_mcp(root, server):
    (root / "config" / "mcp-servers.json").write_text(json.dumps({
        "mcpServers": {"catalog": {"enabled": True, **server}},
    }))


@pytest.fixture
def assigned_guard(tmp_path, monkeypatch):
    directory = tmp_path / "config"
    directory.mkdir()
    policy_paths = {}
    for mode in ("cloud", "local"):
        policy_paths[mode] = directory / f"{mode}.json"
        write_policy(policy_paths[mode])
        (directory / f"{mode}.env").write_text(
            "PROMPT_GUARD_ENABLED=true\n"
            f"PROMPT_GUARD_POLICY_FILE={policy_paths[mode]}\n"
            f"PROMPT_GUARD_URL=http://{mode}-assignment.test:8188\n"
            "PROMPT_GUARD_API_KEY=test-only-key\n"
            "PROMPT_GUARD_THRESHOLD=0.9\n"
            "PROMPT_GUARD_MAX_INPUT_BYTES=8192\n"
            f"PROMPT_GUARD_INCIDENT_DIR={tmp_path / 'incidents'}\n"
            "PROMPT_GUARD_ALERTS_ENABLED=false\n"
        )
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(paths, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(package_paths, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(policy, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(scanner, "_states", OrderedDict())
    monkeypatch.setattr(scanner, "_capacity", threading.BoundedSemaphore(1))
    state = SimpleNamespace(calls=[], score=0.1)

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def post(self, url, **kwargs):
            assert self.trust_env is False
            assert kwargs["allow_redirects"] is False and kwargs["stream"] is True
            body = kwargs["json"]
            state.calls.append({"url": url, "mode": get_active_config_mode(), **body})
            return Response(payload(
                injection_score=state.score, threshold=body["threshold"],
                flagged=state.score >= body["threshold"],
            ))

    monkeypatch.setattr(scanner.requests, "Session", Session)
    return SimpleNamespace(root=tmp_path, paths=policy_paths, state=state)


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_local_assignment_alone_selects_and_withholds_at_its_named_threshold(assigned_guard, mode):
    path = write_manifest(assigned_guard.root, "assigned_fetch", "web_content")
    assert ToolSchema.from_json_file(str(path)).prompt_guard_policy == "web_content"
    assigned_guard.state.score = 0.85  # Below global 0.9, above the assigned 0.8.
    original = {"ok": True, "data": {"content": "PRIVATE_EXTERNAL_BODY"}}
    before = deepcopy(original)
    with config_scope(mode):
        assert json.loads(assigned_guard.paths[mode].read_text())["tools"] == []
        assert policy.is_tool_selected("assigned_fetch")
        result = observer.review_tool_result("assigned_fetch", original)
    assert observer.is_prompt_guard_rejection(result)
    assert result["terminal_failure"] is True and result["retry_safe"] is False
    assert result["data"]["prompt_guard"]["policy_id"] == "policy:web_content"
    assert original == before and "PRIVATE_EXTERNAL_BODY" not in json.dumps(result)
    call, = assigned_guard.state.calls
    assert call["mode"] == mode and call["threshold"] == 0.8
    assert call["url"] == f"http://{mode}-assignment.test:8188/v1/scan"
    evidence_path, = (assigned_guard.root / "incidents" / mode).glob("*.json")
    evidence = json.loads(evidence_path.read_text())
    assert evidence["evidence"]["text"] == call["text"]
    assert json.loads(call["text"]) == {"data": original["data"]}


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_one_mcp_server_assignment_selects_many_tools_without_listing_each(assigned_guard, mode):
    server = {"prompt_guard_policy": "web_content"}
    write_mcp(assigned_guard.root, server)
    names = ["search-actors", "fetch-actor-details", *[f"resource_{i}" for i in range(10)]]
    client = SimpleNamespace(tool_defaults={})
    with config_scope(mode):
        for name in names:
            schema = ToolRegistry.schema_from_mcp_tool("catalog", client, server, {
                "name": name, "description": "External result", "inputSchema": {"type": "object"},
            })
            assert schema.prompt_guard_policy == "web_content"
            assert policy.is_tool_selected(schema.name)
            original = {"ok": True, "data": {"content": name}}
            assert observer.review_tool_result(schema.name, original) is original
    assert [row["source"]["name"] for row in assigned_guard.state.calls] == [
        f"mcp_catalog_{name}" for name in names
    ]
    assert all(row["threshold"] == 0.8 for row in assigned_guard.state.calls)
    assert json.loads(assigned_guard.paths[mode].read_text())["tools"] == []


def test_per_tool_mcp_assignment_and_exact_rule_override_server_default(assigned_guard):
    server = {
        "prompt_guard_policy": "web_content",
        "tool_metadata": {
            "details": {"prompt_guard_policy": "strict_content"},
            "specific": {"prompt_guard_policy": "strict_content"},
        },
    }
    write_mcp(assigned_guard.root, server)
    write_policy(assigned_guard.paths["cloud"], rules=[{
        "id": "operator_exact", "source_type": "tool_result",
        "source_name": "mcp_catalog_specific", "threshold": 0.95,
    }])
    with config_scope("cloud"):
        for name in ("search", "details", "specific"):
            original = {"ok": True, "data": {"content": name}}
            assert observer.review_tool_result(f"mcp_catalog_{name}", original) is original
    assert [row["threshold"] for row in assigned_guard.state.calls] == [0.8, 0.6, 0.95]


@pytest.mark.parametrize("kind", ["local", "mcp"])
def test_unknown_assigned_name_still_selects_and_reports_global_fallback(
    assigned_guard, caplog, kind,
):
    if kind == "local":
        name = "assigned_fetch"
        write_manifest(assigned_guard.root, name, "operator_typo")
    else:
        name = "mcp_catalog_search"
        write_mcp(assigned_guard.root, {"prompt_guard_policy": "operator_typo"})
    original = {"ok": True, "data": {"content": "Ordinary source."}}
    with config_scope("cloud"), caplog.at_level(logging.WARNING):
        assert policy.is_tool_selected(name)
        assert observer.review_tool_result(name, original) is original
    call, = assigned_guard.state.calls
    assert call["threshold"] == 0.9 and "unknown_policy" in caplog.text
    assert "invalid_policy" not in caplog.text


@pytest.mark.parametrize("forgery", ["arguments", "result", "nested_result", "remote_metadata"])
def test_untrusted_policy_name_cannot_select_an_untagged_tool(assigned_guard, forgery):
    name = "untagged_fetch"
    original = {"ok": True, "data": {"content": "Ordinary source."}}
    arguments = {}
    if forgery == "arguments":
        arguments["prompt_guard_policy"] = "web_content"
    elif forgery == "result":
        original["prompt_guard_policy"] = "web_content"
    elif forgery == "nested_result":
        original["data"]["prompt_guard_policy"] = "web_content"
    else:
        reported = {
            "name": "search", "description": "External search", "inputSchema": {"type": "object"},
            "prompt_guard_policy": "web_content",
            "annotations": {"prompt_guard_policy": "web_content"},
            "_meta": {"prompt_guard_policy": "web_content"},
        }
        schema = ToolRegistry.schema_from_mcp_tool(
            "catalog", SimpleNamespace(tool_defaults={}), {}, reported,
        )
        assert schema.prompt_guard_policy is None
        name = schema.name
        write_mcp(assigned_guard.root, {})
    if forgery != "remote_metadata":
        write_manifest(assigned_guard.root, name)
    before = deepcopy(original)
    with config_scope("cloud"):
        assert not policy.is_tool_selected(name)
        assert observer.review_tool_result(name, original, args=arguments) is original
    assert original == before and not assigned_guard.state.calls


def test_returned_or_argument_policy_cannot_override_trusted_assignment(assigned_guard):
    write_manifest(assigned_guard.root, "assigned_fetch", "web_content")
    original = {
        "ok": True, "prompt_guard_policy": "strict_content",
        "data": {"content": "Ordinary source.", "prompt_guard_policy": "strict_content"},
    }
    with config_scope("cloud"):
        assert observer.review_tool_result("assigned_fetch", original, args={
            "prompt_guard_policy": "strict_content", "secret": "ARGUMENT_NOT_SCANNED",
        }) is original
    call, = assigned_guard.state.calls
    assert call["threshold"] == 0.8 and "ARGUMENT_NOT_SCANNED" not in call["text"]


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_master_disabled_prevents_assigned_output_extraction_and_scan(
    assigned_guard, monkeypatch, mode,
):
    write_manifest(assigned_guard.root, "assigned_fetch", "web_content")
    extraction = Mock(wraps=observer._serialize_content)
    monkeypatch.setattr(observer, "_serialize_content", extraction)
    original = {"ok": True, "data": "x" * 100000}
    with config_scope(mode, {"PROMPT_GUARD_ENABLED": "false"}):
        assert observer.review_tool_result("assigned_fetch", original) is original
    extraction.assert_not_called()
    assert not assigned_guard.state.calls


@pytest.mark.parametrize("invalid", ["malformed", "wrong_version", "missing"])
def test_invalid_config_does_not_select_assigned_or_explicit_tools(assigned_guard, caplog, invalid):
    write_manifest(assigned_guard.root, "assigned_fetch", "web_content")
    path = assigned_guard.paths["cloud"]
    if invalid == "malformed":
        path.write_text("{not JSON")
    elif invalid == "wrong_version":
        document = json.loads(path.read_text())
        document["v"] = 1
        document["tools"] = ["explicit_fetch"]
        path.write_text(json.dumps(document))
    else:
        path.unlink()
    with config_scope("cloud"), caplog.at_level(logging.WARNING):
        for name in ("assigned_fetch", "explicit_fetch"):
            original = {"ok": True, "data": {"content": "Ordinary source."}}
            assert not policy.is_tool_selected(name)
            assert observer.review_tool_result(name, original) is original
    assert not assigned_guard.state.calls and "invalid_policy" in caplog.text


def test_local_assignment_and_named_threshold_edits_hot_reload_without_new_scope(assigned_guard):
    write_manifest(assigned_guard.root, "assigned_fetch", "web_content")
    original = {"ok": True, "data": {"content": "Ordinary source."}}
    with config_scope("cloud"):
        observer.review_tool_result("assigned_fetch", original)
        write_policy(assigned_guard.paths["cloud"], policies={"web_content": 0.7})
        observer.review_tool_result("assigned_fetch", original)
        write_manifest(assigned_guard.root, "assigned_fetch")
        assert not policy.is_tool_selected("assigned_fetch")
        observer.review_tool_result("assigned_fetch", original)
        write_manifest(assigned_guard.root, "assigned_fetch", "new_policy_not_defined")
        observer.review_tool_result("assigned_fetch", original)
    assert [row["threshold"] for row in assigned_guard.state.calls] == [0.8, 0.7, 0.9]


def test_mcp_server_assignment_hot_reload_selects_and_deselects_existing_tool(assigned_guard):
    original = {"ok": True, "data": {"content": "Ordinary source."}}
    with config_scope("local"):
        write_mcp(assigned_guard.root, {"prompt_guard_policy": "web_content"})
        observer.review_tool_result("mcp_catalog_search", original)
        write_mcp(assigned_guard.root, {"prompt_guard_policy": "strict_content"})
        observer.review_tool_result("mcp_catalog_search", original)
        write_mcp(assigned_guard.root, {})
        assert not policy.is_tool_selected("mcp_catalog_search")
        observer.review_tool_result("mcp_catalog_search", original)
    assert [row["threshold"] for row in assigned_guard.state.calls] == [0.8, 0.6]


def test_explicit_selection_without_assignment_retains_global_threshold(assigned_guard):
    write_manifest(assigned_guard.root, "explicit_fetch")
    write_policy(assigned_guard.paths["cloud"], tools=["explicit_fetch"])
    with config_scope("cloud"):
        observer.review_tool_result("explicit_fetch", {"ok": True, "data": "Ordinary source."})
    call, = assigned_guard.state.calls
    assert call["threshold"] == 0.9


def test_trusted_foreground_binding_selects_even_without_on_disk_definition(assigned_guard):
    original = {"ok": True, "data": {"content": "Ordinary source."}}
    with config_scope("cloud"):
        assert policy.is_tool_selected("registry_bound_fetch", policy_name="web_content")
        assert observer.review_tool_result(
            "registry_bound_fetch", original, policy_name="web_content",
        ) is original
    call, = assigned_guard.state.calls
    assert call["threshold"] == 0.8
