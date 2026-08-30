#!/usr/bin/env python3
"""Scheduled workflow input persistence regressions."""

import json
import sys
from types import SimpleNamespace

import pytest

from api.managers import scheduled_task_manager as scheduled_task_manager_module
from api.managers.scheduled_task_manager import ScheduledTaskManager
from services import scheduled_task_runner


def _manager(tmp_path) -> ScheduledTaskManager:
    manager = object.__new__(ScheduledTaskManager)
    manager.mode = "cloud"
    manager.db = SimpleNamespace(db_path=str(tmp_path / "scheduled.db"))
    manager._ensure_tables()
    return manager


def test_workflow_task_preserves_optional_query_input(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    monkeypatch.setattr(
        ScheduledTaskManager,
        "_resolve_workflow_id",
        staticmethod(lambda workflow_id, **_kwargs: workflow_id),
    )

    task_id = manager.create_task(
        name="Deep dive URL",
        task_type="workflow",
        workflow_id="deep_dive",
        query="https://example.com/research",
        when="now",
        timezone_name="America/Los_Angeles",
    )

    task = manager.get_task(task_id)
    payload = json.loads(task["task_payload"])

    assert task["task_target"] == "deep_dive"
    assert payload["workflow_id"] == "deep_dive"
    assert payload["query"] == "https://example.com/research"
    assert payload["when_original"] == "now"
    assert payload["schedule_summary"] == "Once immediately"


def test_workflow_task_preserves_every_week_on_weekday_recurrence(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    monkeypatch.setattr(
        ScheduledTaskManager,
        "_resolve_workflow_id",
        staticmethod(lambda workflow_id, **_kwargs: workflow_id),
    )

    task_id = manager.create_task(
        name="Upcoming Movies Emailed",
        task_type="workflow",
        workflow_id="upcoming_movie_radar",
        query="science fiction, exclude animation and anime, next 90 days, email",
        when="every week on friday at 10am",
        timezone_name="America/Los_Angeles",
    )

    task = manager.get_task(task_id)
    payload = json.loads(task["task_payload"])

    assert task["schedule_type"] == "weekly"
    assert json.loads(task["schedule_expr"]) == {"days": [4], "hour": 10, "minute": 0}
    assert payload["when_original"] == "every week on friday at 10am"
    assert payload["schedule_summary"] == "Every Friday at 10:00 AM"


def test_workflow_task_update_preserves_query_input(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    monkeypatch.setattr(
        ScheduledTaskManager,
        "_resolve_workflow_id",
        staticmethod(lambda workflow_id, **_kwargs: workflow_id),
    )
    task_id = manager.create_task(
        name="Deep dive URL",
        task_type="workflow",
        workflow_id="deep_dive",
        when="tomorrow at 10am",
        timezone_name="America/Los_Angeles",
    )

    assert manager.update_task(task_id, query="https://example.com/updated")
    payload = json.loads(manager.get_task(task_id)["task_payload"])

    assert payload["query"] == "https://example.com/updated"


def test_workflow_task_creation_rejects_unavailable_workflow(tmp_path, monkeypatch):
    class FakeWorkflowLoader:
        def __init__(self, explicit_only=True):
            self.workflows = {
                "disabled_workflow": {
                    "id": "disabled_workflow",
                    "name": "Disabled Workflow",
                    "triggers": {"explicit": ["/disabled_workflow"]},
                    "steps": [{"step": 1, "tool": "disabled_tool"}],
                }
            }

        def get_workflow(self, workflow_id):
            return self.workflows.get(workflow_id)

    monkeypatch.setattr(
        scheduled_task_manager_module,
        "WorkflowLoader",
        FakeWorkflowLoader,
    )
    monkeypatch.setitem(
        sys.modules,
        "tool_schema",
        type(
            "Module",
            (),
            {
                "get_tool_registry": staticmethod(
                    lambda mode=None: SimpleNamespace(list_tools=lambda: ["get_time"])
                )
            },
        ),
    )
    manager = _manager(tmp_path)

    with pytest.raises(ValueError, match="disabled_tool"):
        manager.create_task(
            name="Unavailable workflow",
            task_type="workflow",
            workflow_id="disabled_workflow",
            when="now",
            timezone_name="America/Los_Angeles",
        )


def test_runner_prefixes_workflow_input_with_trigger(monkeypatch):
    observed = {}

    class FakeWorkflowLoader:
        def __init__(self, explicit_only=True):
            self.workflows = {
                "deep_dive": {
                    "id": "deep_dive",
                    "triggers": {"explicit": ["/deep_dive"]},
                    "steps": [{"step": 1, "tool": "get_time"}],
                }
            }

        def get_workflow(self, workflow_id):
            return self.workflows.get(workflow_id)

    class FakeToolExecutor:
        def __init__(self, mode, registry=None):
            pass

    class FakePipelineExecutor:
        def __init__(self, mode, tool_executor):
            pass

        def execute(self, workflow, transcript):
            observed["workflow_id"] = workflow["id"]
            observed["transcript"] = transcript
            return {"ok": True}

    shared_registry = SimpleNamespace(list_tools=lambda: ["get_time"])
    modules = {
        "workflow_loader": type("Module", (), {"WorkflowLoader": FakeWorkflowLoader}),
        "executor": type("Module", (), {"ToolExecutor": FakeToolExecutor}),
        "pipeline_executor": type("Module", (), {"PipelineExecutor": FakePipelineExecutor}),
        "tool_schema": type("Module", (), {"get_tool_registry": staticmethod(lambda mode=None: shared_registry)}),
    }
    monkeypatch.setitem(sys.modules, "workflow_loader", modules["workflow_loader"])
    monkeypatch.setitem(sys.modules, "executor", modules["executor"])
    monkeypatch.setitem(sys.modules, "pipeline_executor", modules["pipeline_executor"])
    monkeypatch.setitem(sys.modules, "tool_schema", modules["tool_schema"])

    result = scheduled_task_runner._run_workflow_task(
        "cloud",
        "deep_dive",
        "https://example.com/product",
    )

    assert result["ok"] is True
    assert observed == {
        "workflow_id": "deep_dive",
        "transcript": "/deep_dive https://example.com/product",
    }


def test_runner_does_not_start_workflow_with_unavailable_tool(monkeypatch):
    class FakeWorkflowLoader:
        def __init__(self, explicit_only=True):
            self.workflows = {}

        def get_workflow(self, workflow_id):
            return {
                "id": workflow_id,
                "name": "Disabled Workflow",
                "triggers": {"explicit": [f"/{workflow_id}"]},
                "steps": [{"step": 1, "tool": "disabled_tool"}],
            }

    shared_registry = SimpleNamespace(list_tools=lambda: ["get_time"])
    modules = {
        "workflow_loader": type("Module", (), {"WorkflowLoader": FakeWorkflowLoader}),
        "executor": type(
            "Module",
            (),
            {
                "ToolExecutor": lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("blocked workflow must not create an executor")
                )
            },
        ),
        "pipeline_executor": type(
            "Module",
            (),
            {
                "PipelineExecutor": lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("blocked workflow must not create a pipeline")
                )
            },
        ),
        "tool_schema": type(
            "Module",
            (),
            {"get_tool_registry": staticmethod(lambda mode=None: shared_registry)},
        ),
    }
    monkeypatch.setitem(sys.modules, "workflow_loader", modules["workflow_loader"])
    monkeypatch.setitem(sys.modules, "executor", modules["executor"])
    monkeypatch.setitem(sys.modules, "pipeline_executor", modules["pipeline_executor"])
    monkeypatch.setitem(sys.modules, "tool_schema", modules["tool_schema"])

    result = scheduled_task_runner._run_workflow_task("cloud", "disabled_workflow")

    assert result["ok"] is False
    assert result["steps_completed"] == 0
    assert result["data"]["availability"]["unavailable_tools"] == ["disabled_tool"]
