"""Workflow availability and execution-boundary regressions."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

from orchestrator.executor import ToolExecutor
from orchestrator.orchestrator_v2 import Orchestrator
from orchestrator.pipeline_executor import PipelineExecutor
from orchestrator.workflow_availability import (
    check_workflow_availability,
)


class FakeRegistry:
    def __init__(self, tools):
        self.tools = {name: object() for name in tools}

    def list_tools(self):
        return list(self.tools)

    def get_tool(self, name):
        return self.tools.get(name)


def _workflow():
    return {
        "id": "research_report",
        "name": "Research Report",
        "triggers": {"explicit": ["/research_report"]},
        "steps": [
            {"step": 1, "tool": "search_docs"},
            {
                "step": 2,
                "tool": "send_email",
                "required": False,
                "on_fail": "continue",
            },
        ],
    }


def test_workflow_availability_allows_unavailable_optional_tools():
    availability = check_workflow_availability(
        _workflow(),
        available_tools={"search_docs"},
    )

    assert availability == {
        "available": True,
        "degraded": True,
        "workflow_id": "research_report",
        "tools": ["search_docs", "send_email"],
        "required_tools": ["search_docs"],
        "optional_tools": ["send_email"],
        "blocked_tools": [],
        "unavailable_tools": [],
        "optional_blocked_tools": [],
        "optional_unavailable_tools": ["send_email"],
        "optional_tools_skipped": ["send_email"],
    }


def test_workflow_availability_allows_blocked_optional_tools():
    availability = check_workflow_availability(
        _workflow(),
        available_tools={"search_docs", "send_email"},
        excluded_tools={"send_email"},
    )

    assert availability["available"] is True
    assert availability["degraded"] is True
    assert availability["blocked_tools"] == []
    assert availability["unavailable_tools"] == []
    assert availability["optional_blocked_tools"] == ["send_email"]
    assert availability["optional_tools_skipped"] == ["send_email"]


def test_workflow_availability_remains_strict_for_required_request_block():
    availability = check_workflow_availability(
        _workflow(),
        available_tools={"search_docs", "send_email"},
        excluded_tools={"search_docs"},
    )

    assert availability["available"] is False
    assert availability["blocked_tools"] == ["search_docs"]
    assert availability["optional_tools_skipped"] == []


def test_workflow_cannot_recursively_invoke_meta_tool():
    workflow = {
        "id": "recursive",
        "name": "Recursive Workflow",
        "steps": [{"step": 1, "tool": "workflow", "required": False}],
    }

    availability = check_workflow_availability(
        workflow,
        available_tools={"workflow"},
    )

    assert availability["available"] is False
    assert availability["unavailable_tools"] == ["workflow"]


def test_tool_used_by_required_and_optional_steps_remains_required():
    workflow = _workflow()
    workflow["steps"] = [
        {"step": 1, "tool": "search_docs", "required": False},
        {"step": 2, "tool": "search_docs"},
        {"step": 3, "tool": "send_email", "required": False},
    ]

    availability = check_workflow_availability(
        workflow,
        available_tools={"send_email"},
    )

    assert availability["available"] is False
    assert availability["required_tools"] == ["search_docs"]
    assert availability["optional_tools"] == ["send_email"]
    assert availability["unavailable_tools"] == ["search_docs"]


def test_executor_enforces_request_exclusions_before_registry_lookup():
    executor = object.__new__(ToolExecutor)
    executor.excluded_tools = {"send_email"}
    executor.registry = SimpleNamespace(
        get_tool=lambda _name: (_ for _ in ()).throw(
            AssertionError("blocked tool must not reach registry lookup")
        )
    )

    result = executor.execute("send_email", {"to": "boss"})

    assert result["ok"] is False
    assert result["error"] == "Tool blocked for this request"


def test_workflow_meta_tool_bypasses_subprocess_timeout_path():
    executor = object.__new__(ToolExecutor)
    executor.excluded_tools = set()
    executor.registry = FakeRegistry({"workflow"})
    executor._execute_workflow = lambda _tool_name, _args: {
        "ok": True,
        "speech": "Found workflows.",
        "data": {"action": "search"},
    }
    executor._get_subprocess_timeout = lambda _tool_name: (_ for _ in ()).throw(
        AssertionError("in-process workflow tool must not use subprocess timeout")
    )

    result = executor.execute("workflow", {"action": "search", "query": "research"})

    assert result["ok"] is True
    assert result["data"]["action"] == "search"


def test_pipeline_preflight_blocks_before_any_step_executes():
    calls = []
    executor = SimpleNamespace(
        registry=FakeRegistry({"send_email"}),
        excluded_tools=set(),
        execute=lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    pipeline = PipelineExecutor(
        mode="cloud",
        executor=executor,
        provider=SimpleNamespace(),
    )

    result = pipeline.execute(_workflow(), "/research_report AI agents")

    assert result["ok"] is False
    assert result["steps_completed"] == 0
    assert result["data"]["availability"]["unavailable_tools"] == ["search_docs"]
    assert calls == []


def test_pipeline_skips_unavailable_optional_tool_without_calling_it():
    calls = []

    def execute(tool_name, _params):
        calls.append(tool_name)
        return {"ok": True, "data": {"source": tool_name}}

    executor = SimpleNamespace(
        registry=FakeRegistry({"search_docs"}),
        excluded_tools=set(),
        execute=execute,
    )
    pipeline = PipelineExecutor(
        mode="cloud",
        executor=executor,
        provider=SimpleNamespace(),
    )

    result = pipeline.execute(_workflow(), "/research_report AI agents")

    assert result["ok"] is True
    assert result["tools_used"] == ["search_docs"]
    assert calls == ["search_docs"]
    assert result["speech"].endswith(
        "Optional unavailable tools skipped: send_email."
    )
    assert result["data"]["degraded"] is True
    assert result["data"]["optional_tools_skipped"] == ["send_email"]
    assert result["data"]["results"][1] == {
        "step": 2,
        "tool": "send_email",
        "skipped": True,
        "skip_kind": "optional_tool_unavailable",
        "reason": (
            "Optional tool 'send_email' is unavailable in the active registry "
            "or blocked for this execution surface"
        ),
    }


def test_explicit_slash_workflow_returns_unavailable_instead_of_falling_through():
    workflow = _workflow()
    orchestrator = object.__new__(Orchestrator)
    orchestrator.workflow_loader = SimpleNamespace(match=lambda _query: workflow)
    orchestrator.registry = FakeRegistry({"search_docs", "send_email"})
    orchestrator.executor = SimpleNamespace(excluded_tools={"search_docs"})
    orchestrator.pipeline_executor = SimpleNamespace(
        execute=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unavailable workflow must not execute")
        )
    )

    result = orchestrator._try_workflow("/research_report AI agents")

    assert result["ok"] is False
    assert result["workflow_executed"] == "research_report"
    assert result["data"]["availability"]["blocked_tools"] == ["search_docs"]
