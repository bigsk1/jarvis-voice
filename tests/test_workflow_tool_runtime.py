"""Foreground workflow meta-tool discovery and execution regressions."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

from pipeline_executor import PipelineExecutor
from orchestrator_v2 import Orchestrator
from workflow_loader import WorkflowLoader
from workflow_tool_runtime import execute_workflow_tool


class FakeRegistry:
    def __init__(self, tools):
        self.tools = {name: SimpleNamespace(name=name) for name in tools}

    def list_tools(self):
        return list(self.tools)

    def get_tool(self, name):
        return self.tools.get(name)


def _write_workflow(path: Path, workflow: dict) -> None:
    path.write_text(json.dumps(workflow), encoding="utf-8")


def _workflow(workflow_id: str, tool: str = "get_time", *, name: str | None = None) -> dict:
    return {
        "id": workflow_id,
        "name": name or workflow_id.replace("_", " ").title(),
        "description": f"Research and report with {tool}.",
        "triggers": {
            "explicit": [f"/{workflow_id}"],
            "patterns": ["research report"],
            "keywords": ["research", "report"],
        },
        "variables": {
            "topic": {"from": "query", "extract": "main_subject"},
        },
        "steps": [
            {"step": 1, "tool": tool, "description": "Get the source data"},
        ],
    }


def test_search_uses_personal_override_and_omits_unavailable(tmp_path):
    _write_workflow(tmp_path / "report.json", _workflow("report", name="Shared Report"))
    _write_workflow(tmp_path / "blocked.json", _workflow("blocked", tool="send_email"))
    personal = tmp_path / "personal"
    personal.mkdir()
    _write_workflow(personal / "report.json", _workflow("report", name="Personal Report"))

    result = execute_workflow_tool(
        registry=FakeRegistry({"workflow", "get_time"}),
        args={"action": "search", "query": "research report"},
        mode="cloud",
        loader=WorkflowLoader(str(tmp_path)),
    )

    assert result["ok"] is True
    assert result["data"]["selected_workflow_hints"] == ["report"]
    assert result["data"]["matches"][0]["name"] == "Personal Report"
    assert result["data"]["matches"][0]["query_required"] is True
    assert "blocked" not in result["data"]["selected_workflow_hints"]


def test_describe_is_compact_and_does_not_expose_component_schemas(tmp_path):
    _write_workflow(tmp_path / "report.json", _workflow("report"))

    result = execute_workflow_tool(
        registry=FakeRegistry({"workflow", "get_time"}),
        args={"action": "describe", "workflow_id": "report"},
        mode="cloud",
        loader=WorkflowLoader(str(tmp_path)),
    )

    description = result["data"]["workflow"]
    assert description["component_tools"] == ["get_time"]
    assert description["steps"] == [
        {
            "step": 1,
            "tool": "get_time",
            "description": "Get the source data",
        }
    ]
    assert "parameters_schema" not in json.dumps(description)


def test_run_requires_query_and_rechecks_availability(tmp_path):
    _write_workflow(tmp_path / "report.json", _workflow("report"))
    loader = WorkflowLoader(str(tmp_path))

    missing = execute_workflow_tool(
        registry=FakeRegistry({"workflow", "get_time"}),
        args={"action": "run", "workflow_id": "report"},
        mode="cloud",
        loader=loader,
    )
    assert missing["ok"] is False
    assert missing["data"]["required_query_inputs"] == ["topic"]

    blocked = execute_workflow_tool(
        registry=FakeRegistry({"workflow", "get_time"}),
        args={"action": "run", "workflow_id": "report", "query": "AI agents"},
        mode="cloud",
        loader=loader,
        excluded_tools={"get_time"},
    )
    assert blocked["ok"] is False
    assert blocked["data"]["availability"]["blocked_tools"] == ["get_time"]


def test_run_is_foreground_and_returns_pipeline_result(tmp_path):
    _write_workflow(tmp_path / "report.json", _workflow("report"))
    calls = []
    statuses = []

    def execute(workflow, query, status_callback=None):
        calls.append((workflow["id"], query))
        status_callback("Step 1: source")
        return {
            "ok": True,
            "speech": "Report complete.",
            "data": {
                "workflow_id": workflow["id"],
                "steps_completed": 1,
                "results": [{"step": 1, "ok": True}],
            },
            "tools_used": ["get_time"],
            "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14, "model_calls": 1},
        }

    result = execute_workflow_tool(
        registry=FakeRegistry({"workflow", "get_time"}),
        args={"action": "run", "workflow_id": "report", "query": "AI agents"},
        mode="cloud",
        loader=WorkflowLoader(str(tmp_path)),
        pipeline_executor=SimpleNamespace(execute=execute),
        status_callback=statuses.append,
    )

    assert calls == [("report", "/report AI agents")]
    assert statuses == ["Step 1: source"]
    assert result["ok"] is True
    assert result["data"]["execution"] == "foreground"
    assert result["data"]["component_tools_used"] == ["get_time"]
    assert result["data"]["workflow_metadata"]["workflow_id"] == "report"
    assert result["data"]["workflow_metadata"]["summary"] == (
        "Research and report with get_time."
    )
    assert result["data"]["workflow_metadata"]["triggers"]["keywords"] == [
        "research",
        "report",
    ]
    assert result["usage"]["total_tokens"] == 14


def test_pipeline_merges_usage_reported_by_component_llm_tools():
    pipeline = object.__new__(PipelineExecutor)
    pipeline._total_usage = {
        "input_tokens": 3,
        "output_tokens": 1,
        "total_tokens": 4,
        "model_calls": 1,
        "peak_context_tokens": 4,
        "cost_usd": 0.01,
        "has_unknown_cost": False,
        "cost_known": True,
        "billing_mode": None,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_cost_usd": 0.0,
        "cache_read_cost_usd": 0.0,
        "cache_cost_usd": 0.0,
        "cache_savings_usd": 0.0,
    }
    pipeline._server_side_tools = {}

    pipeline._merge_component_usage(
        {
            "ok": True,
            "usage": {
                "input_tokens": 20,
                "output_tokens": 5,
                "total_tokens": 25,
                "model_calls": 2,
                "peak_context_tokens": 15,
                "cost_usd": 0.04,
                "server_side_tools": {"SERVER_SIDE_TOOL_WEB_SEARCH": 1},
                "provider": "ollama",
                "model": "summary-model:cloud",
            },
        },
        tool_name="text_summarizer",
    )

    assert pipeline._total_usage["model_calls"] == 3
    assert pipeline._total_usage["total_tokens"] == 29
    assert pipeline._total_usage["peak_context_tokens"] == 15
    assert pipeline._total_usage["cost_usd"] == 0.05
    assert pipeline._server_side_tools == {"SERVER_SIDE_TOOL_WEB_SEARCH": 1}
    assert pipeline._total_usage["mixed_model_usage"] is True
    assert pipeline._total_usage["component_llm_usage"] == [
        {
            "tool": "text_summarizer",
            "provider": "ollama",
            "model": "summary-model:cloud",
            "input_tokens": 20,
            "output_tokens": 5,
            "total_tokens": 25,
            "model_calls": 2,
            "cost_usd": 0.04,
        }
    ]


def test_workflow_env_variables_use_mode_scoped_config():
    pipeline = object.__new__(PipelineExecutor)
    workflow = {
        "id": "weather_watch",
        "variables": {
            "location": {
                "from": "env",
                "key": "JARVIS_DEFAULT_LOCATION",
                "default": "Fallback",
            }
        },
    }

    with patch("pipeline_executor.get_config_value", return_value="Cloud Location") as get_value:
        variables = pipeline._extract_workflow_variables(
            "/weather_watch",
            workflow,
            "",
        )

    assert variables["location"] == "Cloud Location"
    get_value.assert_called_once_with("JARVIS_DEFAULT_LOCATION")


def test_parent_turn_merges_workflow_and_component_model_usage():
    total = {
        "input_tokens": 10,
        "output_tokens": 2,
        "total_tokens": 12,
        "model_calls": 1,
        "peak_context_tokens": 12,
        "cost_usd": 0.01,
        "has_unknown_cost": False,
        "cost_known": True,
        "billing_mode": None,
        "input_estimated": False,
        "cache_creation_tokens": 0,
        "cache_creation_5m_tokens": 0,
        "cache_creation_1h_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_cost_usd": 0.0,
        "cache_read_cost_usd": 0.0,
        "cache_cost_usd": 0.0,
        "cache_savings_usd": 0.0,
        "server_side_tools": {},
    }
    workflow_usage = {
        "input_tokens": 30,
        "output_tokens": 8,
        "total_tokens": 38,
        "model_calls": 3,
        "peak_context_tokens": 20,
        "cost_usd": 0.05,
        "component_llm_usage": [
            {
                "tool": "text_summarizer",
                "provider": "ollama",
                "model": "summary-model:cloud",
                "total_tokens": 20,
                "model_calls": 2,
            }
        ],
    }

    Orchestrator._merge_workflow_usage(total, workflow_usage)

    assert total["total_tokens"] == 50
    assert total["model_calls"] == 4
    assert total["peak_context_tokens"] == 20
    assert total["mixed_model_usage"] is True
    assert total["component_llm_usage"][0]["model"] == "summary-model:cloud"


def test_pipeline_cancellation_stops_before_later_side_effects():
    calls = []

    def execute(tool_name, _params):
        calls.append(tool_name)
        return {
            "ok": True,
            "cancelled": True,
            "speech": f"Stopped {tool_name}.",
        }

    executor = SimpleNamespace(
        registry=FakeRegistry({"get_time", "send_email"}),
        excluded_tools=set(),
        cancel_check=lambda: False,
        execute=execute,
    )
    pipeline = PipelineExecutor("cloud", executor, provider=SimpleNamespace())
    pipeline.logger = SimpleNamespace(log_workflow_execution=lambda **_kwargs: None)
    workflow = {
        "id": "cancel_before_email",
        "name": "Cancel Before Email",
        "steps": [
            {"step": 1, "tool": "get_time"},
            {"step": 2, "tool": "send_email"},
        ],
    }

    result = pipeline.execute(workflow, "/cancel_before_email")

    assert result["ok"] is True
    assert result["cancelled"] is True
    assert calls == ["get_time"]
    assert result["data"]["steps_completed"] == 1
