"""Webhook routing selects a route before sending one non-retriable POST."""

import importlib
import json
import os
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "lib"))
    module = importlib.import_module("webhook_transport")
    monkeypatch.setattr(module, "get_config_value", lambda key, default=None: os.environ.get(key, default))
    for key in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        monkeypatch.delenv(key, raising=False)
    return module


def test_missing_policy_is_direct_even_with_ambient_proxy_policy(transport, monkeypatch):
    monkeypatch.setenv("JARVIS_TOOL_PROXY_POLICY", "require")
    chain = Mock(side_effect=AssertionError("off must not inspect proxies"))
    monkeypatch.setattr(transport, "get_proxy_url_chain", chain)
    assert transport.policy_for_webhook({}) == "off"
    proxies, metadata = transport.prepare_webhook_route("off")
    assert proxies == {}
    assert metadata["policy"] == "off" and metadata["used"] is False
    assert metadata["basis"] == "webhook_route" and metadata["direct_reason"]
    chain.assert_not_called()


@pytest.mark.parametrize("policy", [None, "", " \t", "inherit", "unknown", True, 1, [], {}])
def test_explicit_invalid_policy_fails_closed(transport, policy):
    with pytest.raises(ValueError):
        transport.policy_for_webhook({"proxy_policy": policy})


@pytest.mark.parametrize("policy", ["off", "prefer", "require"])
def test_supported_registry_policies(transport, policy):
    assert transport.policy_for_webhook({"proxy_policy": policy}) == policy


@pytest.mark.parametrize("policy", [" OFF ", " Prefer\t", "\nREQUIRE "])
def test_registry_policies_normalize_whitespace_and_case(transport, monkeypatch, policy):
    normalized = policy.strip().lower()
    assert transport.policy_for_webhook({"proxy_policy": policy}) == normalized
    monkeypatch.setattr(transport, "get_proxy_url_chain", lambda **_kwargs: [])
    if normalized == "require":
        with pytest.raises(transport.WebhookProxyUnavailable):
            transport.prepare_webhook_route(policy)
    else:
        assert transport.prepare_webhook_route(policy)[1]["policy"] == normalized


def test_unreachable_primary_selects_secondary_before_post(transport, monkeypatch):
    http = importlib.import_module("http_client")
    primary = "http://primary-user:primary-secret@one.test:8001"
    secondary = "http://secondary-user:secondary-secret@two.test:8002"
    chain = Mock(return_value=[primary, secondary])
    monkeypatch.setattr(transport, "get_proxy_url_chain", chain)
    attempts = []

    def connect(address, **_kwargs):
        attempts.append(address)
        if address[0] == "one.test":
            raise OSError("synthetic listener down")
        return nullcontext()

    monkeypatch.setattr(http.socket, "create_connection", connect)
    proxies, metadata = transport.prepare_webhook_route("prefer")
    assert attempts == [("one.test", 8001), ("two.test", 8002)]
    assert proxies == {"http": secondary, "https": secondary}
    assert metadata["policy"] == "prefer" and metadata["used"] is True
    assert metadata["slot"] == "LOCAL_PROXY2"
    assert "secret" not in json.dumps(metadata) and "two.test" not in json.dumps(metadata)
    chain.assert_called_once_with(respect_policy=False)


@pytest.mark.parametrize("policy", ["prefer", "require"])
def test_secondary_only_configuration_keeps_real_proxy_slot(transport, monkeypatch, policy):
    http = importlib.import_module("http_client")
    secondary = "http://secondary-user:SECONDARY_SECRET@secondary.test:8002"
    config = {"LOCAL_PROXY": "", "LOCAL_PROXY2": secondary, "JARVIS_TOOL_PROXY_POLICY": "off"}

    def selected_config(key, default=None):
        return config.get(key, default)

    monkeypatch.setattr(http, "get_config_value", selected_config)
    monkeypatch.setattr(transport, "get_config_value", selected_config)
    connect = Mock(return_value=nullcontext())
    monkeypatch.setattr(http.socket, "create_connection", connect)
    proxies, metadata = transport.prepare_webhook_route(policy)
    connect.assert_called_once_with(("secondary.test", 8002), timeout=0.75)
    assert proxies == {"http": secondary, "https": secondary}
    assert metadata["used"] is True and metadata["slot"] == "LOCAL_PROXY2"
    assert "SECONDARY_SECRET" not in json.dumps(metadata)


