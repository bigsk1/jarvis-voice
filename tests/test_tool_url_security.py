"""Exercise tool entry points with real URL validation and mocked networking."""

import builtins
import json
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for directory in ("lib", "skills"):
    sys.path.insert(0, str(ROOT / directory))

import api_call  # noqa: E402
import screenshot_url  # noqa: E402
import security_utils  # noqa: E402
import send_webhook  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_services(monkeypatch):
    monkeypatch.setattr(send_webhook, "load_config", lambda: None)
    monkeypatch.setattr(send_webhook, "load_webhook_registry", lambda: {})
    monkeypatch.setenv("CRAWL4AI_URL", "http://100.64.0.2:11235")

    def reject(*_args, **_kwargs):
        raise AssertionError("Rejected URL must not reach HTTP or rate-limit state")

    monkeypatch.setattr(send_webhook, "check_rate_limit", reject)
    monkeypatch.setattr(api_call.requests, "request", reject)
    monkeypatch.setattr(send_webhook.requests, "post", reject)


@pytest.mark.parametrize("tool", [api_call, screenshot_url, send_webhook])
@pytest.mark.parametrize("address", ["100.64.0.1", "::ffff:6440:1", "fd7a:115c:a1e0::1"])
def test_tool_rejects_tailnet_dns_before_request(monkeypatch, capsys, tool, address):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_kw: [
        (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 443))
    ])
    monkeypatch.setattr(sys, "argv", [tool.__name__, json.dumps({"url": "https://tailnet.example.test/item"})])
    assert tool.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert "blocked" in result["error"].lower()


@pytest.mark.parametrize("tool", [api_call, screenshot_url, send_webhook])
def test_tool_rejects_requests_authority_rewrite(monkeypatch, capsys, tool):
    def reject_dns(*_args, **_kwargs):
        raise AssertionError("Ambiguous authority must fail before DNS")

    monkeypatch.setattr(socket, "getaddrinfo", reject_dns)
    url = "http://100.64.0.1\\@public.example.test/item"
    monkeypatch.setattr(sys, "argv", [tool.__name__, json.dumps({"url": url})])
    assert tool.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert "backslash" in result["error"]


@pytest.mark.parametrize("tool", [api_call, screenshot_url, send_webhook])
def test_missing_validator_fails_closed_without_substring_fallback(monkeypatch, capsys, tool):
    original_import = builtins.__import__

    def unavailable(name, *args, **kwargs):
        if name == "stash_helper":
            raise ImportError("test missing validator")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", unavailable)
    monkeypatch.setattr(sys, "argv", [tool.__name__, json.dumps({"url": "https://100.64.0.1/item"})])
    assert tool.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert "validation unavailable" in result["error"]
    assert security_utils.is_safe_url("https://100.64.0.1/item") is False


def test_explicitly_configured_tailnet_webhook_still_works(monkeypatch, capsys):
    target = "http://100.64.0.2/hooks/test"
    monkeypatch.setattr(send_webhook, "load_webhook_registry", lambda: {"configured": {"url": target}})
    monkeypatch.setattr(send_webhook, "check_rate_limit", lambda *_args: (True, 0))
    calls = []

    class Response:
        status_code = 204
        text = ""

    def post(url, **kwargs):
        calls.append(url)
        assert kwargs["allow_redirects"] is False
        return Response()

    def reject_dns(*_args, **_kwargs):
        raise AssertionError("Configured webhook must not enter arbitrary-URL validation")

    monkeypatch.setattr(socket, "getaddrinfo", reject_dns)
    monkeypatch.setattr(send_webhook.requests, "post", post)
    monkeypatch.setattr(sys, "argv", ["send_webhook", json.dumps({"webhook": "configured"})])
    assert send_webhook.main() == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert calls == [target]


def test_public_screenshot_source_can_use_configured_tailnet_service(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_kw: [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.215.14", 443))
    ])

    class ReachedConfiguredService(BaseException):
        pass

    def post(url, **kwargs):
        assert url == "http://100.64.0.2:11235/screenshot"
        assert kwargs["json"]["url"] == "https://public.example.test/page"
        # Stop before response handling can save a screenshot to real Stash.
        raise ReachedConfiguredService

    monkeypatch.setattr(screenshot_url.requests, "post", post)
    monkeypatch.setattr(sys, "argv", ["screenshot_url", json.dumps({"url": "https://public.example.test/page"})])
    with pytest.raises(ReachedConfiguredService):
        screenshot_url.main()
