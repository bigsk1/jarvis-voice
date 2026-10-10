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

    monkeypatch.setattr(send_webhook.requests, "post", post)
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
    assert len(calls) == 1 and calls[0][1]["json"] == body
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
    assert calls[0][1]["json"] == body


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

    monkeypatch.setattr(send_webhook.requests, 'post', timeout)
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
