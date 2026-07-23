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
    workflow_unavailable_message,
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


def test_workflow_availability_is_strict_for_optional_tools():
    availability = check_workflow_availability(
        _workflow(),
        available_tools={"search_docs"},
    )

    assert availability == {
        "available": False,
        "workflow_id": "research_report",
        "tools": ["search_docs", "send_email"],
        "blocked_tools": [],
        "unavailable_tools": ["send_email"],
    }
    assert "send_email" in workflow_unavailable_message(_workflow(), availability)


def test_workflow_availability_distinguishes_request_block():
    availability = check_workflow_availability(
        _workflow(),
        available_tools={"search_docs", "send_email"},
        excluded_tools={"send_email"},
    )

    assert availability["available"] is False
    assert availability["blocked_tools"] == ["send_email"]
    assert availability["unavailable_tools"] == []


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


def test_pipeline_preflight_blocks_before_any_step_executes():
    calls = []
    executor = SimpleNamespace(
        registry=FakeRegistry({"search_docs"}),
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
    assert result["data"]["availability"]["unavailable_tools"] == ["send_email"]
    assert calls == []


def test_explicit_slash_workflow_returns_unavailable_instead_of_falling_through():
    workflow = _workflow()
    orchestrator = object.__new__(Orchestrator)
    orchestrator.workflow_loader = SimpleNamespace(match=lambda _query: workflow)
    orchestrator.registry = FakeRegistry({"search_docs", "send_email"})
    orchestrator.executor = SimpleNamespace(excluded_tools={"send_email"})
    orchestrator.pipeline_executor = SimpleNamespace(
        execute=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unavailable workflow must not execute")
        )
    )

    result = orchestrator._try_workflow("/research_report AI agents")

    assert result["ok"] is False
    assert result["workflow_executed"] == "research_report"
    assert result["data"]["availability"]["blocked_tools"] == ["send_email"]
