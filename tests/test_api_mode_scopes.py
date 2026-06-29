#!/usr/bin/env python3
"""API query/workflow request-mode isolation regressions."""

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "orchestrator"))

from api.models.query import QueryRequest  # noqa: E402
from api.models.workflows import WorkflowExecuteRequest  # noqa: E402
from api.routes.query import query_jarvis  # noqa: E402
from api.routes.workflows import execute_workflow  # noqa: E402
from config_loader import get_active_config_mode, get_config_value  # noqa: E402


def test_query_route_uses_scope_without_mutating_parent_environment():
    observed = {}

    class FakeOrchestrator:
        def __init__(self, mode):
            observed["mode"] = get_active_config_mode()
            observed["provider"] = get_config_value("LLM_PROVIDER")
            observed["constructor_mode"] = mode

        def process(self, **_kwargs):
            return {"ok": True, "speech": "done", "tools_used": []}

    before = dict(os.environ)
    with patch.dict(sys.modules, {"orchestrator_v2": SimpleNamespace(Orchestrator=FakeOrchestrator)}):
        result = asyncio.run(query_jarvis(None, QueryRequest(query="probe", mode="local")))

    assert result.ok is True
    assert observed == {
        "mode": "local",
        "provider": "ollama",
        "constructor_mode": "local",
    }
    assert dict(os.environ) == before


def test_workflow_route_uses_scope_without_mutating_parent_environment():
    observed = {}

    class FakeToolExecutor:
        def __init__(self, mode):
            observed["tool_mode"] = mode

    class FakePipelineExecutor:
        def __init__(self, mode, _executor):
            observed["mode"] = get_active_config_mode()
            observed["provider"] = get_config_value("LLM_PROVIDER")
            observed["pipeline_mode"] = mode

        def execute(self, _workflow, _transcript):
            return {"ok": True, "speech": "done", "tools_used": []}

    before = dict(os.environ)
    modules = {
        "executor": SimpleNamespace(ToolExecutor=FakeToolExecutor),
        "pipeline_executor": SimpleNamespace(PipelineExecutor=FakePipelineExecutor),
    }
    request = WorkflowExecuteRequest(mode="local", query="all configured servers")
    with patch.dict(sys.modules, modules):
        result = asyncio.run(execute_workflow("server_health_check", request))

    assert result.ok is True
    assert observed == {
        "tool_mode": "local",
        "mode": "local",
        "provider": "ollama",
        "pipeline_mode": "local",
    }
    assert dict(os.environ) == before
