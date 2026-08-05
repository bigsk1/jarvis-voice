#!/usr/bin/env python3
"""Regression coverage for lazy, sanitized SerpApi quota UI."""

import importlib
import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import requests


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "jarvis-web"))
sys.path.insert(0, str(ROOT / "lib"))

# Some lightweight tests install collection-time Flask stubs. This module uses
# the real Web app, so restore installed packages before loading it.
for module_name in ("flask", "flask_socketio"):
    module = sys.modules.get(module_name)
    if module is not None and not getattr(module, "__file__", None):
        del sys.modules[module_name]
    importlib.import_module(module_name)

from server_package_utils import load_server_package  # noqa: E402

load_server_package(
    "jarvis_web_serpapi_account_test_server",
    ROOT / "jarvis-web" / "server",
)

from jarvis_web_serpapi_account_test_server import config as web_config  # noqa: E402
from jarvis_web_serpapi_account_test_server.app import app  # noqa: E402
from jarvis_web_serpapi_account_test_server.routes import api  # noqa: E402


class _Response:
    def __init__(self, status_code=200, payload=None, json_error=False):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("invalid json")
        return self._payload


def _call_account(key, response=None, request_error=None):
    with app.test_request_context("/api/serpapi/account?mode=cloud"):
        with (
            patch.object(web_config, "get_jarvis_setting", return_value=key),
            patch(
                "requests.get",
                return_value=response,
                side_effect=request_error,
            ) as mock_get,
        ):
            body = api.get_serpapi_account.__wrapped__().get_json()
    return body, mock_get


def test_missing_or_placeholder_key_skips_outbound_request():
    for key in ("", "short", "YOUR_SERP_API_KEY", "replace-this-example-key"):
        body, mock_get = _call_account(key)
        assert body == {
            "ok": False,
            "provider": "serpapi",
            "configured": bool(key),
            "valid": False,
        }
        mock_get.assert_not_called()


def test_valid_account_returns_only_sanitized_quota_fields():
    secret = "private-serpapi-key"
    body, mock_get = _call_account(secret, _Response(payload={
        "account_id": "private-account-id",
        "api_key": secret,
        "account_email": "private@example.com",
        "account_status": "Active",
        "plan_id": "bigdata",
        "plan_name": "Big Data Plan",
        "plan_renewal_date": "2026-09-05",
        "searches_per_month": 30_000,
        "plan_searches_left": 5_000,
        "extra_credits": 958,
        "this_month_usage": 24_042,
        "this_hour_searches": 87,
        "account_rate_limit_per_hour": 6_000,
    }))

    mock_get.assert_called_once_with(
        "https://serpapi.com/account.json",
        params={"api_key": secret},
        timeout=10,
    )
    assert body["ok"] is True
    assert body["configured"] is True
    assert body["valid"] is True
    assert body["account"] == {
        "status": "Active",
        "plan_name": "Big Data Plan",
        "renewal_date": "2026-09-05",
    }
    assert body["quota"] == {
        "monthly_used": 24_042,
        "monthly_limit": 30_000,
        "monthly_remaining": 5_958,
        "percentage_used": 80.1,
        "extra_credits": 958,
        "this_hour_searches": 87,
        "hourly_limit": 6_000,
    }
    serialized = json.dumps(body)
    assert secret not in serialized
    assert "private-account-id" not in serialized
    assert "private@example.com" not in serialized


def test_invalid_or_unreadable_account_stays_unavailable_and_sanitized():
    secret = "invalid-private-key"
    for response in (
        _Response(status_code=401, payload={"error": secret}),
        _Response(payload={"api_key": secret}),
        _Response(json_error=True),
    ):
        body, _ = _call_account(secret, response)
        assert body["ok"] is False
        assert body["configured"] is True
        assert body["valid"] is False
        assert secret not in json.dumps(body)


def test_timeout_is_sanitized():
    body, _ = _call_account(
        "private-serpapi-key",
        request_error=requests.exceptions.Timeout("contains private details"),
    )
    assert body["reason"] == "timeout"
    assert "private details" not in json.dumps(body)


