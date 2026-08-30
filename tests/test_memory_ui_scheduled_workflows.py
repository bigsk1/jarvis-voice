#!/usr/bin/env python3
"""Jarvis Memory scheduled-task workflow picker regressions."""

import sys
from pathlib import Path

from flask import Flask

from server_package_utils import load_server_package


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-memory"))
load_server_package("jarvis_memory_test_server", PROJECT_ROOT / "jarvis-memory" / "server")

from jarvis_memory_test_server.routes import scheduled_tasks as scheduled_tasks_route  # noqa: E402


def test_scheduled_task_workflow_list_uses_loaded_workflows(monkeypatch):
    class FakeWorkflowLoader:
        def __init__(self, explicit_only=True):
            self.explicit_only = explicit_only
            self.workflows = {
                "daily_status": {
                    "id": "daily_status",
                    "name": "Daily Status",
                    "description": "Daily dashboard workflow",
                    "version": "1.0",
                    "variables": {
                        "topic": {"from": "query", "extract": "main_subject"},
                        "style": {"from": "query", "extract": "remainder", "default": ""},
                    },
                    "triggers": {"explicit": ["/daily_status"]},
                    "steps": [
                        {"step": 1, "tool": "get_time"},
                        {"step": 2, "tool": "canvas"},
                        {"step": 3, "tool": "canvas"},
                    ],
                },
                "jarvis_self_check": {
                    "id": "jarvis_self_check",
                    "name": "Jarvis Self Check",
                    "description": "Check local Jarvis host health",
                    "triggers": {"explicit": ["/jarvis_self_check"]},
                    "steps": [{"step": 1, "tool": "system_monitor"}],
                },
            }

    monkeypatch.setattr(scheduled_tasks_route, "WorkflowLoader", FakeWorkflowLoader)
    monkeypatch.setattr(
        scheduled_tasks_route,
        "get_tool_registry",
        lambda mode=None: type(
            "Registry",
            (),
            {"list_tools": lambda self: ["get_time", "canvas"]},
        )(),
    )
    app = Flask(__name__)
    app.register_blueprint(scheduled_tasks_route.scheduled_tasks_bp)

    response = app.test_client().get("/api/scheduled-tasks/workflows")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["count"] == 1
    assert [workflow["id"] for workflow in payload["workflows"]] == [
        "daily_status",
    ]
    assert payload["workflows"][0]["name"] == "Daily Status"
    assert payload["workflows"][0]["trigger"] == "/daily_status"
    assert payload["workflows"][0]["triggers"] == ["/daily_status"]
    assert payload["workflows"][0]["requires_input"] is True
    assert payload["workflows"][0]["input_fields"] == [
        {"name": "topic", "extract": "main_subject", "required": True},
        {"name": "style", "extract": "remainder", "required": False},
    ]
    assert payload["workflows"][0]["tools_used"] == ["get_time", "canvas"]


def test_scheduled_task_create_returns_400_for_bad_schedule(monkeypatch):
    class FakeManager:
        def create_task(self, **_kwargs):
            raise ValueError("Could not parse schedule expression: nope")

    monkeypatch.setattr(scheduled_tasks_route, "get_manager", lambda: FakeManager())
    app = Flask(__name__)
    app.register_blueprint(scheduled_tasks_route.scheduled_tasks_bp)

    response = app.test_client().post(
        "/api/scheduled-tasks",
        json={
            "name": "Bad schedule",
            "task_type": "query",
            "query": "status",
            "when": "nope",
        },
    )
    payload = response.get_json()

    assert response.status_code == 400
    assert payload == {
        "ok": False,
        "error": "Could not parse schedule expression: nope",
    }