@pytest.mark.parametrize("policy", ["prefer", "require"])
@pytest.mark.parametrize("primary", [
    "http://private-user:PRIMARY_SECRET@broken.test:not-a-port",
    "http://private-user:PRIMARY_SECRET@[broken",
    "unsupported://private-user:PRIMARY_SECRET@broken.test:8001",
])
def test_malformed_primary_does_not_hide_healthy_secondary(transport, monkeypatch, policy, primary):
    http = importlib.import_module("http_client")
    secondary = "http://secondary-user:SECONDARY_SECRET@secondary.test:8002"
    config = {"LOCAL_PROXY": primary, "LOCAL_PROXY2": secondary}

    def selected_config(key, default=None):
        return config.get(key, default)

    monkeypatch.setattr(http, "get_config_value", selected_config)
    monkeypatch.setattr(transport, "get_config_value", selected_config)
    connect = Mock(return_value=nullcontext())
    monkeypatch.setattr(http.socket, "create_connection", connect)
    proxies, metadata = transport.prepare_webhook_route(policy)
    connect.assert_called_once_with(("secondary.test", 8002), timeout=0.75)
    assert proxies == {"http": secondary, "https": secondary}
    assert metadata["used"] is True and metadata["slot"] == "LOCAL_PROXY2"
    for private in ("PRIMARY_SECRET", "SECONDARY_SECRET", "private-user", "broken.test"):
        assert private not in json.dumps(metadata)


@pytest.mark.parametrize("policy", ["prefer", "require"])
@pytest.mark.parametrize("chain", [[], ["http://unreachable.test:8001"]])
def test_no_reachable_proxy_allows_only_prefer_direct(transport, monkeypatch, policy, chain):
    monkeypatch.setattr(transport, "get_proxy_url_chain", lambda **_kwargs: chain)
    monkeypatch.setattr(transport, "select_reachable_proxy_url", lambda *_args, **_kwargs: None)
    if policy == "require":
        with pytest.raises(transport.WebhookProxyUnavailable):
            transport.prepare_webhook_route(policy)
    else:
        proxies, metadata = transport.prepare_webhook_route(policy)
        assert proxies == {} and metadata["used"] is False
        assert metadata["direct_reason"] and "slot" not in metadata


@pytest.mark.parametrize("policy", ["prefer", "require"])
def test_all_malformed_proxy_urls_follow_policy_without_leaking_configuration(transport, monkeypatch, policy):
    monkeypatch.setattr(transport, "get_proxy_url_chain", lambda **_kwargs: [
        "http://private-user:PROXY_SECRET@private-proxy.test:bad",
        "unsupported://secondary-user:SECONDARY_SECRET@other-private.test:8002",
    ])
    connect = Mock(side_effect=AssertionError("Malformed routes must not connect"))
    monkeypatch.setattr(transport, "select_reachable_proxy_url", connect)
    if policy == "require":
        with pytest.raises(transport.WebhookProxyUnavailable) as captured:
            transport.prepare_webhook_route(policy)
        output = str(captured.value)
        assert "no webhook was sent" in output
    else:
        proxies, metadata = transport.prepare_webhook_route(policy)
        assert proxies == {} and metadata["used"] is False
        output = json.dumps(metadata)
    for private in ("PROXY_SECRET", "private-proxy", "SECONDARY_SECRET", "other-private"):
        assert private not in output
    connect.assert_not_called()


@pytest.mark.parametrize("proxied", [False, True])
@pytest.mark.parametrize("status", [200, 204, 299, 300, 307, 399, 400, 401, 407, 429, 500, 502, 503, 504])
def test_response_receipt_preserves_proxy_delivery_uncertainty(transport, proxied, status):
    proxy = {"policy": "require" if proxied else "off", "used": proxied, "basis": "webhook_route"}
    before = dict(proxy)
    result = transport.webhook_response_receipt(status, proxy)
    assert result["response_received"] is True and result["status_code"] == status
    assert result["proxy"] == before and proxy == before
    if 200 <= status < 300:
        assert result["request_sent"] is True and result["delivery_status"] == "accepted"
        assert "retry_safe" not in result
    else:
        assert result["retry_safe"] is False
        if 300 <= status < 400:
            assert result["request_sent"] is (None if proxied else True)
            assert result["delivery_status"] == "redirect_refused" and result["redirect_blocked"] is True
        elif proxied and status == 407:
            assert result["request_sent"] is False and result["delivery_status"] == "proxy_rejected"
        elif proxied:
            assert result["request_sent"] is None and result["delivery_status"] == "unknown"
        else:
            assert result["request_sent"] is True and result["delivery_status"] == "rejected"


@pytest.fixture
def adapter_calls(monkeypatch):
    calls = []

    def send(adapter, prepared, **kwargs):
        calls.append((adapter, prepared, kwargs))
        response = requests.Response()
        response.status_code = 204
        response._content = b""
        response.request = prepared
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    return calls


