"""Authenticated notification history and secret-preserving channel switches."""

import ast
import importlib
import json
import sqlite3
import subprocess
from pathlib import Path

import pytest
from filelock import FileLock
from flask import Blueprint, Flask, jsonify, request
from server_package_utils import load_server_package

from lib import ntfy_notifications
from lib.notifications import NotificationStore

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "jarvis_notifications_web_test"
load_server_package(PACKAGE, ROOT / "jarvis-web/server")
service = importlib.import_module(PACKAGE + ".services.notifications")
LOGIN = {"Authorization": "Bearer test-login"}


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "ROOT", tmp_path)
    monkeypatch.setattr(ntfy_notifications, "publish", lambda *_: pytest.fail("Unexpected publish"))
    monkeypatch.setattr(ntfy_notifications.urllib.request, "build_opener",
                        lambda *_: pytest.fail("Unexpected HTTP request"))
    return tmp_path


def configure(root, **changes):
    folder = root / "config"
    folder.mkdir(exist_ok=True)
    path = folder / "ntfy.json"
    value = {"enabled": True, "server_url": "https://private.example.test",
             "publisher_token": "tk_" + "a" * 29, "include_descriptions": True,
             "alerts": {"enabled": True, "topic": "private-alerts", "severities": ["critical"]},
             **changes}
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return path


@pytest.fixture
def client(isolated, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "lib"))
    import webui_auth

    monkeypatch.setattr(webui_auth, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(webui_auth, "get_token_from_request",
                        lambda req: req.headers.get("Authorization"))
    monkeypatch.setattr(webui_auth, "verify_token", lambda value: value == LOGIN["Authorization"])
    app = Flask(__name__)
    blueprint = Blueprint("api", __name__, url_prefix="/api")
    scope = {"api_bp": blueprint, "jsonify": jsonify, "request": request,
             "require_auth": webui_auth.require_auth, "__package__": PACKAGE + ".routes",
             "functools": importlib.import_module("functools"),
             "get_web_setting": lambda *_: "cloud", "_apply_tts_provider_override": lambda *_: None,
             "_get_status_overrides": lambda *_: {}}
    source = ast.parse((ROOT / "jarvis-web/server/routes/api.py").read_text())
    for node in source.body:
        if isinstance(node, ast.FunctionDef) and node.name in {
            "_scoped_request_config", "get_notifications_route", "notification_channels_route"
        }:
            exec(compile(ast.Module(body=[node], type_ignores=[]), "api.py", "exec"), scope)
    app.register_blueprint(blueprint)
    return app.test_client()


def test_history_and_settings_require_auth_before_access(client, monkeypatch):
    monkeypatch.setattr(service, "get_history", lambda *_args, **_kwargs: pytest.fail("Unauthenticated read"))
    monkeypatch.setattr(service, "get_channels", lambda: pytest.fail("Unauthenticated read"))
    monkeypatch.setattr(service, "update_channels", lambda *_: pytest.fail("Unauthenticated write"))
    for headers in ({}, {"Authorization": "Bearer wrong"}):
        assert client.get("/api/notifications", headers=headers).status_code == 401
        assert client.get("/api/notifications/channels", headers=headers).status_code == 401
        assert client.patch("/api/notifications/channels", headers=headers,
                            json={"enabled": False}).status_code == 401


def test_empty_history_and_unconfigured_channels_do_not_create_stores(client, isolated):
    result = client.get("/api/notifications?mode=local", headers=LOGIN)
    assert result.status_code == 200
    assert result.json == {"ok": True, "items": [], "total": 0, "limit": 25, "offset": 0}
    assert result.headers["Cache-Control"] == "private, no-store"
    channels = client.get("/api/notifications/channels", headers=LOGIN)
    assert channels.json["configuration"] == "missing"
    assert not channels.json["editable"]
    assert client.patch("/api/notifications/channels", headers=LOGIN,
                        json={"enabled": True}).status_code == 409
    assert list(isolated.iterdir()) == []


def test_channel_switches_preserve_private_fields_across_reload(client, isolated):
    path = configure(isolated)
    original = json.loads(path.read_text())
    response = client.get("/api/notifications/channels", headers=LOGIN)
    assert response.json["categories"] == {"alerts": True, "reminders": True,
                                          "background_tasks": False, "notifications": True}
    assert response.json["editable"]
    response = client.patch("/api/notifications/channels", headers=LOGIN,
                            json={"categories": {"alerts": False, "notifications": False}})
    assert response.status_code == 200 and not response.json["categories"]["notifications"]
    updated = json.loads(path.read_text())
    assert updated["publisher_token"] == original["publisher_token"]
    assert updated["server_url"] == original["server_url"]
    assert updated["alerts"] == {**original["alerts"], "enabled": False}
    assert updated["include_descriptions"] is True
    assert path.stat().st_mode & 0o777 == 0o600
    assert client.get("/api/notifications/channels", headers=LOGIN).json == response.json
    for forbidden in ("tk_", "private.example", "private-alerts", "severities", "publisher_token"):
        assert forbidden not in response.get_data(as_text=True)
    assert client.patch("/api/notifications/channels", headers=LOGIN,
                        json={"enabled": False}).json["enabled"] is False
    assert client.patch("/api/notifications/channels", headers=LOGIN,
                        json={"enabled": True}).json["enabled"] is True
    assert not (isolated / "data").exists()


@pytest.mark.parametrize("payload", [None, [], {}, {"enabled": 1}, {"enabled": "false"},
    {"publisher_token": "new"}, {"server_url": "https://elsewhere.test"},
    {"categories": {}}, {"categories": []}, {"categories": {"unknown": True}},
    {"categories": {"alerts": "false"}}, {"categories": {"alerts": {"enabled": True}}},
    {"mode": "local", "enabled": False}])
def test_invalid_switches_do_not_mutate_config(client, isolated, payload):
    path = configure(isolated)
    before = path.read_bytes()
    response = client.patch("/api/notifications/channels", headers=LOGIN,
                            data=json.dumps(payload), content_type="application/json")
    assert response.status_code == 400
    assert path.read_bytes() == before


def test_invalid_or_public_config_cannot_be_repaired_or_enabled_by_ui(client, isolated):
    path = configure(isolated)
    path.chmod(0o644)
    assert client.get("/api/notifications/channels", headers=LOGIN).json["editable"] is False
    before = path.read_bytes()
    assert client.patch("/api/notifications/channels", headers=LOGIN,
                        json={"enabled": False}).status_code == 409
    assert path.read_bytes() == before
    path.chmod(0o600)
    path.write_text('{"enabled":false}')
    assert client.get("/api/notifications/channels", headers=LOGIN).json["editable"] is False
    assert client.patch("/api/notifications/channels", headers=LOGIN,
                        json={"enabled": True}).status_code == 409


def test_read_only_mount_disables_controls_and_rejects_writes(client, isolated, monkeypatch):
    path = configure(isolated)
    original = path.read_bytes()
    monkeypatch.setattr(service.os, "access", lambda *_: False)
    result = client.get("/api/notifications/channels", headers=LOGIN)
    assert result.json["configured"] and result.json["read_only"]
    assert not result.json["editable"]
    result = client.patch("/api/notifications/channels", headers=LOGIN, json={"enabled": False})
    assert result.status_code == 503 and "host" in result.json["error"]
    assert path.read_bytes() == original


def test_locked_or_failed_save_leaves_original_config(client, isolated, monkeypatch):
    path = configure(isolated)
    original = path.read_bytes()
    with FileLock(str(path) + ".lock"):
        assert client.patch("/api/notifications/channels", headers=LOGIN,
                            json={"enabled": False}).status_code == 409
    monkeypatch.setattr(service.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("private")))
    response = client.patch("/api/notifications/channels", headers=LOGIN,
                            json={"enabled": False})
    assert response.status_code == 503 and "private" not in response.get_data(as_text=True)
    assert path.read_bytes() == original
    assert not list(path.parent.glob(".ntfy-*"))