def test_decorated_route_reads_the_requested_mode_scope():
    import config_loader

    active_mode = {"value": None}

    @contextmanager
    def fake_scope(mode, overrides=None):
        active_mode["value"] = mode
        try:
            yield
        finally:
            active_mode["value"] = None

    def get_setting(key, default=""):
        if key == "SERP_API_KEY":
            return f"{active_mode['value']}-private-key"
        return default

    response = _Response(payload={"account_status": "Active"})
    with (
        app.test_request_context("/api/serpapi/account?mode=local"),
        patch.object(api, "_apply_tts_provider_override", return_value=None),
        patch.object(config_loader, "config_scope", side_effect=fake_scope),
        patch.object(web_config, "get_jarvis_setting", side_effect=get_setting),
        patch("requests.get", return_value=response) as mock_get,
    ):
        body = api.get_serpapi_account().get_json()

    assert body["valid"] is True
    assert mock_get.call_args.kwargs["params"] == {"api_key": "local-private-key"}


def test_browser_quota_loader_is_system_tab_only_and_hides_failed_accounts():
    app_js = (ROOT / "jarvis-web/client/js/app.js").read_text()
    index_html = (ROOT / "jarvis-web/client/index.html").read_text()
    setup_start = app_js.index("  _setupUIListeners() {")
    setup_end = app_js.index("\n  /**", setup_start)
    settings_start = app_js.index("async _loadSettings(")
    settings_end = app_js.index("\n  /**", settings_start)

    assert "if (tabName === 'system')" in app_js[setup_start:setup_end]
    assert "this._loadSerpApiAccount();" in app_js[setup_start:setup_end]
    assert "_loadSerpApiAccount" not in app_js[settings_start:settings_end]
    assert 'id="serpapi-account-section" hidden' in index_html
    assert "Never retain quota from a previously selected mode" in app_js
    assert "requestId !== this._serpApiAccountRequestId" in app_js

    script = r"""
const fs = require('fs');
const source = fs.readFileSync('jarvis-web/client/js/app.js', 'utf8')
  .split('// Initialize app when DOM is ready')[0];
const section = {hidden: true, innerHTML: ''};
global.document = {getElementById: id => id === 'serpapi-account-section' ? section : null};
global.Utils = {escapeHtml: value => String(value).replaceAll('<', '&lt;').replaceAll('>', '&gt;')};
let requestedUrl = null;
let payload = {
  ok: true,
  configured: true,
  valid: true,
  account: {status: 'Active', plan_name: '<img src=x>', renewal_date: '2026-09-05'},
  quota: {
    monthly_used: 750,
    monthly_limit: 1000,
    monthly_remaining: 250,
    percentage_used: 75,
    this_hour_searches: 2,
    hourly_limit: 100
  }
};
global.fetch = async url => {
  requestedUrl = url;
  return {json: async () => payload};
};
eval(source + '\nglobal.JarvisApp = JarvisApp;');

(async () => {
  const instance = Object.create(global.JarvisApp.prototype);
  instance._settingsData = {mode: 'local'};
  instance.socket = {mode: 'cloud'};
  instance._serpApiAccountRequestId = 0;
  await instance._loadSerpApiAccount();
  if (requestedUrl !== '/api/serpapi/account?mode=local') throw new Error(requestedUrl);
  if (section.hidden) throw new Error('valid account stayed hidden');
  if (!section.innerHTML.includes('750 / 1,000') || !section.innerHTML.includes('75%')) {
    throw new Error(section.innerHTML);
  }
  if (section.innerHTML.includes('<img')) throw new Error('account metadata was not escaped');

  payload = {ok: false, configured: false, valid: false};
  await instance._loadSerpApiAccount();
  if (!section.hidden || section.innerHTML !== '') throw new Error('invalid account remained visible');
})().catch(error => {
  console.error(error);
  process.exit(1);
});
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)
