#!/usr/bin/env python3
"""Security boundaries for the send_webhook tool."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills"))

import send_webhook  # noqa: E402

THREE_XX_STATUS_CODES = (300, 301, 302, 303, 304, 305, 306, 307, 308, 399)


def test_registry_header_expands_only_explicit_placeholder(monkeypatch):
    requested = []

    def fake_get_config_value(name, default=None):
        requested.append(name)
        return {"WEBHOOK_TOKEN": "registry-secret"}.get(name, default)

    monkeypatch.setattr(send_webhook, "get_config_value", fake_get_config_value)

    headers = send_webhook.process_headers(
        {"headers": {"Authorization": "Bearer ${WEBHOOK_TOKEN}"}},
        {"X-Trace-ID": "deployment-42"},
    )

    assert headers == {
        "Authorization": "Bearer registry-secret",
        "X-Trace-ID": "deployment-42",
    }
    assert requested == ["WEBHOOK_TOKEN"]


def test_tool_header_cannot_select_environment_variable(monkeypatch):
    def unexpected_lookup(*_args, **_kwargs):
        raise AssertionError("tool-supplied placeholder reached config lookup")

    monkeypatch.setattr(send_webhook, "get_config_value", unexpected_lookup)

    with pytest.raises(ValueError, match="only allowed in config/webhook_registry.json"):
        send_webhook.process_headers({}, {"X-Leak": "${ANY_ENV_VAR}"})


def test_literal_tool_header_still_overrides_registry_header():
    headers = send_webhook.process_headers(
        {"headers": {"X-Request-ID": "registry-default"}},
        {"X-Request-ID": "request-value"},
    )

    assert headers == {"X-Request-ID": "request-value"}


def test_main_rejects_placeholder_before_network_request(monkeypatch, capsys):
    monkeypatch.setattr(send_webhook, "load_config", lambda: None)
    monkeypatch.setattr(
        send_webhook,
        "load_webhook_registry",
        lambda: {"named": {"url": "https://example.test/webhook"}},
    )
    monkeypatch.setattr(send_webhook, "check_rate_limit", lambda *_args: (True, 0))

    def unexpected_post(*_args, **_kwargs):
        raise AssertionError("network request should not run")

    monkeypatch.setattr(send_webhook.requests, "post", unexpected_post)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "send_webhook.py",
            json.dumps(
                {
                    "webhook": "named",
                    "data": {"event": "test"},
                    "headers": {"X-Leak": "Bearer ${ANY_ENV_VAR}"},
                }
            ),
        ],
    )

    assert send_webhook.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert "only allowed in config/webhook_registry.json" in result["error"]


def test_main_sends_registry_credential_and_literal_tool_header(monkeypatch, capsys):
    calls = []

    class FakeResponse:
        status_code = 204
        text = ""

    monkeypatch.setattr(send_webhook, "load_config", lambda: None)
    monkeypatch.setattr(
        send_webhook,
        "load_webhook_registry",
        lambda: {
            "named": {
                "url": "https://example.test/webhook",
                "headers": {"Authorization": "Bearer ${WEBHOOK_TOKEN}"},
            }
        },
    )
    monkeypatch.setattr(
        send_webhook,
        "get_config_value",
        lambda name, default=None: (
            "registry-secret" if name == "WEBHOOK_TOKEN" else default
        ),
    )
    monkeypatch.setattr(send_webhook, "check_rate_limit", lambda *_args: (True, 0))

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(send_webhook.requests, "post", fake_post)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "send_webhook.py",
            json.dumps(
                {
                    "webhook": "named",
                    "data": {"event": "test"},
                    "headers": {"X-Trace-ID": "deployment-42"},
                }
            ),
        ],
    )

    assert send_webhook.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert calls == [
        (
            "https://example.test/webhook",
            {
                "json": {"event": "test"},
                "headers": {
                    "Authorization": "Bearer registry-secret",
                    "X-Trace-ID": "deployment-42",
                    "Content-Type": "application/json",
                },
                "timeout": 15,
                "allow_redirects": False,
            },
        )
    ]


@pytest.mark.parametrize("status_code", THREE_XX_STATUS_CODES)
def test_main_refuses_3xx_without_followup_request_or_body_output(
    monkeypatch, capsys, status_code
):
    calls = []

    class RedirectResponse:
        text = "redirect body must not be returned"
        headers = {"Location": "http://127.0.0.1/private"}

        def __init__(self, code):
            self.status_code = code

    monkeypatch.setattr(send_webhook, "load_config", lambda: None)
    monkeypatch.setattr(
        send_webhook,
        "load_webhook_registry",
        lambda: {"named": {"url": "https://example.test/webhook"}},
    )
    monkeypatch.setattr(send_webhook, "check_rate_limit", lambda *_args: (True, 0))

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return RedirectResponse(status_code)

    monkeypatch.setattr(send_webhook.requests, "post", fake_post)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "send_webhook.py",
            json.dumps({"webhook": "named", "data": {"event": "test"}}),
        ],
    )

    assert send_webhook.main() == 1
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["ok"] is False
    assert result["data"]["redirect_blocked"] is True
    assert f"status {status_code}" in result["error"]
    assert "127.0.0.1" not in output
    assert "redirect body" not in output
    assert len(calls) == 1
    assert calls[0][1]["allow_redirects"] is False


def test_direct_url_redirect_is_refused_after_initial_validation(
    monkeypatch, capsys
):
    import stash_helper

    calls = []

    class RedirectResponse:
        status_code = 302
        text = ""
        headers = {"Location": "http://169.254.169.254/latest/meta-data"}

    monkeypatch.setattr(send_webhook, "load_config", lambda: None)
    monkeypatch.setattr(send_webhook, "load_webhook_registry", lambda: {})
    monkeypatch.setattr(send_webhook, "check_rate_limit", lambda *_args: (True, 0))
    monkeypatch.setattr(stash_helper, "validate_url", lambda url: url)

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return RedirectResponse()

    monkeypatch.setattr(send_webhook.requests, "post", fake_post)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "send_webhook.py",
            json.dumps(
                {
                    "url": "https://public.example/webhook",
                    "data": {"event": "test"},
                }
            ),
        ],
    )

    assert send_webhook.main() == 1
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["data"]["redirect_blocked"] is True
    assert "169.254.169.254" not in output
    assert len(calls) == 1
    assert calls[0][1]["allow_redirects"] is False
