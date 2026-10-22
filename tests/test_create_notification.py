"""Tool/API/workflow entry points share the durable quiet-notification writer."""

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from lib.config_loader import config_scope
from lib.notifications import NotificationStore

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "notification_skill_test", ROOT / "skills/create_notification.py"
)
assert SPEC is not None and SPEC.loader is not None
skill = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(skill)


def test_tool_saves_without_ntfy_and_reports_unavailable_not_sent(tmp_path):
    with config_scope("local"):
        result = skill.run(
            {
                "title": "Cleanup complete",
                "message": "All stages succeeded.",
                "dedupe_key": "run-7",
            },
            root=tmp_path,
        )
    assert result["ok"]
    assert "unavailable" in result["speech"] and "sent" not in result["speech"]
    assert result["data"]["mode"] == "local"
    assert result["data"]["deliveries"] == [
        {"channel": "ntfy", "state": "unavailable", "error": "ntfy_unconfigured"}
    ]
    assert NotificationStore(tmp_path, "cloud").list_history()["total"] == 0
    rows = NotificationStore(tmp_path, "local").list_history()["items"]
    assert rows[0]["id"] == result["data"]["id"]
    assert not (tmp_path / "data/jarvis_memory_local.db").exists()


def test_tool_same_occurrence_is_saved_once_and_new_occurrence_is_independent(tmp_path):
    args = {
        "title": "Update",
        "message": "A release is available.",
        "source": "radar",
        "channels": [],
        "dedupe_key": "release-7",
    }
    first = skill.run(args, root=tmp_path, mode="cloud")
    duplicate = skill.run(args, root=tmp_path, mode="cloud")
    other = skill.run({**args, "dedupe_key": "release-8"}, root=tmp_path, mode="cloud")
    assert first["data"]["id"] == duplicate["data"]["id"]
    assert duplicate["data"]["deduplicated"] is True
    assert other["data"]["id"] != first["data"]["id"]
    assert NotificationStore(tmp_path, "cloud").list_history()["total"] == 2


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"title": "x"},
        {"title": "x", "message": "y", "server_url": "https://example.test"},
        {"title": "x", "message": "y", "channels": ["discord"]},
    ],
)
def test_tool_rejects_invalid_arguments_without_creating_storage(tmp_path, payload):
    with pytest.raises(ValueError):
        skill.run(payload, root=tmp_path, mode="cloud")
    assert not (tmp_path / "data").exists()


def test_command_errors_are_json_nonzero_and_do_not_block_on_stdin(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["create_notification.py"])
    assert skill.main() == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
    monkeypatch.setattr(
        sys, "argv", ["create_notification.py", '{"publisher_token":"SECRET_SENTINEL"}']
    )
    monkeypatch.setattr(skill, "load_config", lambda: None)
    assert skill.main() == 1
    assert "SECRET_SENTINEL" not in capsys.readouterr().out


def test_tool_storage_failure_is_json_and_does_not_expose_exception(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["create_notification.py", '{"title":"x","message":"y"}'])
    monkeypatch.setattr(skill, "load_config", lambda: None)

    def unavailable(*_args, **_kwargs):
        raise sqlite3.OperationalError("PRIVATE_PATH_SENTINEL")

    monkeypatch.setattr(skill, "run", unavailable)
    assert skill.main() == 1
    output = capsys.readouterr().out
    assert json.loads(output)["error"] == "Notification storage is unavailable."
    assert "PRIVATE_PATH_SENTINEL" not in output


def test_manifest_does_not_require_ntfy_or_inherit_provider_credentials():
    manifest = json.loads((ROOT / "skills/create_notification.tool.json").read_text())
    assert manifest["enabled"] and "availability" not in manifest
    assert manifest["child_environment"] == {"mode": "restricted", "allow": []}
    assert manifest["permissions"]["network"] is False
    assert manifest["parameters"]["additionalProperties"] is False


def test_manual_notification_workflow_runs_without_a_model_or_alert(tmp_path):
    from orchestrator.pipeline_executor import PipelineExecutor

    workflow = json.loads((ROOT / "data/workflows/notification_test.json").read_text())
    calls = []

    class Executor:
        def execute(self, name, args):
            calls.append(name)
            if name == "get_time":
                return {"ok": True, "data": {"time_12h": "03:00 AM", "date": "2026-10-22"}}
            assert name == "create_notification"
            return skill.run(args, root=tmp_path, mode="local")

    class NoModel:
        def chat_with_tools(self, **_kwargs):
            pytest.fail("A deterministic notification workflow must not call a model")

    with config_scope("local", {"LLM_PROVIDER": "ollama"}):
        result = PipelineExecutor("local", Executor(), provider=NoModel()).execute(
            workflow, "/notification_test"
        )
    assert result["ok"], result
    assert calls == ["get_time", "create_notification"]
    assert workflow["allow_workflow_tool"] is False
    item = NotificationStore(tmp_path, "local").list_history()["items"][0]
    assert item["message"] == "Manual workflow test at 03:00 AM UTC on 2026-10-22."
    assert item["state"] == "unavailable"
    assert not (tmp_path / "data/jarvis_memory_local.db").exists()
