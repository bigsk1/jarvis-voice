"""Native email uses its trusted webhook route without changing or replaying mail."""

import base64
import importlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests


@pytest.fixture
def email_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "path", list(sys.path))
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "lib"))
    spec = importlib.util.spec_from_file_location("email_route_test_skill", root / "skills/send_email.py")
    assert spec and spec.loader
    skill = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(skill)
    transport = importlib.import_module("webhook_transport")
    entry = {"url": "https://mail-receiver.example.test/webhook/send-email", "enabled": True}
    monkeypatch.setattr(skill, "load_config", lambda: None)
    monkeypatch.setattr(skill, "load_webhook_registry", lambda: {"send_email": entry})
    monkeypatch.setattr(skill, "load_contacts", lambda: {
        "boss": {"name": "The Boss", "email": "boss@example.test"},
    })
    monkeypatch.setattr(skill, "RATE_LIMIT_FILE", str(tmp_path / "email-cooldown.json"))
    monkeypatch.setattr(skill, "time", SimpleNamespace(time=lambda: 1000.0))
    selected = "http://proxy.example.test:8888"
    monkeypatch.setattr(transport, "get_proxy_url_chain", lambda **_kwargs: [selected])
    monkeypatch.setattr(transport, "select_reachable_proxy_url", lambda *_args: (selected, "LOCAL_PROXY"))
    monkeypatch.setattr(transport, "get_config_value", lambda key, default=None:
                        selected if key == "LOCAL_PROXY" else default)
    calls = []
    status = [200]
    failure = [None]

    def send(adapter, prepared, **kwargs):
        calls.append((adapter, prepared, kwargs))
        if failure[0] is not None:
            raise failure[0]
        response = requests.Response()
        response.status_code = status[0]
        response._content = b"synthetic acceptance"
        response.request = prepared
        response.headers["Location"] = "https://another.example.test/must-not-replay"
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    return SimpleNamespace(skill=skill, transport=transport, entry=entry, selected=selected,
                           calls=calls, status=status, failure=failure, tmp_path=tmp_path)


def _run(runtime, monkeypatch, capsys, **overrides):
    args = {"to": "Boss", "subject": "Meeting", "body": "Hello from Jarvis", **overrides}
    monkeypatch.setattr(sys, "argv", ["send_email.py", json.dumps(args)])
    try:
        runtime.skill.main()
    except SystemExit as exited:
        assert exited.code == 1
    return json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("policy", [None, "off", "prefer", "require", " PREFER "])
def test_registry_route_controls_actual_email_post(email_runtime, monkeypatch, capsys, policy):
    runtime = email_runtime
    if policy is not None:
        runtime.entry["proxy_policy"] = policy
    # A model argument and NO_PROXY cannot change an explicit registry route.
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("HTTPS_PROXY", "http://unrelated-ambient.example.test:8000")
    result = _run(runtime, monkeypatch, capsys, proxy_policy="off")
    assert result["ok"]
    assert len(runtime.calls) == 1
    adapter, prepared, kwargs = runtime.calls[0]
    proxied = policy is not None and policy.strip().lower() in {"prefer", "require"}
    assert kwargs["proxies"] == ({"http": runtime.selected, "https": runtime.selected} if proxied else {})
    assert adapter.max_retries.total == 0 and kwargs["timeout"] == 30
    assert prepared.url == runtime.entry["url"] and prepared.method == "POST"
    assert json.loads(prepared.body) == {
        "to": "boss@example.test", "subject": "Meeting", "body": "Hello from Jarvis", "from_name": "Jarvis Assistant",
    }
    receipt = result["data"]
    assert receipt["to_name"] == "The Boss"
    assert receipt["request_sent"] is True and receipt["delivery_status"] == "accepted"
    assert receipt["proxy"]["used"] is proxied
    assert receipt["proxy"]["policy"] == (policy.strip().lower() if policy else "off")


@pytest.mark.parametrize("problem", ["disabled", "invalid_policy", "unreachable_require"])
def test_email_presend_failures_do_not_reserve_recipient_or_post(email_runtime, monkeypatch, capsys, problem):
    runtime = email_runtime
    if problem == "disabled":
        runtime.entry["enabled"] = False
    elif problem == "invalid_policy":
        runtime.entry["proxy_policy"] = "unsupported"
    else:
        runtime.entry["proxy_policy"] = "require"
        monkeypatch.setattr(runtime.transport, "select_reachable_proxy_url", lambda *_args: None)
    result = _run(runtime, monkeypatch, capsys)
    assert not result["ok"]
    assert result["data"]["request_sent"] is False
    assert not Path(runtime.skill.RATE_LIMIT_FILE).exists()
    assert not runtime.calls


