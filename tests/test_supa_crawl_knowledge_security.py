#!/usr/bin/env python3
"""Credential-to-origin boundaries for the Supa-Crawl knowledge tool."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills"))

import supa_crawl_knowledge  # noqa: E402


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"ok": True}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_configured_base_url_comes_only_from_operator_config(monkeypatch):
    requested = []

    def fake_get_config_value(name, default=None):
        requested.append(name)
        return "https://supa.internal.example/"

    monkeypatch.setattr(supa_crawl_knowledge, "get_config_value", fake_get_config_value)

    assert supa_crawl_knowledge.get_configured_base_url() == "https://supa.internal.example"
    assert requested == ["SUPA_CRAWL_CHAT_URL"]


def test_main_rejects_tool_supplied_base_url_before_request(monkeypatch, capsys):
    monkeypatch.setattr(supa_crawl_knowledge, "load_config", lambda: None)

    def unexpected_request(*_args, **_kwargs):
        raise AssertionError("network request should not run")

    monkeypatch.setattr(supa_crawl_knowledge, "request_json", unexpected_request)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "supa_crawl_knowledge.py",
            json.dumps(
                {
                    "action": "health",
                    "base_url": "https://attacker.example",
                }
            ),
        ],
    )

    assert supa_crawl_knowledge.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert "base_url cannot be provided as a tool argument" in result["error"]


def test_authenticated_request_uses_configured_origin_without_redirects(monkeypatch):
    calls = []

    def fake_get_config_value(name, default=None):
        return {
            "SUPA_CRAWL_CHAT_URL": "https://supa.internal.example",
            "SUPA_API_KEY": "configured-key",
            "SUPA_API_KEY_STYLE": "x-api-key",
        }.get(name, default)

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(payload={"status": "ok"})

    monkeypatch.setattr(supa_crawl_knowledge, "get_config_value", fake_get_config_value)
    monkeypatch.setattr(supa_crawl_knowledge.requests, "get", fake_get)

    result = supa_crawl_knowledge.request_json(
        "https://supa.internal.example",
        "/api/health",
    )

    assert result == {"status": "ok"}
    assert calls == [
        (
            "https://supa.internal.example/api/health",
            {
                "params": {},
                "headers": {"X-API-Key": "configured-key"},
                "timeout": 20,
                "allow_redirects": False,
            },
        )
    ]


def test_request_sink_rejects_nonconfigured_origin_before_credentials(monkeypatch):
    def fake_get_config_value(name, default=None):
        if name == "SUPA_CRAWL_CHAT_URL":
            return "https://supa.internal.example"
        raise AssertionError("credential lookup must not occur for another origin")

    def unexpected_get(*_args, **_kwargs):
        raise AssertionError("network request should not run")

    monkeypatch.setattr(supa_crawl_knowledge, "get_config_value", fake_get_config_value)
    monkeypatch.setattr(supa_crawl_knowledge.requests, "get", unexpected_get)

    with pytest.raises(ValueError, match="does not match SUPA_CRAWL_CHAT_URL"):
        supa_crawl_knowledge.request_json(
            "https://attacker.example",
            "/api/health",
        )


def test_authenticated_redirect_is_refused(monkeypatch):
    monkeypatch.setattr(
        supa_crawl_knowledge,
        "get_configured_base_url",
        lambda: "https://supa.internal.example",
    )
    monkeypatch.setattr(
        supa_crawl_knowledge,
        "supa_api_headers",
        lambda: {"Authorization": "Bearer configured-key"},
    )
    monkeypatch.setattr(
        supa_crawl_knowledge.requests,
        "get",
        lambda *_args, **_kwargs: FakeResponse(status_code=302),
    )

    with pytest.raises(RuntimeError, match="refused an HTTP redirect"):
        supa_crawl_knowledge.request_json(
            "https://supa.internal.example",
            "/api/health",
        )


def test_tool_manifest_does_not_expose_base_url():
    manifest = json.loads(
        (ROOT / "skills" / "supa_crawl_knowledge.tool.json").read_text()
    )

    assert "base_url" not in manifest["parameters"]["properties"]
