#!/usr/bin/env python3
"""Regression coverage for the Jarvis Web user-profile editor bridge."""

from __future__ import annotations

import importlib.util
import json
import sys
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import call, patch

import pytest
import requests
import yaml


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "jarvis-web"
CLIENT_HTML = (WEB_ROOT / "client" / "index.html").read_text(encoding="utf-8")
CLIENT_JS = (WEB_ROOT / "client" / "js" / "app.js").read_text(encoding="utf-8")
MEMORY_JS = (ROOT / "jarvis-memory" / "client" / "js" / "app.js").read_text(
    encoding="utf-8"
)

sys.path.insert(0, str(ROOT / "lib"))


def _load_service():
    module_name = "jarvis_web_user_profile_service_test"
    sys.modules.pop(module_name, None)
    path = WEB_ROOT / "server" / "services" / "user_profile_service.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_web_app():
    for key in list(sys.modules):
        if key == "server" or key.startswith("server."):
            del sys.modules[key]
    web_root = str(WEB_ROOT)
    if web_root in sys.path:
        sys.path.remove(web_root)
    sys.path.insert(0, web_root)
    from server.app import app

    return app


class _Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _profile_payload(content: str, *, ingested=False, fact_count=None):
    return {
        "ok": True,
        "content": content,
        "file": {
            "filename": "user-profile.md",
            "modified_at": "2026-08-13T00:00:00",
            "ingested": ingested,
            "fact_count": fact_count,
        },
    }


def test_missing_profile_returns_tracked_starter(monkeypatch):
    service = _load_service()
    monkeypatch.setattr(service, "_intel_request", lambda *args, **kwargs: _Response(404, {}))

    result = service.get_user_profile()

    assert result["exists"] is False
    assert result["content"] == ""
    assert "## Profile Card" in result["starter_template"]
    assert "## Profile Reference" in result["starter_template"]


def test_create_uses_fastapi_intel_route_with_auto_ingest(monkeypatch):
    service = _load_service()
    content = "# User Profile\n\n## Profile Card\n\n- **Who**: Tester\n"
    responses = iter([
        _Response(404, {}),
        _Response(200, {
            "ok": True,
            "ingestion_started": True,
            "ingest_modes": ["cloud", "local"],
            "ingest_warning": None,
        }),
        _Response(200, _profile_payload(content)),
    ])
    calls = []

    def fake_request(method, path, *, payload=None):
        calls.append((method, path, payload))
        return next(responses)

    monkeypatch.setattr(service, "_intel_request", fake_request)
    result = service.save_user_profile(
        content,
        mode="cloud",
        expected_exists=False,
        expected_revision=None,
    )

    assert calls[1] == (
        "POST",
        "/api/intel?mode=cloud",
        {
            "filename": "user-profile.md",
            "content": content,
            "auto_ingest": True,
        },
    )
    assert calls[0][1] == "/api/intel/user-profile.md?mode=cloud"
    assert calls[2][1] == "/api/intel/user-profile.md?mode=cloud"
    assert result["exists"] is True
    assert result["ingestion_started"] is True
    assert result["ingest_modes"] == ["cloud", "local"]


def test_update_rejects_stale_revision_before_writing(monkeypatch):
    service = _load_service()
    current = "# User Profile\n\n## Profile Card\n\n- **Who**: Current\n"
    calls = []

    def fake_request(method, path, *, payload=None):
        calls.append((method, path, payload))
        return _Response(200, _profile_payload(current))

    monkeypatch.setattr(service, "_intel_request", fake_request)
    with pytest.raises(service.UserProfileServiceError) as exc_info:
        service.save_user_profile(
            "# User Profile\n\n## Profile Card\n\n- **Who**: Changed\n",
            mode="cloud",
            expected_exists=True,
            expected_revision="stale",
        )

    assert exc_info.value.status_code == 409
    assert [call[0] for call in calls] == ["GET"]


def test_update_uses_fastapi_intel_file_route_with_auto_ingest(monkeypatch):
    service = _load_service()
    current = "# User Profile\n\n## Profile Card\n\n- **Who**: Current\n"
    updated = "# User Profile\n\n## Profile Card\n\n- **Who**: Updated\n"
    responses = iter([
        _Response(200, _profile_payload(current)),
        _Response(200, {"ok": True}),
        _Response(200, _profile_payload(updated, ingested=False)),
    ])
    calls = []

    def fake_request(method, path, *, payload=None):
        calls.append((method, path, payload))
        return next(responses)

    monkeypatch.setattr(service, "_intel_request", fake_request)
    result = service.save_user_profile(
        updated,
        mode="local",
        expected_exists=True,
        expected_revision=service._content_revision(current),
    )

    assert calls[1] == (
        "PUT",
        "/api/intel/user-profile.md?mode=local",
        {"content": updated, "auto_ingest": True},
    )
    assert result["content"] == updated


