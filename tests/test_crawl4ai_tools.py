"""Crawl4AI REST contracts with controlled configuration, DNS and transport."""

import base64
import io
import json
import socket
import sys
from pathlib import Path

import pytest
import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
for directory in ("lib", "skills"):
    sys.path.insert(0, str(ROOT / directory))

import crawl_url  # noqa: E402
import screenshot_url  # noqa: E402


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


@pytest.fixture
def configured_tools(monkeypatch):
    config = {"CRAWL4AI_URL": "https://crawler.example.test", "CRAWL4AI_API_KEY": "test-token"}
    for tool in (crawl_url, screenshot_url):
        monkeypatch.setattr(tool, "load_config", lambda: None)
        monkeypatch.setattr(tool, "get_config_value", lambda key, default="": config.get(key, default))

        def reject(*args, **kwargs):
            raise AssertionError("Unexpected network request")

        monkeypatch.setattr(tool, "http_request", reject)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.215.14", 443)),
    ])
    return config


def run_tool(monkeypatch, capsys, tool, arguments):
    monkeypatch.setattr(sys, "argv", [tool.__name__, json.dumps(arguments)])
    code = tool.main()
    return code, json.loads(capsys.readouterr().out)


def test_crawl_auth_payload_and_workflow_result(configured_tools, monkeypatch, capsys):
    configured_tools.update(CRAWL4AI_USER="obsolete-user", CRAWL4AI_PASS="obsolete-pass")
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return Response({"results": [{
            "url": "https://example.org/article", "success": True,
            "markdown": {"raw_markdown": "Article content"},
            "metadata": {"title": "Article title"},
        }]})

    monkeypatch.setattr(crawl_url, "http_request", request)
    code, result = run_tool(monkeypatch, capsys, crawl_url, {
        "url": "https://example.org/article", "stealth": True,
        "wait_for_js": True, "screenshot": True,
    })
    assert code == 0 and result["ok"] is True
    assert result["data"]["results"][0] == {
        "url": "https://example.org/article", "markdown": "Article content",
        "title": "Article title", "success": True,
    }
    method, url, kwargs = calls[0]
    assert len(calls) == 1 and method == "POST" and url.endswith("/crawl")
    assert kwargs["allow_redirects"] is False and kwargs["proxy_policy"] == "off"
    assert kwargs["timeout"] == 60 and kwargs["deadline"] > 0
    assert kwargs["headers"]["Authorization"] == "Bearer test-token"
    assert "x-api-key" not in kwargs["headers"]
    body = kwargs["json"]
    assert body["urls"] == ["https://example.org/article"]
    assert "priority" not in body
    assert "screenshot" not in body
    assert body["browser_config"]["params"]["enable_stealth"] is True
    assert body["crawler_config"]["params"]["screenshot"] is True


@pytest.mark.parametrize("arguments", [
    {"js_code": "scroll_down"}, {"extraction_type": "llm"},
    {"extraction_type": "regex", "custom_patterns": {"price": "[0-9]+"}},
])
def test_bearer_rejects_disabled_features(configured_tools, monkeypatch, capsys, arguments):
    code, result = run_tool(monkeypatch, capsys, crawl_url, {
        "url": "https://example.org", **arguments,
    })
    assert code == 1 and result["ok"] is False
    assert "does not support" in result["error"]


@pytest.mark.parametrize("patterns, expected", [
    (None, 3471), (["email"], 1), (["phone"], 6), (["url"], 8),
    (["currency"], 128), (["percentage"], 256), (["date"], 3072),
    (["email", "url", "date"], 3081),
])
def test_regex_serializes_reviewed_builtin_flags(
    configured_tools, monkeypatch, capsys, patterns, expected,
):
    captured = {}

    def request(*args, **kwargs):
        captured.update(kwargs["json"]["crawler_config"]["params"]["extraction_strategy"])
        return Response({"results": [{"url": "https://example.org", "markdown": "Page content"}]})

    monkeypatch.setattr(crawl_url, "http_request", request)
    arguments = {"url": "https://example.org", "extraction_type": "regex"}
    if patterns is not None:
        arguments["regex_patterns"] = patterns
    code, result = run_tool(monkeypatch, capsys, crawl_url, arguments)
    assert code == 0 and result["ok"] is True
    assert captured == {
        "type": "RegexExtractionStrategy",
        "params": {"input_format": "markdown", "pattern": expected},
    }


@pytest.mark.parametrize("patterns", [
    [], "email", ["unknown"], [".*"], [8], [None], ["email"] * 7,
    {"email": ".*"}, None,
])
def test_regex_rejects_arbitrary_or_invalid_pattern_selection(
    configured_tools, monkeypatch, capsys, patterns,
):
    code, result = run_tool(monkeypatch, capsys, crawl_url, {
        "url": "https://example.org", "extraction_type": "regex", "regex_patterns": patterns,
    })
    assert code == 1 and "regex_patterns must be" in result["error"]


@pytest.mark.parametrize("tool", [crawl_url, screenshot_url])
@pytest.mark.parametrize("token", [None, "", "  "])
def test_missing_bearer_token_fails_before_request(configured_tools, monkeypatch, capsys, tool, token):
    configured_tools.update(CRAWL4AI_USER="obsolete-user", CRAWL4AI_PASS="obsolete-pass")
    if token is None:
        configured_tools.pop("CRAWL4AI_API_KEY")
    else:
        configured_tools["CRAWL4AI_API_KEY"] = token
    code, result = run_tool(monkeypatch, capsys, tool, {"url": "https://example.org"})
    assert code == 1 and "CRAWL4AI_API_KEY not configured" in result["error"]


