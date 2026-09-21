"""SearXNG request, auth, output, and child environment contracts."""

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills"))
sys.path.insert(0, str(ROOT / "lib"))

import searxng_search
from tool_child_environment import restrict_child_environment
from tool_schema import ToolSchema


class Response:
    def __init__(self, payload=None, *, status=200, headers=None):
        self.payload = payload
        self.status_code = status
        self.headers = headers or {}

    def json(self):
        if isinstance(self.payload, ValueError):
            raise self.payload
        return self.payload


def _config(values):
    return lambda name, default="": values.get(name, default)


def test_search_uses_configured_json_endpoint_and_bounds_source_output(monkeypatch):
    monkeypatch.setattr(searxng_search, "get_config_value", _config({
        "SEARXNG_BASE_URL": "http://search.example.test/prefix/",
    }))
    response = Response({
        "query": "kernel release",
        "results": [
            {
                "title": "<b>Official</b> notes", "url": "https://example.org/notes",
                "content": "Kernel <b>details</b>", "engine": "brave",
                "category": "general", "publishedDate": "2026-09-20",
                "thumbnail": "https://example.org/thumb.png",
            },
            {"title": "Next", "url": "https://example.org/next", "content": "Next result"},
            {"title": "Unsafe", "url": "javascript:alert(1)", "content": "Do not show"},
        ],
        "answers": ["<strong>Answer</strong> text"],
        "suggestions": ["related query"],
        "infoboxes": [],
        "unresponsive_engines": [["example engine", "timeout"]],
    })
    with patch.object(searxng_search, "http_request", return_value=response) as request:
        result = searxng_search.search({
            "query": "kernel release", "categories": "general, news", "language": "en-US",
            "page": 2, "time_range": "week", "safesearch": 1, "max_results": 1,
        })
    assert result["ok"] is True
    assert request.call_args.args == ("GET", "http://search.example.test/prefix/search")
    kwargs = request.call_args.kwargs
    assert kwargs["params"] == {
        "q": "kernel release", "format": "json", "pageno": 2,
        "categories": "general,news", "language": "en-US",
        "time_range": "week", "safesearch": 1,
    }
    assert kwargs["use_proxy"] is False
    assert kwargs["headers"]["User-Agent"].startswith("Mozilla/5.0")
    assert "auth" not in kwargs
    data = result["data"]
    assert data["results_count"] == 1
    assert data["provider_results_count"] == 3
    assert data["results_truncated"] is True
    assert data["results"][0] == {
        "title": "Official notes", "url": "https://example.org/notes",
        "snippet": "Kernel details", "engine": "brave", "category": "general",
        "published_date": "2026-09-20", "thumbnail": "https://example.org/thumb.png",
    }
    assert data["answers"] == ["Answer text"]
    assert data["unresponsive_engine_count"] == 1
    assert data["external_content_trust"] == "untrusted"
    assert "search.example.test" not in json.dumps(result)


def test_probe_checks_json_without_returning_source_content(monkeypatch):
    monkeypatch.setattr(searxng_search, "get_config_value", _config({
        "SEARXNG_BASE_URL": "https://searx.example.org/search",
    }))
    with patch.object(searxng_search, "http_request", return_value=Response({
        "results": [{"title": "Private probe content", "url": "https://example.org"}],
    })) as request:
        result = searxng_search.probe()
    assert result == {
        "ok": True, "speech": "SearXNG JSON search is available.",
        "data": {"results_count": 1},
    }
    assert request.call_args.args[1] == "https://searx.example.org/search"
    assert request.call_args.kwargs["params"]["format"] == "json"
    assert "Private probe content" not in json.dumps(result)


def test_optional_basic_and_reverse_proxy_headers(monkeypatch):
    monkeypatch.setattr(searxng_search, "get_config_value", _config({
        "SEARXNG_BASE_URL": "https://searx.example.org",
        "SEARXNG_USERNAME": "operator",
        "SEARXNG_PASSWORD": "private-password",
        "SEARXNG_HEADER_NAME": "X-Search-Token",
        "SEARXNG_HEADER_VALUE": "private-proxy-token",
    }))
    with patch.object(searxng_search, "http_request", return_value=Response({"results": []})) as request:
        result = searxng_search.search({"query": "test"})
    assert result["ok"] is True
    assert request.call_args.kwargs["auth"] == ("operator", "private-password")
    assert request.call_args.kwargs["headers"]["X-Search-Token"] == "private-proxy-token"
    assert "private-password" not in json.dumps(result)
    assert "private-proxy-token" not in json.dumps(result)

    monkeypatch.setattr(searxng_search, "get_config_value", _config({
        "SEARXNG_BASE_URL": "https://searx.example.org",
        "SEARXNG_AUTHORIZATION": "Bearer private-bearer-token",
    }))
    with patch.object(searxng_search, "http_request", return_value=Response({"results": []})) as request:
        result = searxng_search.search({"query": "test"})
    assert result["ok"] is True
    assert request.call_args.kwargs["headers"]["Authorization"] == "Bearer private-bearer-token"
    assert "auth" not in request.call_args.kwargs
    assert "private-bearer-token" not in json.dumps(result)


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"SEARXNG_USERNAME": "someone"}, "Set both"),
        ({"SEARXNG_AUTHORIZATION": "Bearer token", "SEARXNG_USERNAME": "u",
          "SEARXNG_PASSWORD": "p"}, "Choose Basic"),
        ({"SEARXNG_HEADER_NAME": "X-Key"}, "Set both"),
        ({"SEARXNG_HEADER_NAME": "Authorization", "SEARXNG_HEADER_VALUE": "secret"},
         "valid custom header"),
        ({"SEARXNG_AUTHORIZATION": "Bearer token\nInjected: value"}, "line breaks"),
    ],
)
def test_invalid_auth_config_fails_before_network(monkeypatch, settings, message):
    monkeypatch.setattr(searxng_search, "get_config_value", _config({
        "SEARXNG_BASE_URL": "https://searx.example.org", **settings,
    }))
    with patch.object(searxng_search, "http_request") as request:
        with pytest.raises(searxng_search.SearxngError, match=message):
            searxng_search.probe()
    request.assert_not_called()


