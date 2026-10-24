"""Dependency security checks use deterministic workflow and tool contracts."""

from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

from orchestrator.pipeline_executor import PipelineExecutor
from orchestrator.workflow_loader import WorkflowLoader

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "data/workflows/jarvis_dependency_security_check.json"
TITLE = "Workflows/Jarvis Dependency Security"


@pytest.fixture(autouse=True)
def isolate_script_import_paths(monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))


def report(status="clear"):
    complete = status != "incomplete"
    return {
        "status": status,
        "complete": complete,
        "issue_count": int(status != "clear"),
        "packages_queried": 153,
        "checked_at": "2026-10-24T16:00:00Z",
        "findings": [{"package": "fixture", "version": "1.0"}] if status == "findings" else [],
        "summary_markdown": f"## Current Status\n\n{status}\n\nExact package evidence.",
        "alert_title": "Dependency security requires review",
        "alert_description": f"Current dependency check: {status}.",
        "alert_severity": "medium",
        "alert_dedupe_key": f"dependency-security:{status}:fixture-identity",
    }


class NoModelCalls:
    def chat(self, *args, **kwargs):
        pytest.fail("The dependency security workflow must not call a model")

    def chat_with_tools(self, *args, **kwargs):
        pytest.fail("The dependency security workflow must not call a model")


class WorkflowTools:
    """Model the persisted Canvas and alert boundaries without external writes."""

    def __init__(self, data, *, existing=False, fail_canvas=None):
        self.data = data
        self.calls = []
        self.page = {"page_id": "page_security", "title": TITLE, "content": "Old finding"} if existing else None
        self.fail_canvas = fail_canvas
        self.alert_keys = set()
        self.alert_results = []

    def execute(self, tool, params):
        self.calls.append((tool, copy.deepcopy(params)))
        if tool == "dependency_security_check":
            assert params == {"action": "check"}
            return {"ok": True, "data": copy.deepcopy(self.data)}
        if tool == "canvas":
            action = params["action"]
            if action == self.fail_canvas:
                return {"ok": False, "error": "Fixture Canvas storage unavailable"}
            if action == "read":
                assert params["search"] == TITLE
                return {"ok": True, "data": copy.deepcopy(self.page) if self.page else {"matches": [], "count": 0}}
            if action == "create":
                assert self.page is None
                self.page = {"page_id": "page_security", "title": params["title"], "content": params["content"]}
            elif action == "update":
                assert self.page and params["page_id"] == self.page["page_id"]
                assert params["allow_content_shrink"] is True
                self.page["content"] = params["content"]
            else:
                pytest.fail(f"Unexpected Canvas action: {action}")
            return {"ok": True, "data": {"page_id": self.page["page_id"]}}
        if tool == "create_alert":
            assert self.page and self.data["summary_markdown"] in self.page["content"]
            key = params["metadata"]["dedupe_key"]
            duplicate = key in self.alert_keys
            self.alert_keys.add(key)
            self.alert_results.append({"duplicate_suppressed": duplicate})
            return {"ok": True, "data": self.alert_results[-1]}
        pytest.fail(f"Unexpected workflow tool: {tool}")


def run_workflow(tools, mode="cloud"):
    executor = PipelineExecutor(mode=mode, executor=tools, provider=NoModelCalls())
    return executor.execute(json.loads(WORKFLOW.read_text()), "/jarvis_security_check")


def test_workflow_is_explicit_and_has_no_model_steps(tmp_path):
    shutil.copy2(WORKFLOW, tmp_path / WORKFLOW.name)
    workflow = WorkflowLoader(str(tmp_path)).match("/jarvis_security_check")
    assert workflow and workflow["id"] == "jarvis_dependency_security_check"
    assert workflow["allow_workflow_tool"] is False
    assert workflow["disable_server_side_tools"] is True
    assert all("llm_prompt" not in step for step in workflow["steps"])
    assert WorkflowLoader(str(tmp_path)).match("Please audit dependencies") is None


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_clear_checks_refresh_one_complete_canvas_report_without_alert(mode):
    tools = WorkflowTools(report())
    first = run_workflow(tools, mode)
    assert first["ok"] is True, first
    assert tools.page["title"] == TITLE
    assert tools.data["checked_at"] in tools.page["content"]
    assert tools.data["summary_markdown"] in tools.page["content"]

    tools.data["checked_at"] = "2026-10-31T16:00:00Z"
    tools.data["summary_markdown"] = "## Current Status\n\nclear\n\nFresh evidence."
    second = run_workflow(tools, mode)
    assert second["ok"] is True, second
    assert [(tool, args.get("action")) for tool, args in tools.calls] == [
        ("dependency_security_check", "check"), ("canvas", "read"), ("canvas", "create"),
        ("dependency_security_check", "check"), ("canvas", "read"), ("canvas", "update"),
    ]
    assert "Fresh evidence." in tools.page["content"]
    assert "Exact package evidence." not in tools.page["content"]
    assert "2026-10-24T16:00:00Z" not in tools.page["content"]
    assert not tools.alert_results