def test_crawl_validates_every_batch_url_before_request(configured_tools, monkeypatch, capsys):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *_args, **_kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
         ("127.0.0.1" if host == "private.example.test" else "93.184.215.14", 443)),
    ])
    code, result = run_tool(monkeypatch, capsys, crawl_url, {
        "urls": ["https://example.org", "http://private.example.test"],
    })
    assert code == 1 and "blocked" in result["error"].lower()


@pytest.mark.parametrize("arguments", [
    {"urls": ["https://example.org"] * 11}, {"urls": "https://example.org"},
    {"url": "file:///etc/passwd"}, {"urls": [123]},
])
def test_crawl_rejects_invalid_or_unbounded_input(configured_tools, monkeypatch, capsys, arguments):
    code, result = run_tool(monkeypatch, capsys, crawl_url, arguments)
    assert code == 1 and result["ok"] is False


@pytest.mark.parametrize("tool", [crawl_url, screenshot_url])
@pytest.mark.parametrize("status", [301, 401, 403, 500])
def test_http_errors_do_not_retry_or_report_success(configured_tools, monkeypatch, capsys, tool, status):
    calls = []

    def request(*args, **kwargs):
        calls.append(kwargs)
        return Response({}, status)

    monkeypatch.setattr(tool, "http_request", request)
    arguments = {"url": "https://example.org"}
    if tool is crawl_url:
        arguments["extraction_type"] = "css"
        arguments["css_schema"] = {"baseSelector": "article", "fields": []}
    code, result = run_tool(monkeypatch, capsys, tool, arguments)
    assert code == 1 and result["ok"] is False
    assert len(calls) == 1


def test_crawl_result_failures_and_explicit_truncation(configured_tools, monkeypatch, capsys):
    monkeypatch.setattr(crawl_url, "http_request", lambda *_args, **_kwargs: Response({"results": [
        {"url": "https://example.org/failed", "success": False, "markdown": "error content"},
        {"url": "https://example.org/good", "success": True, "markdown": "x" * 10001},
        {"url": "https://example.org/structured", "success": True,
         "extracted_content": '[{"price": 42}]'},
    ]}))
    code, result = run_tool(monkeypatch, capsys, crawl_url, {"url": "https://example.org"})
    assert code == 0
    data = result["data"]
    assert data["count"] == 2 and data["failed_urls"] == ["https://example.org/failed"]
    assert data["results"][0]["truncated"] is True
    assert data["results"][0]["original_characters"] == 10001
    assert len(data["results"][0]["markdown"]) == 10000
    assert data["results"][1]["extracted_content"] == '[{"price": 42}]'


@pytest.mark.parametrize("payload", [
    {"success": False, "markdown": "error content"},
    {"results": [{"success": False, "markdown": "error content"}]},
    {"results": []},
])
def test_failed_crawls_never_become_success(configured_tools, monkeypatch, capsys, payload):
    monkeypatch.setattr(crawl_url, "http_request", lambda *_args, **_kwargs: Response(payload))
    code, result = run_tool(monkeypatch, capsys, crawl_url, {"url": "https://example.org"})
    assert code == 1 and result["ok"] is False


def test_screenshot_auth_saves_inline_image_and_preserves_analysis(
    configured_tools, monkeypatch, capsys, tmp_path,
):
    configured_tools.update(CRAWL4AI_USER="obsolete-user", CRAWL4AI_PASS="obsolete-pass")
    image = io.BytesIO()
    Image.new("RGB", (20, 10), "white").save(image, format="PNG")
    captured = {}

    def request(method, url, **kwargs):
        assert method == "POST" and url.endswith("/screenshot")
        captured.update(kwargs)
        return Response({"screenshot": base64.b64encode(image.getvalue()).decode()})

    output = tmp_path / "screenshot.jpg"
    monkeypatch.setattr(screenshot_url, "http_request", request)
    monkeypatch.setattr(screenshot_url, "resolve_screenshot_output_path", lambda _: output)
    monkeypatch.setattr(screenshot_url, "_analyze_screenshot", lambda *_args: "Visible product price")
    code, result = run_tool(monkeypatch, capsys, screenshot_url, {
        "url": "https://example.org", "wait": 3, "analyze": True,
    })
    assert code == 0 and result["data"]["analysis"] == "Visible product price"
    assert Path(result["data"]["screenshot_path"]).read_bytes().startswith(b"\xff\xd8")
    assert captured["headers"]["Authorization"] == "Bearer test-token"
    assert "x-api-key" not in captured["headers"]
    assert captured["json"] == {"url": "https://example.org", "screenshot_wait_for": 3}
    assert captured["timeout"] == 45 and captured["allow_redirects"] is False


def test_screenshot_server_failure_does_not_save_file(configured_tools, monkeypatch, capsys):
    monkeypatch.setattr(screenshot_url, "http_request", lambda *_args, **_kwargs: Response({
        "success": False, "screenshot": "invalid",
    }))
    code, result = run_tool(monkeypatch, capsys, screenshot_url, {"url": "https://example.org"})
    assert code == 1 and "failed screenshot" in result["error"]


@pytest.mark.parametrize("tool", [crawl_url, screenshot_url])
def test_timeout_returns_failure_without_resubmission(configured_tools, monkeypatch, capsys, tool):
    calls = []

    def timeout(*args, **kwargs):
        calls.append(kwargs)
        raise requests.Timeout("Test timeout")

    monkeypatch.setattr(tool, "http_request", timeout)
    code, result = run_tool(monkeypatch, capsys, tool, {"url": "https://example.org"})
    assert code == 1 and "timed out" in result["error"]
    assert len(calls) == 1
