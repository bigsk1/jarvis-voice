#!/usr/bin/env python3
"""API query/workflow request-mode isolation regressions."""

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "orchestrator"))

from api.models.query import QueryRequest  # noqa: E402
from api.models.scheduled_task import ScheduledTaskCreate, ScheduledTaskType, ScheduledTaskUpdate  # noqa: E402
from api.models.workflows import WorkflowExecuteRequest  # noqa: E402
from api.routes.query import query_jarvis  # noqa: E402
from api.routes.workflows import execute_workflow, _resolve_workflow  # noqa: E402
from services import scheduled_task_runner  # noqa: E402
import config_loader  # noqa: E402
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
    shared_registry = object()

    class FakeToolExecutor:
        def __init__(self, mode, registry=None):
            observed["tool_mode"] = mode
            observed["registry"] = registry

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
        "tool_schema": SimpleNamespace(get_tool_registry=lambda mode=None: shared_registry),
    }
    request = WorkflowExecuteRequest(mode="local", query="all configured servers")
    with patch.dict(sys.modules, modules):
        result = asyncio.run(execute_workflow("server_health_check", request))

    assert result.ok is True
    assert observed == {
        "tool_mode": "local",
        "registry": shared_registry,
        "mode": "local",
        "provider": "ollama",
        "pipeline_mode": "local",
    }
    assert dict(os.environ) == before


def test_workflow_route_resolves_personal_trigger_alias():
    observed = {}
    shared_registry = object()

    class FakeWorkflowLoader:
        def __init__(self, explicit_only=True):
            self.workflows = {
                "private_radar": {
                    "id": "private_radar",
                    "triggers": {"explicit": ["/private_radar", "/secret_radar"]},
                    "steps": [{"step": 1, "tool": "get_time"}],
                }
            }

        def get_workflow(self, workflow_id):
            return self.workflows.get(workflow_id)

    class FakeToolExecutor:
        def __init__(self, mode, registry=None):
            observed["tool_mode"] = mode
            observed["registry"] = registry

    class FakePipelineExecutor:
        def __init__(self, mode, _executor):
            observed["pipeline_mode"] = mode

        def execute(self, workflow, transcript):
            observed["workflow_id"] = workflow["id"]
            observed["transcript"] = transcript
            return {"ok": True, "speech": "done", "tools_used": []}

    modules = {
        "workflow_loader": SimpleNamespace(WorkflowLoader=FakeWorkflowLoader),
        "executor": SimpleNamespace(ToolExecutor=FakeToolExecutor),
        "pipeline_executor": SimpleNamespace(PipelineExecutor=FakePipelineExecutor),
        "tool_schema": SimpleNamespace(get_tool_registry=lambda mode=None: shared_registry),
    }
    request = WorkflowExecuteRequest(mode="cloud", query="today")
    with patch.dict(sys.modules, modules):
        result = asyncio.run(execute_workflow("secret_radar", request))

    assert result.ok is True
    assert observed == {
        "tool_mode": "cloud",
        "registry": shared_registry,
        "pipeline_mode": "cloud",
        "workflow_id": "private_radar",
        "transcript": "/private_radar today",
    }


def test_workflow_api_alias_resolution_does_not_prefix_match():
    loader = SimpleNamespace(
        workflows={
            "private_radar": {
                "id": "private_radar",
                "triggers": {"explicit": ["/private_radar", "/secret_radar"]},
            }
        },
        get_workflow=lambda workflow_id: None,
    )

    assert _resolve_workflow(loader, "secret_radar")["id"] == "private_radar"
    assert _resolve_workflow(loader, "secret") is None