def test_profile_card_is_required_before_any_write(monkeypatch):
    service = _load_service()
    monkeypatch.setattr(
        service,
        "_intel_request",
        lambda *args, **kwargs: pytest.fail("validation must happen before network access"),
    )

    with pytest.raises(service.UserProfileServiceError) as exc_info:
        service.save_user_profile(
            "# User Profile\n\n## Profile Reference\n\nLong notes only.\n",
            mode="cloud",
            expected_exists=False,
            expected_revision=None,
        )

    assert exc_info.value.status_code == 400
    assert "Profile Card" in str(exc_info.value)


def test_internal_failures_do_not_expose_endpoint_or_credentials(monkeypatch):
    service = _load_service()
    secret = "private-internal-api-key"
    endpoint = "http://jarvis-api.internal:8880"
    monkeypatch.setattr(service, "get_internal_api_base_url", lambda: endpoint)
    monkeypatch.setattr(service, "get_internal_api_headers", lambda: {"X-API-Key": secret})

    def fail_request(*args, **kwargs):
        raise requests.ConnectionError(f"failed {endpoint} with {secret}")

    monkeypatch.setattr(service.requests, "request", fail_request)
    with pytest.raises(service.UserProfileServiceError) as exc_info:
        service.get_user_profile()

    message = str(exc_info.value)
    assert exc_info.value.status_code == 503
    assert endpoint not in message
    assert secret not in message


def test_web_profile_ui_has_release_link_safe_preview_and_intel_deep_link():
    assert 'href="https://github.com/bigsk1/jarvis-voice/releases"' in CLIENT_HTML
    assert 'id="userProfileModal"' in CLIENT_HTML
    assert 'id="saveUserProfileBtn"' in CLIENT_HTML
    assert "Utils.parseMarkdown(Utils.escapeHtml" in CLIENT_JS
    assert "['href', 'title', 'target', 'rel'].includes" in CLIENT_JS
    assert "['http:', 'https:'].includes(parsed.protocol)" in CLIENT_JS
    assert "http://${hostname}:5002/#intel" in CLIENT_JS
    assert "window.location.hash.slice(1)" in MEMORY_JS
    assert "switchTab(requestedTab, { load: false })" in MEMORY_JS


def test_docker_services_share_canonical_intel_directory():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    intel_mount = "./jarvis-intel:/app/jarvis-intel"
    assert intel_mount in compose["x-jarvis-common"]["volumes"]
    assert intel_mount in compose["services"]["jarvis-web"]["volumes"]


def test_web_profile_bridge_returns_no_configured_secret_values(monkeypatch):
    service = _load_service()
    secret = "internal-api-secret"
    monkeypatch.setattr(service, "get_internal_api_base_url", lambda: "http://jarvis-api:8880")
    monkeypatch.setattr(service, "get_internal_api_headers", lambda: {"X-API-Key": secret})

    def fake_request(method, url, **kwargs):
        assert kwargs["headers"] == {"X-API-Key": secret}
        return _Response(200, _profile_payload("# User Profile\n\n## Profile Card\n\n- Hi\n"))

    monkeypatch.setattr(service.requests, "request", fake_request)
    result = service.get_user_profile()

    assert secret not in json.dumps(result)
    assert "jarvis-api" not in json.dumps(result)


def test_web_route_keeps_fixed_profile_contract_and_warms_ingest_modes():
    app = _load_web_app()
    saved = {
        "exists": True,
        "filename": "user-profile.md",
        "content": "# User Profile\n\n## Profile Card\n\n- Tester\n",
        "revision": "new-revision",
        "starter_template": None,
        "modified_at": "2026-08-13T00:00:00",
        "ingested": False,
        "fact_count": 0,
        "ingestion_started": True,
        "ingest_modes": ["local", "cloud"],
        "ingest_warning": None,
    }
    with (
        patch("server.app.is_auth_enabled", return_value=False),
        patch("server.routes.api.save_user_profile", return_value=saved) as save_mock,
        patch("config_loader.config_scope", side_effect=lambda mode: nullcontext()) as scope_mock,
        patch("user_profile.get_cached_profile_card") as cache_mock,
    ):
        with app.test_client() as client:
            response = client.put(
                "/api/user-profile",
                json={
                    "content": saved["content"],
                    "mode": "local",
                    "expected_exists": False,
                    "expected_revision": None,
                },
            )

    assert response.status_code == 200
    assert response.get_json()["profile"] == saved
    assert "local and cloud" in response.get_json()["message"]
    save_mock.assert_called_once_with(
        saved["content"],
        mode="local",
        expected_exists=False,
        expected_revision=None,
    )
    assert scope_mock.call_args_list == [call("local"), call("cloud")]
    assert cache_mock.call_args_list == [
        call(force_refresh=True),
        call(force_refresh=True),
    ]