def test_active_recipient_cooldown_never_probes_or_sends(email_runtime, monkeypatch, capsys):
    runtime = email_runtime
    runtime.entry["proxy_policy"] = "require"
    assert runtime.skill.check_rate_limit("boss@example.test") is True
    cooldown = Path(runtime.skill.RATE_LIMIT_FILE)
    before = cooldown.read_bytes()
    def unexpected_probe(*_args, **_kwargs):
        raise AssertionError("A rate-limited email must not probe a proxy")
    monkeypatch.setattr(runtime.skill, "prepare_webhook_route", unexpected_probe)
    result = _run(runtime, monkeypatch, capsys)
    assert not result["ok"] and result["error"] == "rate_limited"
    assert result["data"]["request_sent"] is False and result["data"]["retry_after_seconds"] == 10
    assert cooldown.read_bytes() == before and not runtime.calls


def test_postattempt_value_error_remains_unknown_and_redacted(email_runtime, monkeypatch, capsys):
    runtime = email_runtime
    def invalid_receipt(*_args, **_kwargs):
        raise ValueError("private-user:PROXY_SECRET@private-proxy.example.test")
    monkeypatch.setattr(runtime.skill, "webhook_response_receipt", invalid_receipt)
    result = _run(runtime, monkeypatch, capsys)
    assert not result["ok"] and len(runtime.calls) == 1
    assert result["data"]["request_sent"] is None and result["data"]["delivery_status"] == "unknown"
    assert result["data"]["retry_safe"] is False and "PROXY_SECRET" not in json.dumps(result)


def test_attachment_and_rich_email_payload_stays_unchanged(email_runtime):
    runtime = email_runtime
    path = runtime.tmp_path / "diagram.png"
    body = b"synthetic attachment bytes"
    path.write_bytes(body)
    result = runtime.skill.send_email_webhook(
        "recipient@example.test", "Diagram", "See this diagram", runtime.entry["url"],
        image_url="https://public.example.test/old.png", link_url="https://public.example.test/details",
        attachment_path=str(path), attachment_filename="diagram.png",
    )
    assert result["ok"] and result["had_attachment"]
    assert len(runtime.calls) == 1
    _, prepared, kwargs = runtime.calls[0]
    encoded = base64.b64encode(body).decode("ascii")
    assert json.loads(prepared.body) == {
        "to": "recipient@example.test", "subject": "Diagram", "body": "See this diagram",
        "from_name": "Jarvis Assistant", "image_url": f"data:image/png;base64,{encoded}",
        "link_url": "https://public.example.test/details", "link_text": "Open Link",
        "attachment_base64": encoded, "attachment_filename": "diagram.png",
        "attachment_size": len(body), "attachment_mime": "image/png",
    }
    assert kwargs["proxies"] == {} and kwargs["timeout"] == 30


@pytest.mark.parametrize("proxied,status,sent,delivery", [
    (True, 407, False, "proxy_rejected"),
    (True, 502, None, "unknown"), (True, 503, None, "unknown"), (True, 504, None, "unknown"),
    (True, 401, None, "unknown"), (True, 307, None, "redirect_refused"),
    (False, 403, True, "rejected"), (False, 500, True, "rejected"), (False, 307, True, "redirect_refused"),
])
def test_email_http_failures_preserve_receipt_without_resending(email_runtime, monkeypatch, capsys, proxied, status, sent, delivery):
    runtime = email_runtime
    runtime.entry["proxy_policy"] = "require" if proxied else "off"
    runtime.status[0] = status
    result = _run(runtime, monkeypatch, capsys)
    assert not result["ok"]
    assert len(runtime.calls) == 1
    receipt = result["data"]
    assert receipt["request_sent"] is sent and receipt["response_received"] is True
    assert receipt["delivery_status"] == delivery and receipt["status_code"] == status
    assert receipt["retry_safe"] is False and receipt["proxy"]["used"] is proxied
    assert Path(runtime.skill.RATE_LIMIT_FILE).exists()
    if delivery == "unknown":
        assert "unknown" in result["speech"].lower() and "retrying" in result["speech"]
    elif delivery == "proxy_rejected":
        assert "no webhook reached" in result["speech"]


@pytest.mark.parametrize("failure", [requests.ReadTimeout, requests.ConnectionError, requests.exceptions.ProxyError])
def test_email_transport_exceptions_are_unknown_redacted_and_never_retried(email_runtime, monkeypatch, capsys, failure):
    runtime = email_runtime
    runtime.entry["proxy_policy"] = "require"
    runtime.failure[0] = failure("http://private-user:PROXY_SECRET@private-proxy.example.test")
    result = _run(runtime, monkeypatch, capsys)
    assert not result["ok"] and len(runtime.calls) == 1
    assert result["data"]["delivery_status"] == "unknown"
    assert result["data"]["request_sent"] is None and result["data"]["response_received"] is False
    assert result["data"]["retry_safe"] is False
    assert "PROXY_SECRET" not in json.dumps(result) and "private-proxy" not in json.dumps(result)
    assert Path(runtime.skill.RATE_LIMIT_FILE).exists()