@pytest.mark.parametrize("proxies", [{}, {"http": "http://selected.test:8001", "https": "http://selected.test:8001"}])
@pytest.mark.parametrize("scheme", ["http", "https"])
def test_real_session_ignores_environment_proxies_and_no_proxy(transport, monkeypatch, adapter_calls, proxies, scheme):
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(key, "http://ambient.test:9999")
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("no_proxy", "*")
    body = {"event": "create", "nested": [1, True]}
    url = f"{scheme}://destination.test/hook"
    response = transport.post_webhook(url, data=body,
                                      headers={"Authorization": "Bearer registry-only"}, proxies=proxies)
    assert response.status_code == 204 and len(adapter_calls) == 1
    adapter, prepared, kwargs = adapter_calls[0]
    assert prepared.method == "POST" and prepared.url == url
    assert json.loads(prepared.body) == body
    assert prepared.headers["Authorization"] == "Bearer registry-only"
    assert kwargs["proxies"] == proxies and kwargs["timeout"] == 15
    assert adapter.max_retries.total == 0


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]", "192.168.1.20"])
def test_explicit_required_route_is_preserved_for_private_destinations(transport, monkeypatch, adapter_calls, host):
    proxy_url = "http://explicit-proxy.test:8001"
    monkeypatch.setattr(transport, "get_proxy_url_chain", lambda **_kwargs: [proxy_url])
    monkeypatch.setattr(transport, "select_reachable_proxy_url", lambda _urls: (proxy_url, "LOCAL_PROXY"))
    monkeypatch.setenv("NO_PROXY", "*")
    proxies, metadata = transport.prepare_webhook_route("require")
    transport.post_webhook(f"http://{host}/hook", data={}, headers={}, proxies=proxies)
    assert metadata["used"] is True and metadata["policy"] == "require"
    assert len(adapter_calls) == 1 and adapter_calls[0][2]["proxies"] == proxies


@pytest.mark.parametrize("status", [301, 307, 407, 429, 500, 502, 503, 504])
def test_http_response_never_sends_second_post_or_follows_redirect(transport, monkeypatch, status):
    calls = []

    def send(_adapter, prepared, **kwargs):
        calls.append((prepared, kwargs))
        response = requests.Response()
        response.status_code = status
        response.headers["Location"] = "https://another.test/replay"
        response._content = b"upstream response"
        response.request = prepared
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    response = transport.post_webhook("https://destination.test/hook", data={}, headers={},
                                      proxies={"https": "http://selected.test:8001"})
    assert response.status_code == status and len(calls) == 1


@pytest.mark.parametrize("failure", [requests.ReadTimeout, requests.ConnectTimeout, requests.ConnectionError, requests.exceptions.ProxyError])
def test_ambiguous_exception_never_replays_post(transport, monkeypatch, failure):
    send = Mock(side_effect=failure("synthetic transport failure"))
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    with pytest.raises(failure):
        transport.post_webhook("https://destination.test/hook", data={}, headers={},
                               proxies={"https": "http://selected.test:8001"})
    assert send.call_count == 1


@pytest.mark.parametrize("key", ["REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"])
def test_explicit_ca_bundle_survives_disabling_ambient_proxy_handling(transport, monkeypatch, adapter_calls, key):
    monkeypatch.setenv(key, "/synthetic/trusted-ca.pem")
    transport.post_webhook("https://destination.test/hook", data={}, headers={}, proxies={})
    assert adapter_calls[0][2]["verify"] == "/synthetic/trusted-ca.pem"


def test_selected_mode_ca_bundle_is_preserved(transport, monkeypatch, adapter_calls):
    monkeypatch.setattr(transport, "get_config_value", lambda key, default=None:
                        "/selected-mode/ca.pem" if key == "REQUESTS_CA_BUNDLE" else default)
    transport.post_webhook("https://destination.test/hook", data={}, headers={}, proxies={})
    assert adapter_calls[0][2]["verify"] == "/selected-mode/ca.pem"


def test_other_mode_ca_is_omitted_before_selected_curl_bundle(transport, monkeypatch, tmp_path, adapter_calls):
    config = importlib.import_module("config_loader")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cloud.env").write_text("REQUESTS_CA_BUNDLE=/cloud-only/ca.pem\n")
    (config_dir / "local.env").write_text("CURL_CA_BUNDLE=/local-selected/ca.pem\n")
    monkeypatch.setattr(config, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(transport, "get_config_value", config.get_config_value)
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/cloud-only/ca.pem")
    for key in ("JARVIS_OVERRIDE_REQUESTS_CA_BUNDLE", "JARVIS_OVERRIDE_CURL_CA_BUNDLE"):
        monkeypatch.delenv(key, raising=False)
    with config.config_scope("local"):
        assert config.get_config_value("REQUESTS_CA_BUNDLE") is None
        transport.post_webhook("https://destination.test/hook", data={}, headers={}, proxies={})
    assert adapter_calls[0][2]["verify"] == "/local-selected/ca.pem"
