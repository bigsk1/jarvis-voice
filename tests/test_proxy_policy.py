#!/usr/bin/env python3
"""Focused tests for Jarvis proxy-policy semantics."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import http_client


PROJECT_ROOT = Path(__file__).parent.parent.resolve()


def _config(monkeypatch, values):
    monkeypatch.setattr(
        http_client,
        "get_config_value",
        lambda key, default=None: values.get(key, default),
    )


def test_omitted_policy_preserves_legacy_request_options(monkeypatch):
    _config(monkeypatch, {})
    assert http_client.get_proxy_policy() == "inherit"
    assert http_client.resolve_proxy_behavior(
        use_proxy=False,
        fallback_on_proxy_fail=False,
    ) == (False, False)


def test_prefer_keeps_primary_secondary_direct_semantics(monkeypatch):
    _config(
        monkeypatch,
        {
            http_client.PROXY_POLICY_ENV: "prefer",
            "LOCAL_PROXY": "http://proxy-one.test:8001",
            "LOCAL_PROXY2": "http://proxy-two.test:8002",
        },
    )
    assert http_client.get_proxy_url_chain() == [
        "http://proxy-one.test:8001",
        "http://proxy-two.test:8002",
    ]
    assert http_client.resolve_proxy_behavior(
        use_proxy=False,
        fallback_on_proxy_fail=False,
    ) == (True, True)
    assert http_client.build_proxy_url_attempts(direct_fallback_default=False) == [
        "http://proxy-one.test:8001",
        "http://proxy-two.test:8002",
        None,
    ]


@pytest.mark.parametrize(
    "manifest_name",
    ["youtube_transcript.tool.json", "youtube_video.tool.json"],
)
def test_youtube_tools_prefer_proxies_with_direct_fallback(manifest_name):
    manifest_path = PROJECT_ROOT / "skills" / "auto-tools" / manifest_name
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["proxy_policy"] == "prefer"


def test_off_suppresses_jarvis_proxy_chain(monkeypatch):
    _config(
        monkeypatch,
        {
            http_client.PROXY_POLICY_ENV: "off",
            "LOCAL_PROXY": "http://proxy-one.test:8001",
            "LOCAL_PROXY2": "http://proxy-two.test:8002",
        },
    )
    assert http_client.get_proxy_chain() == []
    assert http_client.build_proxy_url_attempts(direct_fallback_default=False) == [None]


def test_require_never_calls_direct_after_proxy_failures(monkeypatch):
    _config(
        monkeypatch,
        {
            http_client.PROXY_POLICY_ENV: "require",
            "LOCAL_PROXY": "http://proxy-one.test:8001",
            "LOCAL_PROXY2": "http://proxy-two.test:8002",
        },
    )
    calls = []

    def fail_request(method, url, **kwargs):
        calls.append(kwargs.get("proxies"))
        raise requests.exceptions.ProxyError("proxy unavailable")

    monkeypatch.setattr(http_client.requests, "request", fail_request)

    with pytest.raises(requests.exceptions.ProxyError):
        http_client.http_request("GET", "https://example.test", timeout=1)

    assert calls == [
        {
            "http": "http://proxy-one.test:8001",
            "https": "http://proxy-one.test:8001",
        },
        {
            "http": "http://proxy-two.test:8002",
            "https": "http://proxy-two.test:8002",
        },
    ]


def test_require_without_config_fails_before_network(monkeypatch):
    _config(monkeypatch, {http_client.PROXY_POLICY_ENV: "require"})
    request = Mock()
    monkeypatch.setattr(http_client.requests, "request", request)

    with pytest.raises(requests.exceptions.ProxyError):
        http_client.http_request("GET", "https://example.test")

    request.assert_not_called()


def test_invalid_policy_is_rejected():
    with pytest.raises(ValueError):
        http_client.normalize_proxy_policy("sometimes")
