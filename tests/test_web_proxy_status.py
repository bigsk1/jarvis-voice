#!/usr/bin/env python3
"""Regression coverage for lazy, credential-safe proxy health status."""

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "jarvis-web"))
sys.path.insert(0, str(ROOT / "lib"))

for module_name in ("flask", "flask_socketio"):
    module = sys.modules.get(module_name)
    if module is not None and not getattr(module, "__file__", None):
        del sys.modules[module_name]
    importlib.import_module(module_name)

from server_package_utils import load_server_package  # noqa: E402

load_server_package(
    "jarvis_web_proxy_status_test_server",
    ROOT / "jarvis-web" / "server",
)

from jarvis_web_proxy_status_test_server import config as web_config  # noqa: E402
from jarvis_web_proxy_status_test_server.app import app  # noqa: E402
from jarvis_web_proxy_status_test_server.routes import api  # noqa: E402


class _Response:
    status_code = 200

    @staticmethod
    def json():
        return {
            "ip": "149.22.88.55",
            "city": "Seattle",
            "region": "Washington",
            "country_name": "United States",
        }


class _Session:
    def __init__(self):
        self.trust_env = True
        self.calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response()

    def close(self):
        self.closed = True


def _healthy_result(slot, endpoint, exit_ip):
    return {
        "slot": slot,
        "configured": True,
        "status": "healthy",
        "proxy_type": "HTTP",
        "endpoint": endpoint,
        "exit_ip": exit_ip,
        "location": "Seattle, Washington, United States",
        "latency_ms": 123,
        "detail": None,
    }


def test_proxy_display_metadata_redacts_credentials():
    secret = "proxy-password-that-must-not-leak"
    result = api._proxy_display_metadata(
        "LOCAL_PROXY",
        f"http://proxy-user:{secret}@192.168.60.186:8888",
    )

    assert result["proxy_type"] == "HTTP"
    assert result["endpoint"] == "192.168.60.186:8888"
    assert "proxy-user" not in json.dumps(result)
    assert secret not in json.dumps(result)


def test_probe_uses_one_explicit_proxy_without_environment_fallback():
    proxy_url = "http://user:secret@192.168.60.186:8888"
    session = _Session()
    with patch("requests.Session", return_value=session):
        result = api._probe_proxy("LOCAL_PROXY", proxy_url)

    assert session.trust_env is False
    assert session.closed is True
    assert session.calls == [(
        api._PROXY_STATUS_URL,
        {
            "proxies": {"http": proxy_url, "https": proxy_url},
            "timeout": (3, 8),
            "headers": {
                "Accept": "application/json",
                "User-Agent": "Jarvis-Proxy-Health/1.0",
            },
        },
    )]
    assert result["status"] == "healthy"
    assert result["exit_ip"] == "149.22.88.55"
    assert result["location"] == "Seattle, Washington, United States"
    assert "secret" not in json.dumps(result)


def test_probe_failure_does_not_return_proxy_url_or_exception_text():
    import requests

    secret = "failure-path-proxy-secret"
    proxy_url = f"http://user:{secret}@192.168.60.186:8888"
    session = _Session()
    with (
        patch("requests.Session", return_value=session),
        patch.object(
            session,
            "get",
            side_effect=requests.exceptions.ProxyError(
                f"failed via {proxy_url} with credentials"
            ),
        ),
    ):
        result = api._probe_proxy("LOCAL_PROXY", proxy_url)

    serialized = json.dumps(result)
    assert result["status"] == "unreachable"
    assert result["detail"] == "Proxy connection or authentication failed"
    assert secret not in serialized
    assert "user" not in serialized


def test_endpoint_is_mode_scoped_cached_refreshable_and_secret_free():
    cloud_secret = "cloud-proxy-password"
    local_secret = "local-proxy-password"
    mode_values = {
        "cloud": {
            "LOCAL_PROXY": f"http://user:{cloud_secret}@192.168.60.186:8888",
            "LOCAL_PROXY2": "",
        },
        "local": {
            "LOCAL_PROXY": "",
            "LOCAL_PROXY2": f"http://user:{local_secret}@192.168.60.187:8889",
        },
    }
    current_mode = {"value": "cloud"}

    def get_setting(key, default=""):
        return mode_values[current_mode["value"]].get(key, default)

    def probe(slot, proxy_url):
        endpoint = "192.168.60.186:8888" if slot == "LOCAL_PROXY" else "192.168.60.187:8889"
        exit_ip = "149.22.88.55" if slot == "LOCAL_PROXY" else "149.22.88.56"
        return _healthy_result(slot, endpoint, exit_ip)

    api._PROXY_STATUS_CACHE.clear()
    with (
        patch.object(web_config, "load_jarvis_config", return_value=True),
        patch.object(web_config, "get_jarvis_setting", side_effect=get_setting),
        patch.object(api, "_probe_proxy", side_effect=probe) as mock_probe,
    ):
        with app.test_request_context("/api/proxy/status?mode=cloud"):
            cloud_first = api.get_proxy_status.__wrapped__().get_json()
        with app.test_request_context("/api/proxy/status?mode=cloud"):
            cloud_cached = api.get_proxy_status.__wrapped__().get_json()
        with app.test_request_context("/api/proxy/status?mode=cloud&refresh=1"):
            cloud_refreshed = api.get_proxy_status.__wrapped__().get_json()

        current_mode["value"] = "local"
        with app.test_request_context("/api/proxy/status?mode=local"):
            local_first = api.get_proxy_status.__wrapped__().get_json()

    assert cloud_first["cached"] is False
    assert cloud_cached["cached"] is True
    assert cloud_refreshed["cached"] is False
    assert local_first["mode"] == "local"
    assert mock_probe.call_count == 3
    assert cloud_first["proxies"][0]["endpoint"] == "192.168.60.186:8888"
    assert cloud_first["proxies"][1]["status"] == "not_configured"
    assert local_first["proxies"][0]["status"] == "not_configured"
    assert local_first["proxies"][1]["endpoint"] == "192.168.60.187:8889"

    serialized = json.dumps({
        "cloud": cloud_first,
        "local": local_first,
    })
    assert cloud_secret not in serialized
    assert local_secret not in serialized
    assert "user" not in serialized


def test_proxy_status_ui_is_lazy_and_escapes_server_fields():
    app_js = (ROOT / "jarvis-web/client/js/app.js").read_text(encoding="utf-8")
    index_html = (ROOT / "jarvis-web/client/index.html").read_text(encoding="utf-8")
    setup_start = app_js.index("  _setupUIListeners() {")
    setup_end = app_js.index("\n  /**", setup_start)
    settings_start = app_js.index("async _loadSettings(")
    settings_end = app_js.index("\n  /**", settings_start)
    proxy_start = app_js.index("  async _loadProxyStatus(")
    proxy_end = app_js.index("\n  /**", proxy_start)

    assert "if (tabName === 'api')" in app_js[setup_start:setup_end]
    assert "this._loadProxyStatus();" in app_js[setup_start:setup_end]
    assert "settings-api')?.classList.contains('active')" in app_js[settings_start:settings_end]
    assert "/api/proxy/status?mode=" in app_js[proxy_start:proxy_end]
    assert "Utils.escapeHtml(description)" in app_js[proxy_start:proxy_end]
    assert "proxy.password" not in app_js[proxy_start:proxy_end]
    assert 'id="refreshProxyStatusBtn"' in index_html
    assert "Exit locations are approximate" in index_html
