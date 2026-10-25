"""Named payload discovery and validation must not consume outbound cooldowns."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills"))
import send_webhook  # noqa: E402


@pytest.fixture
def webhook_runtime(monkeypatch, tmp_path):
    registry = {
        "sample_notification": {
            "url": "https://example.test/webhook",
            "description": "Create a sample notification",
            "headers": {"Authorization": "Bearer private-registry-value"},
            "required_fields": ["action", "notification"],
            "payload_schema": {
                "type": "object",
                "properties": {
                    "action": {"enum": ["create"]},
                    "notification": {
                        "type": "object",
                        "required": ["message", "scheduled_at"],
                        "properties": {
                            "message": {"type": "string"},
                            "scheduled_at": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})$"},
                        },
                    },
                },
                "required": ["action", "notification"],
            },
            "example": {"action": "create", "notification": {
                "message": "Sample notification", "scheduled_at": "2030-01-01T12:00:00Z"}},
            "rate_limit_seconds": 5,
        },
        "disabled": {"url": "https://example.test/disabled", "enabled": False},
    }
    calls = []
    limit_file = tmp_path / "rate_limit.json"
    monkeypatch.setattr(send_webhook, "RATE_LIMIT_FILE", str(limit_file))
    monkeypatch.setattr(send_webhook, "load_config", lambda: None)
    monkeypatch.setattr(send_webhook, "load_webhook_registry", lambda: registry)

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return type("Response", (), {"status_code": 204, "text": ""})()

    monkeypatch.setattr(send_webhook, "post_webhook", post)
    return registry, calls, limit_file


def invoke(monkeypatch, capsys, payload):
    monkeypatch.setattr(sys, "argv", ["send_webhook.py", json.dumps(payload)])
    status = send_webhook.main()
    return status, json.loads(capsys.readouterr().out)


def test_listing_exposes_contract_without_credentials_or_cooldown(webhook_runtime, monkeypatch, capsys):
    registry, calls, limit_file = webhook_runtime
    status, result = invoke(monkeypatch, capsys, {"webhook": "list", "data": {}})
    assert status == 0
    assert result["data"]["request_sent"] is False
    items = result["data"]["webhooks"]
    assert len(items) == 1
    item = items[0]
    assert item["required_fields"] == ["action", "notification"]
    assert item["payload_schema"] == registry["sample_notification"]["payload_schema"]
    assert item["example"] == registry["sample_notification"]["example"]
    assert "url" not in item and "headers" not in item
    assert "private-registry-value" not in json.dumps(result)
    assert not calls and not limit_file.exists()


def test_missing_fields_then_corrected_call_sends_immediately(webhook_runtime, monkeypatch, capsys):
    registry, calls, limit_file = webhook_runtime
    status, result = invoke(monkeypatch, capsys, {"webhook": "sample_notification", "data": {"message": "test"}})
    assert status == 1
    assert result["data"]["missing_fields"] == ["action", "notification"]
    assert result["data"]["request_sent"] is False
    assert "No webhook was sent." in result["error"]
    assert not calls and not limit_file.exists()
    body = registry["sample_notification"]["example"]
    status, result = invoke(monkeypatch, capsys, {"webhook": "sample_notification", "data": body})
    assert status == 0
    assert len(calls) == 1 and calls[0][1]["data"] == body
    assert limit_file.exists()


@pytest.mark.parametrize("body,path", [
    ({"action": "test", "notification": {}}, "action"),
    ({"action": "create", "notification": {"message": "Sample"}}, "notification"),
    ({"action": "create", "notification": {"message": "Sample", "scheduled_at": "tomorrow"}}, "notification.scheduled_at"),
])
def test_schema_errors_precede_cooldown_and_network(webhook_runtime, monkeypatch, capsys, body, path):
    _, calls, limit_file = webhook_runtime
    status, result = invoke(monkeypatch, capsys, {"webhook": "sample_notification", "data": body})
    assert status == 1
    assert result["data"]["validation_path"] == path
    assert result["data"]["request_sent"] is False
    assert not calls and not limit_file.exists()


def test_schema_is_optional_and_arbitrary_payload_stays_unchanged(webhook_runtime, monkeypatch, capsys):
    registry, calls, _ = webhook_runtime
    registry["sample_notification"].pop("payload_schema")
    registry["sample_notification"]["required_fields"] = []
    body = {"arbitrary": [1, "sample", {"nested": True}], "action": "anything"}
    assert invoke(monkeypatch, capsys, {"webhook": "sample_notification", "data": body})[0] == 0
    assert calls[0][1]["data"] == body


@pytest.mark.parametrize("schema", [{"type": "invalid-type"}, "invalid-schema", None])
def test_invalid_registry_schema_does_not_reserve_attempt(webhook_runtime, monkeypatch, capsys, schema):
    registry, calls, limit_file = webhook_runtime
    registry["sample_notification"]["payload_schema"] = schema
    status, result = invoke(monkeypatch, capsys, {"webhook": "sample_notification", "data": registry["sample_notification"]["example"]})
    assert status == 1 and "registry" in result["error"]
    assert not calls and not limit_file.exists()


def test_fractional_cooldown_never_reports_zero(webhook_runtime, monkeypatch, capsys):
    registry, calls, _ = webhook_runtime
    clock = iter([100.0, 104.75])
    monkeypatch.setattr(send_webhook.time, "time", lambda: next(clock))
    payload = {"webhook": "sample_notification", "data": registry["sample_notification"]["example"]}
    assert invoke(monkeypatch, capsys, payload)[0] == 0
    status, result = invoke(monkeypatch, capsys, payload)
    assert status == 1
    assert result["data"]["retry_after_seconds"] == 1
    assert "wait 1 second" in result["error"]
    assert len(calls) == 1


def test_rate_limited_call_does_not_probe_proxy_listener(webhook_runtime, monkeypatch, capsys):
    registry, calls, limit_file = webhook_runtime
    registry['sample_notification']['proxy_policy'] = 'require'
    route_calls = []

    def route(policy):
        route_calls.append(policy)
        return {'https': 'http://proxy.test:8080'}, {'policy': policy, 'used': True, 'slot': 'LOCAL_PROXY'}

    monkeypatch.setattr(send_webhook, 'prepare_webhook_route', route)
    clock = [100.0]
    monkeypatch.setattr(send_webhook.time, 'time', lambda: clock[0])
    payload = {'webhook': 'sample_notification', 'data': registry['sample_notification']['example']}
    assert invoke(monkeypatch, capsys, payload)[0] == 0
    reservation = limit_file.read_text()
    clock[0] = 104.75
    status, result = invoke(monkeypatch, capsys, payload)
    assert status == 1 and result['data']['request_sent'] is False
    assert result['data']['retry_after_seconds'] == 1
    assert len(calls) == 1 and route_calls == ['require']
    assert limit_file.read_text() == reservation


@pytest.mark.parametrize('status_code,delivery_status,request_sent', [
    (407, 'proxy_rejected', False),
    (400, 'unknown', None),
    (502, 'unknown', None),
    (503, 'unknown', None),
    (504, 'unknown', None),
])
def test_proxy_http_failure_never_claims_destination_rejection(
    webhook_runtime, monkeypatch, capsys, status_code, delivery_status, request_sent,
):
    registry, _, _ = webhook_runtime
    registry['sample_notification']['proxy_policy'] = 'prefer'
    proxy = {'policy': 'prefer', 'used': True, 'slot': 'LOCAL_PROXY', 'basis': 'webhook_route'}
    monkeypatch.setattr(send_webhook, 'prepare_webhook_route', lambda _policy: (
        {'https': 'http://proxy.test:8080'}, proxy,
    ))
    attempts = []

    def post(url, **kwargs):
        attempts.append((url, kwargs))
        return type('Response', (), {'status_code': status_code, 'text': 'upstream error'})()

    monkeypatch.setattr(send_webhook, 'post_webhook', post)
    payload = {'webhook': 'sample_notification', 'data': registry['sample_notification']['example']}
    status, result = invoke(monkeypatch, capsys, payload)
    assert status == 1
    assert result['data']['request_sent'] is request_sent
    assert result['data']['delivery_status'] == delivery_status
    assert result['data']['proxy'] == proxy
    assert result['data']['response_received'] is True and result['data']['retry_safe'] is False
    assert 'Proxy authentication' in result['speech'] if status_code == 407 else 'unknown' in result['speech']
    assert invoke(monkeypatch, capsys, payload)[0] == 1
    assert len(attempts) == 1


@pytest.mark.parametrize("field,value", [("data", []), ("headers", [])])
def test_non_object_arguments_fail_before_cooldown(webhook_runtime, monkeypatch, capsys, field, value):
    registry, calls, limit_file = webhook_runtime
    payload = {"webhook": "sample_notification", "data": registry["sample_notification"]["example"], field: value}
    assert invoke(monkeypatch, capsys, payload)[0] == 1
    assert not calls and not limit_file.exists()


def test_describe_returns_complete_single_contract_without_sending(webhook_runtime, monkeypatch, capsys):
    registry, calls, limit_file = webhook_runtime
    registry['sample_notification']['optional_fields'] = ['callback']
    registry['sample_notification']['notes'] = 'Independent notification service.'
    status, result = invoke(monkeypatch, capsys, {'webhook': 'sample_notification', 'describe': True, 'data': {}})
    assert status == 0 and result['data']['request_sent'] is False
    for field in ('payload_schema', 'example', 'optional_fields', 'notes'):
        assert result['data'][field] == registry['sample_notification'][field]
    assert not calls and not limit_file.exists()


def test_timeout_records_unknown_delivery_and_consumes_cooldown(webhook_runtime, monkeypatch, capsys):
    registry, _, limit_file = webhook_runtime
    calls = []

    def timeout(*args, **kwargs):
        calls.append((args, kwargs))
        raise send_webhook.requests.Timeout()

    monkeypatch.setattr(send_webhook, 'post_webhook', timeout)
    body = {'webhook': 'sample_notification', 'data': registry['sample_notification']['example']}
    status, result = invoke(monkeypatch, capsys, body)
    assert status == 1
    assert result['data']['request_sent'] is None
    assert result['data']['retry_safe'] is False
    assert result['data']['delivery_status'] == 'unknown'
    assert limit_file.exists()
    assert invoke(monkeypatch, capsys, body)[0] == 1
    assert len(calls) == 1


def test_http_acceptance_is_a_delivery_receipt(webhook_runtime, monkeypatch, capsys):
    registry, _, _ = webhook_runtime
    status, result = invoke(monkeypatch, capsys, {'webhook': 'sample_notification', 'data': registry['sample_notification']['example']})
    assert status == 0
    assert result['data']['request_sent'] is True
    assert result['data']['response_received'] is True
    assert result['data']['delivery_status'] == 'accepted'
    assert "does not verify the automation" in result['speech']


@pytest.mark.parametrize("policy", [None, "", "inherit", "invalid", True, 5])
def test_invalid_destination_policy_does_not_reserve_attempt(webhook_runtime, monkeypatch, capsys, policy):
    registry, calls, limit_file = webhook_runtime
    registry["sample_notification"]["proxy_policy"] = policy
    status, result = invoke(monkeypatch, capsys, {
        "webhook": "sample_notification", "data": registry["sample_notification"]["example"],
    })
    assert status == 1 and result["data"]["request_sent"] is False
    assert not calls and not limit_file.exists()


def test_required_proxy_unavailable_does_not_reserve_attempt(webhook_runtime, monkeypatch, capsys):
    from webhook_transport import WebhookProxyUnavailable

    registry, calls, limit_file = webhook_runtime
    registry["sample_notification"]["proxy_policy"] = "require"

    def unavailable(policy):
        assert policy == "require"
        raise WebhookProxyUnavailable("No configured proxy is reachable")

    monkeypatch.setattr(send_webhook, "prepare_webhook_route", unavailable)
    status, result = invoke(monkeypatch, capsys, {
        "webhook": "sample_notification", "data": registry["sample_notification"]["example"],
    })
    assert status == 1 and result["data"]["request_sent"] is False
    assert not calls and not limit_file.exists()


@pytest.mark.parametrize("registry_policy", [None, "require"])
def test_tool_arguments_cannot_override_registry_routing(webhook_runtime, monkeypatch, capsys, registry_policy):
    registry, calls, _ = webhook_runtime
    if registry_policy is not None:
        registry["sample_notification"]["proxy_policy"] = registry_policy
    selected = []
    proxies = {"http": "http://selected.test:8001", "https": "http://selected.test:8001"}

    def route(policy):
        selected.append(policy)
        return (proxies if policy == "require" else {}), {"policy": policy, "used": policy != "off", "basis": "webhook_route"}

    monkeypatch.setattr(send_webhook, "prepare_webhook_route", route)
    status, _ = invoke(monkeypatch, capsys, {
        "webhook": "sample_notification", "data": registry["sample_notification"]["example"],
        "proxy_policy": "prefer", "proxies": {"https": "http://caller-selected.test:9999"},
    })
    assert status == 0
    assert selected == [registry_policy or "off"]
    assert calls[0][1]["proxies"] == (proxies if registry_policy == "require" else {})


def test_direct_url_remains_direct_despite_caller_policy(webhook_runtime, monkeypatch, capsys):
    import stash_helper

    _, calls, _ = webhook_runtime
    monkeypatch.setattr(stash_helper, "validate_url", lambda url: url)
    selected = []

    def route(policy):
        selected.append(policy)
        return {}, {"policy": policy, "used": False, "basis": "webhook_route"}

    monkeypatch.setattr(send_webhook, "prepare_webhook_route", route)
    status, _ = invoke(monkeypatch, capsys, {
        "url": "https://public.example/hook", "data": {}, "proxy_policy": "require",
    })
    assert status == 0 and selected == ["off"]
    assert calls[0][1]["proxies"] == {}


@pytest.mark.parametrize("action", ["invalid_payload", "list", "describe"])
def test_local_validation_and_inspection_never_probe_proxy(webhook_runtime, monkeypatch, capsys, action):
    registry, calls, limit_file = webhook_runtime
    registry["sample_notification"]["proxy_policy"] = "require"

    def unexpected_route(_policy):
        raise AssertionError("Local-only operation must not probe proxy listeners")

    monkeypatch.setattr(send_webhook, "prepare_webhook_route", unexpected_route)
    payload = {"webhook": "sample_notification", "data": {}}
    if action == "list":
        payload["webhook"] = "list"
    elif action == "describe":
        payload["describe"] = True
    status, result = invoke(monkeypatch, capsys, payload)
    assert status == (1 if action == "invalid_payload" else 0)
    assert result["data"]["request_sent"] is False
    assert not calls and not limit_file.exists()


def test_proxy_exception_never_echoes_credentials_or_retries(webhook_runtime, monkeypatch, capsys):
    registry, _, limit_file = webhook_runtime
    registry["sample_notification"]["proxy_policy"] = "require"
    metadata = {"policy": "require", "used": True, "basis": "webhook_route", "slot": "LOCAL_PROXY"}
    proxy = "http://private-user:WEBHOOK_PROXY_SECRET@proxy-private.test:8001"
    monkeypatch.setattr(send_webhook, "prepare_webhook_route", lambda _policy: (
        {"http": proxy, "https": proxy}, metadata,
    ))
    attempts = []

    def fail(url, **kwargs):
        attempts.append((url, kwargs))
        raise send_webhook.requests.exceptions.ProxyError(f"Tunnel failed using {proxy}")

    monkeypatch.setattr(send_webhook, "post_webhook", fail)
    payload = {"webhook": "sample_notification", "data": registry["sample_notification"]["example"]}
    monkeypatch.setattr(sys, "argv", ["send_webhook.py", json.dumps(payload)])
    assert send_webhook.main() == 1
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert "ProxyError" in result["error"]
    assert result["data"]["request_sent"] is None
    assert result["data"]["retry_safe"] is False
    assert result["data"]["proxy"] == metadata
    for private in ("WEBHOOK_PROXY_SECRET", "private-user", "proxy-private.test"):
        assert private not in captured.out + captured.err
    assert limit_file.exists() and len(attempts) == 1