def test_history_mode_filters_pagination_and_local_only_records(client, isolated):
    cloud = NotificationStore(isolated, "cloud")
    cloud.create("First", "Saved body", source="cleanup", channels=[])
    cloud.create("Second", "Other source", source="radar", channels=[])
    NotificationStore(isolated, "local").create("Local", "Local body", channels=[])
    result = client.get("/api/notifications?mode=cloud&source_type=notifications&state=saved&limit=1", headers=LOGIN)
    assert result.status_code == 200 and result.json["total"] == 2
    assert len(result.json["items"]) == 1 and result.json["items"][0]["mode"] == "cloud"
    second = client.get("/api/notifications?mode=cloud&limit=1&offset=1", headers=LOGIN)
    assert second.json["items"][0]["id"] != result.json["items"][0]["id"]
    filtered = client.get("/api/notifications?mode=cloud&source=cleanup", headers=LOGIN)
    assert filtered.json["total"] == 1 and filtered.json["items"][0]["title"] == "First"
    assert client.get("/api/notifications?mode=local", headers=LOGIN).json["total"] == 1
    assert client.get("/api/notifications?mode=cloud&channel=ntfy", headers=LOGIN).json["total"] == 0


@pytest.mark.parametrize("query", ["mode=invalid", "limit=0", "limit=101", "limit=abc", "offset=-1",
    "offset=999999999999999999999999999999", "offset=1000001", "channel=email", "state=invented",
    "source=%00", "source=" + "x" * 81, "source_type=invented"])
def test_invalid_history_parameters_fail_without_source_reads(client, query):
    assert client.get("/api/notifications?" + query, headers=LOGIN).status_code == 400


def test_history_pending_outages_are_truthful_and_sanitized(client, isolated, monkeypatch):
    configure(isolated)
    event = NotificationStore(isolated, "cloud").create("Release", "Ready", source="watch")
    result = client.get("/api/notifications?state=pending", headers=LOGIN)
    assert result.status_code == 200
    assert result.json["items"][0]["id"] == event["id"]
    assert result.json["items"][0]["deliveries"][0]["state"] == "pending"
    monkeypatch.setattr(NotificationStore, "list_history",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("private")))
    response = client.get("/api/notifications", headers=LOGIN)
    assert response.status_code == 503 and "private" not in response.get_data(as_text=True)


def test_notifications_browser_lifecycle():
    result = subprocess.run(["node", "--test", str(ROOT / "tests/notifications_ui.test.js")],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_notification_scripts_and_tab_are_in_shipped_page():
    html = (ROOT / "jarvis-web/client/index.html").read_text()
    assert 'data-settings-tab="notifications"' in html
    assert html.index('id="settings-notifications"') < html.index('id="ntfy-status"') < html.index('id="settings-profile"')
    assert html.index('/js/ntfy-status.js') < html.index('/js/notifications.js') < html.index('/js/app.js')
