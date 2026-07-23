"""Web slash-command workflow availability regressions."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from flask import Flask

from server_package_utils import load_server_package


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))
load_server_package(
    "jarvis_web_workflow_availability_test",
    PROJECT_ROOT / "jarvis-web" / "server",
)

from jarvis_web_workflow_availability_test.routes import api  # noqa: E402


def _client():
    app = Flask(__name__)
    app.register_blueprint(api.api_bp)
    return app.test_client()


def _install_workflow_loader(monkeypatch):
    class FakeWorkflowLoader:
        def __init__(self, explicit_only=True):
            self.workflows = {
                "ready": {
                    "id": "ready",
                    "name": "Ready",
                    "triggers": {"explicit": ["/ready"]},
                    "steps": [{"step": 1, "tool": "get_time"}],
                },
                "blocked": {
                    "id": "blocked",
                    "name": "Blocked",
                    "triggers": {"explicit": ["/blocked"]},
                    "steps": [{"step": 1, "tool": "send_email"}],
                },
            }

        def get_workflow(self, workflow_id):
            return self.workflows.get(workflow_id)

    monkeypatch.setitem(
        sys.modules,
        "workflow_loader",
        SimpleNamespace(WorkflowLoader=FakeWorkflowLoader),
    )


def _install_tool_surface(monkeypatch):
    service = SimpleNamespace(
        get_tools=lambda include_blocked=True: [
            {
                "name": "get_time",
                "enabled": True,
                "available": True,
                "blocked": False,
            },
            {
                "name": "send_email",
                "enabled": False,
                "available": True,
                "blocked": True,
            },
        ]
    )
    monkeypatch.setattr(api, "get_tool_service", lambda: service)


def test_web_workflow_list_hides_workflow_with_blocked_tool(monkeypatch):
    _install_workflow_loader(monkeypatch)
    _install_tool_surface(monkeypatch)

    response = _client().get("/api/workflows")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["count"] == 1
    assert list(payload["workflows"]) == ["ready"]


def test_web_workflow_detail_rejects_workflow_with_blocked_tool(monkeypatch):
    _install_workflow_loader(monkeypatch)
    _install_tool_surface(monkeypatch)

    response = _client().get("/api/workflows/blocked")
    payload = response.get_json()

    assert response.status_code == 409
    assert "send_email" in payload["error"]