def test_scheduled_query_uses_task_scope_not_runner_mode(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cloud.env").write_text("LLM_PROVIDER=xai\nXAI_MODEL=grok-cloud\n")
    (config_dir / "local.env").write_text("LLM_PROVIDER=ollama\nOLLAMA_MODEL=gemma-local\n")
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)
    monkeypatch.setenv("JARVIS_MODE", "cloud")
    observed = {}

    class FakeOrchestrator:
        def __init__(self, mode):
            observed["constructor_mode"] = mode
            observed["active_mode"] = get_active_config_mode()
            observed["provider"] = get_config_value("LLM_PROVIDER")

        def process(self, query):
            return {"ok": True, "speech": query}

    with patch.dict(sys.modules, {"orchestrator_v2": SimpleNamespace(Orchestrator=FakeOrchestrator)}):
        result = scheduled_task_runner._run_query_task("local", "probe")

    assert result["ok"] is True
    assert observed == {
        "constructor_mode": "local",
        "active_mode": "local",
        "provider": "ollama",
    }
    assert get_active_config_mode() == "cloud"


def test_scheduled_workflow_uses_shared_tool_registry(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cloud.env").write_text("LLM_PROVIDER=xai\nXAI_MODEL=grok-cloud\n")
    (config_dir / "local.env").write_text("LLM_PROVIDER=ollama\nOLLAMA_MODEL=gemma-local\n")
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)
    monkeypatch.setenv("JARVIS_MODE", "cloud")
    observed = {}
    shared_registry = object()

    class FakeWorkflowLoader:
        def __init__(self, explicit_only=True):
            observed["loader_explicit_only"] = explicit_only
            self.workflows = {}

        def get_workflow(self, workflow_id):
            return {
                "id": workflow_id,
                "triggers": {"explicit": [f"/{workflow_id}"]},
                "steps": [{"step": 1, "tool": "get_time"}],
            }

    class FakeToolExecutor:
        def __init__(self, mode, registry=None):
            observed["tool_mode"] = mode
            observed["registry"] = registry

    class FakePipelineExecutor:
        def __init__(self, mode, _executor):
            observed["active_mode"] = get_active_config_mode()
            observed["provider"] = get_config_value("LLM_PROVIDER")
            observed["pipeline_mode"] = mode

        def execute(self, workflow, transcript):
            observed["workflow_id"] = workflow["id"]
            observed["transcript"] = transcript
            return {"ok": True, "speech": "done", "tools_used": []}

    modules = {
        "workflow_loader": SimpleNamespace(WorkflowLoader=FakeWorkflowLoader),
        "executor": SimpleNamespace(ToolExecutor=FakeToolExecutor),
        "pipeline_executor": SimpleNamespace(PipelineExecutor=FakePipelineExecutor),
        "tool_schema": SimpleNamespace(get_tool_registry=lambda mode=None: shared_registry),
    }
    with patch.dict(sys.modules, modules):
        result = scheduled_task_runner._run_workflow_task("local", "github_ai_radar_daily")

    assert result["ok"] is True
    assert observed == {
        "loader_explicit_only": True,
        "tool_mode": "local",
        "registry": shared_registry,
        "active_mode": "local",
        "provider": "ollama",
        "pipeline_mode": "local",
        "workflow_id": "github_ai_radar_daily",
        "transcript": "/github_ai_radar_daily",
    }
    assert get_active_config_mode() == "cloud"


def test_scheduled_execution_identity_is_mode_aware(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cloud.env").write_text("LLM_PROVIDER=xai\nXAI_MODEL=grok-cloud\n")
    (config_dir / "local.env").write_text(
        "LLM_PROVIDER=ollama\nOLLAMA_MODEL=gemma-local\n"
    )
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)
    monkeypatch.setenv("JARVIS_MODE", "cloud")

    assert scheduled_task_runner._execution_identity("cloud") == ("xai", "grok-cloud")
    assert scheduled_task_runner._execution_identity("local") == ("ollama", "gemma-local")


@pytest.mark.parametrize(
    "factory",
    [
        lambda: QueryRequest(query="probe", mode="locla"),
        lambda: WorkflowExecuteRequest(query="probe", mode="locla"),
        lambda: ScheduledTaskCreate(
            name="probe",
            task_type=ScheduledTaskType.QUERY,
            query="probe",
            when="tomorrow",
            mode="locla",
        ),
        lambda: ScheduledTaskUpdate(mode="locla"),
    ],
)
def test_request_models_reject_invalid_modes(factory):
    with pytest.raises(ValidationError):
        factory()