@pytest.mark.parametrize("base", [
    "https://user:password@searx.example.org",
    "https://searx.example.org/search?q=secret",
    "file:///tmp/search",
])
def test_invalid_instance_url_fails_before_network(monkeypatch, base):
    monkeypatch.setattr(searxng_search, "get_config_value", _config({
        "SEARXNG_BASE_URL": base,
    }))
    with patch.object(searxng_search, "http_request") as request:
        with pytest.raises(searxng_search.SearxngError, match="SEARXNG_BASE_URL"):
            searxng_search.probe()
    request.assert_not_called()


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (Response(status=403), "JSON output may be disabled"),
        (Response(status=401, headers={"WWW-Authenticate": "Basic realm=search"}),
         "Reverse-proxy authentication"),
        (Response(status=403, headers={"WWW-Authenticate": "Bearer realm=search"}),
         "Reverse-proxy authentication"),
        (Response(status=429), "limiter or rate limit"),
        (Response(ValueError("not JSON")), "did not return JSON"),
        (Response({"unexpected": "shape"}), "unexpected JSON"),
    ],
)
def test_probe_reports_instance_failure_without_echoing_response(monkeypatch, response, message):
    monkeypatch.setattr(searxng_search, "get_config_value", _config({
        "SEARXNG_BASE_URL": "https://searx.example.org",
    }))
    with patch.object(searxng_search, "http_request", return_value=response):
        with pytest.raises(searxng_search.SearxngError, match=message):
            searxng_search.probe()


def test_network_failure_does_not_echo_configured_address(monkeypatch):
    monkeypatch.setattr(searxng_search, "get_config_value", _config({
        "SEARXNG_BASE_URL": "https://private.example.org",
    }))
    with patch.object(searxng_search, "http_request", side_effect=requests.ConnectionError(
        "https://private.example.org/?token=private-value"
    )):
        with pytest.raises(searxng_search.SearxngError) as caught:
            searxng_search.probe()
    assert "private.example.org" not in str(caught.value)
    assert "private-value" not in str(caught.value)


def test_manifest_passes_only_instance_and_optional_front_door_settings():
    manifest = json.loads((ROOT / "skills" / "searxng_search.tool.json").read_text())
    schema = ToolSchema.from_json_file(str(ROOT / "skills" / "searxng_search.tool.json"))
    assert manifest["availability"]["all_of_env"] == ["SEARXNG_BASE_URL"]
    assert "search with SearXNG" in manifest["description"]
    assert "Do not use for an unqualified search request" in manifest["description"]
    assert manifest["parameters"]["additionalProperties"] is False
    assert schema.child_environment_names == frozenset({
        "SEARXNG_BASE_URL", "SEARXNG_USERNAME", "SEARXNG_PASSWORD",
        "SEARXNG_AUTHORIZATION", "SEARXNG_HEADER_NAME", "SEARXNG_HEADER_VALUE",
    })
    child = restrict_child_environment(
        {
            "PATH": "/usr/bin", "JARVIS_MODE": "local",
            "SEARXNG_BASE_URL": "https://searx.example.org",
            "SEARXNG_AUTHORIZATION": "Bearer private-token",
            "OPENAI_API_KEY": "unrelated-secret", "LOCAL_PROXY": "http://proxy.example",
        },
        schema.child_environment_names,
        home="/tmp/empty-home",
        proxy_policy="off",
    )
    assert child["SEARXNG_BASE_URL"] == "https://searx.example.org"
    assert child["SEARXNG_AUTHORIZATION"] == "Bearer private-token"
    assert "OPENAI_API_KEY" not in child
    assert "LOCAL_PROXY" not in child


def test_followup_keeps_source_url_and_engine_attribution():
    load_server_package("searxng_followup_server", ROOT / "jarvis-web" / "server")
    path = ROOT / "jarvis-web" / "server" / "services" / "followup_extractor.py"
    spec = importlib.util.spec_from_file_location(
        "searxng_followup_server.services.followup_extractor", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.extract_followup_data({
        "searxng_search": {"data": {
            "provider": "searxng", "query": "release notes", "results_count": 1,
            "results": [{
                "title": "Official notes", "url": "https://example.org/notes",
                "engine": "brave", "category": "general", "snippet": "A source detail.",
            }],
        }},
    })
    candidate = result["searxng_search"]["candidates"][0]
    assert candidate["url"] == "https://example.org/notes"
    assert candidate["engine"] == "brave"
    assert candidate["snippet"] == "A source detail."


def test_invalid_tool_arguments_do_not_send_requests(monkeypatch):
    monkeypatch.setattr(searxng_search, "get_config_value", _config({
        "SEARXNG_BASE_URL": "https://searx.example.org",
    }))
    with patch.object(searxng_search, "http_request") as request:
        for args in (
            {"query": ""},
            {"query": "test", "page": True},
            {"query": "test", "safesearch": 3},
            {"query": "test", "categories": "general\nInjected: value"},
            {"query": "test", "max_results": 0},
        ):
            with pytest.raises(ValueError):
                searxng_search.search(args)
    request.assert_not_called()
