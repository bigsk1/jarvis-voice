#!/usr/bin/env python3
"""Redirect security boundaries for the generic api_call tool."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills"))

import api_call  # noqa: E402
import stash_helper  # noqa: E402

THREE_XX_STATUS_CODES = (300, 301, 302, 303, 304, 305, 306, 307, 308, 399)


@pytest.mark.parametrize("status_code", THREE_XX_STATUS_CODES)
def test_main_refuses_3xx_without_followup_request_or_body_parsing(
    monkeypatch, capsys, status_code
):
    calls = []

    class RedirectResponse:
        text = "redirect body must not be returned"
        headers = {"Location": "http://169.254.169.254/latest/meta-data"}

        def __init__(self, code):
            self.status_code = code

        def json(self):
            raise AssertionError("redirect response body must not be parsed")

    monkeypatch.setattr(stash_helper, "validate_url", lambda url: url)

    def fake_request(**kwargs):
        calls.append(kwargs)
        return RedirectResponse(status_code)

    monkeypatch.setattr(api_call.requests, "request", fake_request)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "api_call.py",
            json.dumps(
                {
                    "url": "https://public.example/api",
                    "method": "POST",
                    "headers": {"X-Request-ID": "test"},
                    "body": {"event": "test"},
                }
            ),
        ],
    )

    assert api_call.main() == 1
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["ok"] is False
    assert result["data"]["redirect_blocked"] is True
    assert f"status {status_code}" in result["error"]
    assert "169.254.169.254" not in output
    assert "redirect body" not in output
    assert len(calls) == 1
    assert calls[0]["allow_redirects"] is False


def test_main_preserves_nonredirecting_success(monkeypatch, capsys):
    calls = []

    class SuccessResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"status": "ok"}

    monkeypatch.setattr(stash_helper, "validate_url", lambda url: url)

    def fake_request(**kwargs):
        calls.append(kwargs)
        return SuccessResponse()

    monkeypatch.setattr(api_call.requests, "request", fake_request)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "api_call.py",
            json.dumps(
                {
                    "url": "https://public.example/api",
                    "method": "GET",
                    "params": {"limit": 1},
                }
            ),
        ],
    )

    assert api_call.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["data"]["response"] == {"status": "ok"}
    assert len(calls) == 1
    assert calls[0]["allow_redirects"] is False