@pytest.mark.parametrize("status", ["findings", "incomplete"])
def test_findings_and_incomplete_checks_save_report_then_forward_stable_alert_identity(status):
    tools = WorkflowTools(report(status), existing=True)
    for _ in range(2):
        result = run_workflow(tools)
        assert result["ok"] is True, result
    assert [args["action"] for tool, args in tools.calls if tool == "canvas"] == [
        "read", "update", "read", "update",
    ]
    alerts = [args for tool, args in tools.calls if tool == "create_alert"]
    assert len(alerts) == 2
    assert tools.alert_results == [{"duplicate_suppressed": False}, {"duplicate_suppressed": True}]
    assert len(tools.alert_keys) == 1
    for alert in alerts:
        assert alert["title"] == tools.data["alert_title"]
        assert alert["description"] == tools.data["alert_description"]
        assert alert["severity"] == tools.data["alert_severity"]
        assert alert["source"] == "jarvis_dependency_security_check"
        assert alert["speak_immediately"] is False
        assert alert["metadata"]["dedupe_key"] == tools.data["alert_dedupe_key"]
        assert alert["metadata"]["status"] == status
        assert alert["metadata"]["canvas_title"] == TITLE
    if status == "incomplete":
        assert tools.data["findings"] == []
        assert tools.data["complete"] is False


@pytest.mark.parametrize("action", ["read", "create", "update"])
def test_canvas_failure_aborts_before_alert(action):
    tools = WorkflowTools(report("findings"), existing=action == "update", fail_canvas=action)
    result = run_workflow(tools)
    assert result["ok"] is False
    assert "no all-clear" in result["speech"]
    assert not tools.alert_results


def load_skill():
    spec = importlib.util.spec_from_file_location(
        "dependency_security_skill_test", ROOT / "skills/dependency_security_check.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("status", ["clear", "findings", "incomplete"])
def test_tool_preserves_diagnostic_results_for_required_workflow_steps(monkeypatch, status):
    skill = load_skill()
    data = report(status)
    calls = []
    monkeypatch.setattr(skill, "run_audit", lambda root: calls.append(root) or data)
    result = skill.execute({})
    assert result["ok"] is True
    assert result["data"] == data
    assert calls == [ROOT]
    assert status in result["speech"]
    if not data["complete"]:
        assert "could not finish" in result["speech"]


@pytest.mark.parametrize("params", [{"action": "upgrade"}, {"action": "check", "path": "/tmp"}, {"install": True}])
def test_tool_rejects_mutation_or_arbitrary_inventory_arguments_before_audit(monkeypatch, params):
    skill = load_skill()
    monkeypatch.setattr(skill, "run_audit", lambda *args: pytest.fail("Invalid inputs must not audit"))
    result = skill.execute(params)
    assert result["ok"] is False
    assert result["error"] == "unsupported_arguments"


@pytest.mark.parametrize("argument", ["[]", "null", "not-json"])
def test_cli_invalid_input_is_json_and_exits_unsuccessfully(monkeypatch, capsys, argument):
    skill = load_skill()
    monkeypatch.setattr(skill, "run_audit", lambda *args: pytest.fail("Invalid inputs must not audit"))
    monkeypatch.setattr(sys, "argv", ["dependency_security_check.py", argument])
    with pytest.raises(SystemExit) as exc:
        skill.main()
    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().out)["error"] == "invalid_input"


def test_manifest_is_discoverable_with_a_restricted_credential_free_environment(tmp_path, monkeypatch):
    import tool_availability
    import tool_profiles
    from tool_schema import ToolRegistry

    for suffix in (".py", ".tool.json"):
        shutil.copy2(ROOT / f"skills/dependency_security_check{suffix}", tmp_path)
    monkeypatch.setattr(tool_profiles, "get_active_profile_name", lambda: "test")
    monkeypatch.setattr(tool_profiles, "load_active_profile_overrides", lambda: {})
    monkeypatch.setattr(tool_profiles, "warn_missing_profile_file", lambda: None)
    monkeypatch.setattr(tool_availability, "get_config_value", lambda key, default=None: default)
    registry = ToolRegistry(str(tmp_path), None)
    try:
        schema = registry.get_tool("dependency_security_check")
        assert schema is not None
        assert schema.child_environment_names == frozenset()
        assert schema.permissions["network"] is True
        assert schema.permissions["dangerous"] is False
        assert schema.permissions["bash"] is False
        assert schema.parameters["additionalProperties"] is False
        assert schema.parameters["properties"]["action"]["enum"] == ["check"]
        assert schema.to_openai_format()["function"]["name"] == "dependency_security_check"
    finally:
        registry.cleanup()
