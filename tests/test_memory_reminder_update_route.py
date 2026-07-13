"""Regression coverage for Jarvis Memory reminder updates."""

import importlib.util
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]


def _load_reminder_routes():
    path = ROOT / "jarvis-memory/server/routes/reminders.py"
    spec = importlib.util.spec_from_file_location("memory_reminder_routes", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeReminderManager:
    def __init__(self):
        self.updated = None
        self.existing = {
            "id": 7,
            "title": "Keep title",
            "description": "Old description",
            "trigger_time": "2026-07-13T12:00:00",
            "related_intel_file": "old.md",
            "callback_url": "https://old.example",
            "recurrence_rule": "DAILY",
            "metadata": {"source": "test"},
        }

    def get_reminder(self, _reminder_id):
        if self.updated is None:
            return dict(self.existing)
        return {**self.existing, **self.updated}

    def update_reminder(self, **kwargs):
        self.updated = kwargs
        return True


def test_update_reminder_allows_optional_fields_to_be_cleared():
    routes = _load_reminder_routes()
    manager = FakeReminderManager()
    routes.get_manager = lambda: manager
    app = Flask(__name__)
    app.register_blueprint(routes.reminders_bp)

    response = app.test_client().put(
        "/api/reminders/7",
        json={
            "description": None,
            "related_intel_file": None,
            "callback_url": None,
            "recurrence_rule": None,
        },
    )

    assert response.status_code == 200
    assert manager.updated["description"] is None
    assert manager.updated["related_intel_file"] is None
    assert manager.updated["callback_url"] is None
    assert manager.updated["recurrence_rule"] is None
    assert manager.updated["title"] == "Keep title"
    assert manager.updated["trigger_time"] == "2026-07-13T12:00:00"
    assert manager.updated["metadata"] == {"source": "test"}
