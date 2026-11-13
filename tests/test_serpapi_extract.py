"""SerpApi extraction stays bounded, attributable and safe across tool modes."""

from __future__ import annotations

import json
import socket
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
for directory in ("lib", "skills"):
    sys.path.insert(0, str(ROOT / directory))

import serpapi_client  # noqa: E402
import serpapi_extract  # noqa: E402
from config_loader import config_scope  # noqa: E402
from tool_child_environment import (  # noqa: E402
    RESTRICTED_ENV_MARKER,
    restrict_child_environment,
)
from tool_schema import ToolSchema  # noqa: E402

SOURCE = "https://example.org/article"
FINAL = "https://example.org/articles/current"
CANONICAL = "https://example.org/articles/canonical"
BODY = "EXTRACT_ARTICLE_BODY_SENTINEL: independently useful article facts."


def page_payload(*, content: str = BODY) -> dict:
    """Use documented provider fields without saved request IDs or private data."""
    return {
        "search_metadata": {"id": "extract-fixture", "status": "Success", "credits_consumed": 1},
        "search_parameters": {"engine": "extract", "mode": "scrape", "url": SOURCE},
        "page_information": {
            "title": "Article title", "description": "A useful description.",
            "canonical": CANONICAL, "final_url": FINAL, "language": "en",
            "favicon": "https://example.org/favicon.ico",
        },
        "markdown": content,
    }


@pytest.fixture(autouse=True)
def public_dns_and_no_network(monkeypatch):
    """Use the real URL validator with controlled DNS and no provider access."""
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.215.14", 443)),
    ])
    monkeypatch.setattr(serpapi_extract, "load_config", lambda: None)
    monkeypatch.setattr(serpapi_extract, "request_serpapi", Mock(
        side_effect=AssertionError("Unexpected provider request"),
    ))


def provider(monkeypatch, payload):
    request = Mock(return_value=deepcopy(payload))
    monkeypatch.setattr(serpapi_extract, "request_serpapi", request)
    return request


def run_main(monkeypatch, capsys, arguments):
    monkeypatch.setattr(sys, "argv", ["serpapi_extract.py", json.dumps(arguments)])
    code = serpapi_extract.main()
    return code, json.loads(capsys.readouterr().out)


def test_scrape_preserves_distinct_source_redirect_and_canonical_metadata(monkeypatch):
    request = provider(monkeypatch, page_payload())
    result = serpapi_extract.extract({"url": SOURCE})

    assert result["ok"] is True
    data = result["data"]
    assert data["provider"] == "serpapi" and data["engine"] == "extract"
    assert data["mode"] == "scrape" and data["requested_url"] == SOURCE
    assert data["url"] == FINAL and data["title"] == "Article title"
    assert data["page_information"] == page_payload()["page_information"]
    assert data["content"] == BODY and data["content_chars"] == len(BODY)
    assert data["content_truncated"] is False
    assert data["external_content_trust"] == "untrusted"
    assert data["search_id"] == "extract-fixture" and data["credits_consumed"] == 1
    assert BODY not in result["speech"]
    params = request.call_args.args[0]
    assert params["engine"] == "extract" and params["mode"] == "scrape"
    assert params["url"] == SOURCE and params["include_markdown"] == "true"
    assert params["no_cache"] == "false"
    assert request.call_args.kwargs["timeout"] == 45
    assert request.call_args.kwargs["use_proxy"] is False
    assert request.call_args.kwargs["fallback_on_proxy_fail"] is False
    assert request.call_args.kwargs["max_response_bytes"] == 5 * 1024 * 1024
    assert request.call_count == 1


def test_scrape_passes_supported_reading_options_and_explicit_false(monkeypatch):
    request = provider(monkeypatch, page_payload())
    result = serpapi_extract.extract({
        "url": SOURCE, "include_markdown": False, "include_tags": "article,main",
        "exclude_tags": "nav,footer", "device": "tablet", "timeout": 120000,
        "no_cache": True,
    })

    assert result["ok"] is True
    params = request.call_args.args[0]
    assert params["include_markdown"] == "false"
    assert params["include_tags"] == "article,main" and params["exclude_tags"] == "nav,footer"
    assert params["device"] == "tablet" and params["timeout"] == 120000
    assert params["no_cache"] == "true"
    assert request.call_args.kwargs["timeout"] == 135
    assert not result["data"].get("content")


@pytest.mark.parametrize("max_chars", [1000, 20000])
def test_scrape_content_is_capped_with_original_length_and_no_speech_duplicate(
    monkeypatch, max_chars,
):
    content = BODY + "a" * 21000
    provider(monkeypatch, page_payload(content=content))
    result = serpapi_extract.extract({"url": SOURCE, "max_chars": max_chars})
    data = result["data"]
    assert result["ok"] is True
    assert data["content"] == content[:max_chars]
    assert data["content_chars"] == len(content) and data["content_truncated"] is True
    assert "truncat" in result["speech"].lower()
    assert BODY not in result["speech"]


def test_map_limits_returned_urls_without_losing_provider_count_or_source(monkeypatch):
    payload = {
        "search_parameters": {"engine": "extract", "mode": "map"},
        "search_metadata": {"id": "map-fixture", "status": "Success", "credits_consumed": 1},
        "urls": [{"url": f"https://example.org/page/{i}", "title": f"Page {i}",
                  "source": "sitemap" if i else "page",
                  "serpapi_extract_link": "https://serpapi.com/search.json?api_key=not-returned"}
                 for i in range(4)],
    }
    request = provider(monkeypatch, payload)
    result = serpapi_extract.extract({
        "url": SOURCE, "mode": "map", "max_urls": 2,
        "include_sitemap": False, "include_subdomains": True,
    })
    data = result["data"]
    assert result["ok"] is True and data["mode"] == "map"
    assert data["urls_count"] == 2 and data["provider_urls_count"] == 4
    assert data["urls_truncated"] is True
    assert data["urls"] == [
        {"url": "https://example.org/page/0", "title": "Page 0", "source": "page"},
        {"url": "https://example.org/page/1", "title": "Page 1", "source": "sitemap"},
    ]
    params = request.call_args.args[0]
    assert params["mode"] == "map" and params["include_sitemap"] == "false"
    assert params["include_subdomains"] == "true"
    assert "max_pages" not in params and "api_key" not in json.dumps(data)


def test_crawl_limits_provider_spend_and_total_content_across_pages(monkeypatch):
    payload = {
        "search_parameters": {"engine": "extract", "mode": "crawl"},
        "search_metadata": {"id": "crawl-fixture", "status": "Success", "credits_consumed": 3},
        "pages": [{"url": f"https://example.org/page/{i}", "depth": min(i, 1),
                   "page_information": {"title": f"Page {i}"}, "markdown": str(i) * 700}
                  for i in range(3)],
    }
    request = provider(monkeypatch, payload)
    result = serpapi_extract.extract({
        "url": SOURCE, "mode": "crawl", "max_pages": 2, "max_depth": 1,
        "include_subdomains": False, "max_chars": 1000,
    })
    data = result["data"]
    assert result["ok"] is True
    assert data["pages_count"] == 2 and data["provider_pages_count"] == 3
    assert data["pages_truncated"] is True and data["credits_consumed"] == 3
    assert len(data["pages"][0]["content"]) == 700
    assert len(data["pages"][1]["content"]) == 300
    assert data["pages"][1]["content_chars"] == 700
    assert data["pages"][1]["content_truncated"] is True
    params = request.call_args.args[0]
    assert params["max_pages"] == 2 and params["max_depth"] == 1
    assert params["include_subdomains"] == "false"
    assert params["include_markdown"] == "true"
    assert request.call_count == 1


def test_crawl_preserves_partial_failures_but_does_not_report_all_failed_as_success(
    monkeypatch, capsys,
):
    good = {"url": SOURCE, "depth": 0, "markdown": BODY,
            "page_information": {"title": "Good page"}}
    bad = {"url": "https://example.org/missing", "depth": 1, "error": "HTTP 404"}
    payload = {"search_parameters": {"engine": "extract"}, "pages": [good, bad]}
    provider(monkeypatch, payload)
    result = serpapi_extract.extract({"url": SOURCE, "mode": "crawl"})
    assert result["ok"] is True and result["data"]["pages_count"] == 2
    assert result["data"]["pages"][0]["content"] == BODY
    assert result["data"]["pages"][1]["error"] == "HTTP 404"

    provider(monkeypatch, {**payload, "pages": [bad]})
    code, failed = run_main(monkeypatch, capsys, {"url": SOURCE, "mode": "crawl"})
    assert code == 1 and failed["ok"] is False


def test_feed_discovery_and_inline_links_keep_safe_urls_and_explicit_source_types(monkeypatch):
    payload = page_payload()
    payload["feeds"] = [
        {"title": "RSS feed", "source": "https://example.org/rss.xml", "type": "rss"},
        {"title": "Atom feed", "source": "https://example.org/atom.xml", "type": "atom"},
        {"title": "JSON feed", "source": "https://example.org/feed.json", "type": "json"},
        {"title": "Duplicate", "source": "https://example.org/rss.xml", "type": "rss"},
        {"title": "Unsafe", "source": "javascript:alert(1)", "type": "rss"},
        {"title": "Private", "source": "http://127.0.0.1/rss.xml", "type": "rss"},
    ]
    payload["inline_links"] = [
        {"title": "Related article", "link": "https://example.org/related", "internal": True},
        {"title": "Source document", "link": "https://example.net/source", "internal": False},
        {"title": "Credentials", "link": "https://name:password@example.net/private"},
        {"title": "Internal address", "link": "http://10.0.0.1/admin"},
        {"title": "File", "link": "file:///etc/passwd"},
    ]
    provider(monkeypatch, payload)
    result = serpapi_extract.extract({"url": SOURCE})
    assert result["ok"] is True
    assert result["data"]["feeds"] == [
        {"title": "RSS feed", "url": "https://example.org/rss.xml", "type": "rss"},
        {"title": "Atom feed", "url": "https://example.org/atom.xml", "type": "atom"},
        {"title": "JSON feed", "url": "https://example.org/feed.json", "type": "json"},
    ]
    assert result["data"]["links"] == [
        {"title": "Related article", "url": "https://example.org/related", "internal": True},
        {"title": "Source document", "url": "https://example.net/source", "internal": False},
    ]


def test_feeds_alone_are_a_useful_metadata_only_response(monkeypatch):
    request = provider(monkeypatch, {"feeds": [
        {"title": "Site updates", "source": "https://example.org/rss.xml", "type": "rss"},
    ]})
    result = serpapi_extract.extract({"url": SOURCE, "include_markdown": False})
    assert result["ok"] is True
    assert result["data"]["feeds"][0]["url"] == "https://example.org/rss.xml"
    assert not result["data"].get("content")
    assert request.call_args.args[0]["include_markdown"] == "false"


def test_unsafe_redirect_canonical_and_favicon_are_not_exposed_as_clickable_sources(monkeypatch):
    payload = page_payload()
    payload["page_information"].update({
        "final_url": "https://user:password@example.org/private",
        "canonical": "http://192.168.0.2/secret", "favicon": "javascript:alert(1)",
    })
    provider(monkeypatch, payload)
    result = serpapi_extract.extract({"url": SOURCE})
    assert result["ok"] is True and result["data"]["url"] == SOURCE
    info = result["data"]["page_information"]
    assert not {"final_url", "canonical", "favicon"} & info.keys()


def test_unicode_content_and_large_reference_sets_stay_within_guard_input_budget(monkeypatch):
    content = "🛰️漢字" * 6000
    payload = page_payload(content=content)
    payload["page_information"]["description"] = "文" * 2200
    payload["inline_links"] = [
        {"title": "題" * 400, "link": "https://example.org/" + str(i) + "a" * 1900,
         "internal": True} for i in range(25)
    ]
    payload["feeds"] = [
        {"title": "新" * 400, "source": "https://example.org/" + str(i) + "f" * 1900,
         "type": "application/rss+xml"} for i in range(12)
    ]
    provider(monkeypatch, payload)
    result = serpapi_extract.extract({"url": SOURCE, "max_chars": 20000})
    assert result["ok"] is True
    data = result["data"]
    encoded = json.dumps(result, ensure_ascii=False).encode("utf-8")
    assert len(encoded) <= 60 * 1024
    assert data["content_chars"] == len(content) and data["content_truncated"] is True
    assert content.startswith(data["content"])
    assert data["provider_links_count"] == 25 and data["links_truncated"] is True
    assert data["provider_feeds_count"] == 12 and data["feeds_truncated"] is True
    assert data["links_count"] == len(data["links"])
    assert data["feeds_count"] == len(data["feeds"])
    assert len(data["links"]) <= 20 and len(data["feeds"]) <= 10


def test_real_shared_client_redacts_key_from_provider_failure_and_does_not_retry(
    monkeypatch, capsys,
):
    monkeypatch.setattr(serpapi_extract, "request_serpapi", serpapi_client.request_serpapi)
    monkeypatch.setattr(serpapi_client, "get_api_key", lambda: "fixture-secret-sentinel")
    transport = Mock(side_effect=RuntimeError(
        "Failed https://serpapi.com/search.json?api_key=fixture-secret-sentinel&engine=extract",
    ))
    monkeypatch.setattr(serpapi_client, "http_request", transport)
    code, result = run_main(monkeypatch, capsys, {"url": SOURCE})
    assert code == 1 and result["ok"] is False
    assert "fixture-secret-sentinel" not in json.dumps(result)
    assert transport.call_count == 1
    assert transport.call_args.kwargs["use_proxy"] is False


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_shipped_named_guard_policy_scans_article_once_before_model_handoff(monkeypatch, mode):
    from lib import prompt_guard_observer as observer
    from lib.prompt_guard import PromptGuardResult
    from lib.prompt_guard_policy import is_tool_selected

    provider(monkeypatch, page_payload())
    tool_result = serpapi_extract.extract({"url": SOURCE})
    scanned = []

    def scan(text, **source):
        scanned.append((text, source))
        return PromptGuardResult(status="scanned", flagged=False, threshold=0.8)

    monkeypatch.setattr(observer, "scan_text", scan)
    with config_scope(mode, overrides={
        "PROMPT_GUARD_ENABLED": "true", "PROMPT_GUARD_MAX_INPUT_BYTES": "65536",
        "PROMPT_GUARD_POLICY_FILE": str(ROOT / "config/prompt_guard_policy.json.example"),
    }):
        assert is_tool_selected("serpapi_extract")
        assert observer.review_tool_result(
            "serpapi_extract", tool_result, policy_name="web_content",
        ) is tool_result
    assert len(scanned) == 1
    text, source = scanned[0]
    assert text.count(BODY) == 1
    assert json.loads(text)["data"]["content"] == BODY
    assert source == {"source_type": "tool_result", "source_name": "serpapi_extract",
                      "policy_name": "web_content"}


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "http://127.0.0.1/", "http://192.168.1.5/",
    "http://[::1]/", "https://user:secret@example.org/",
    "http://127.0.0.1\\@example.org/", "https://localhost/",
])
def test_private_credential_and_ambiguous_urls_fail_before_provider_request(monkeypatch, url):
    def dns(host, *_args, **_kwargs):
        address = "127.0.0.1" if host == "localhost" else host
        if address not in {"127.0.0.1", "192.168.1.5", "::1"}:
            address = "93.184.215.14"
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 443))]

    monkeypatch.setattr(socket, "getaddrinfo", dns)
    request = serpapi_extract.request_serpapi
    with pytest.raises(ValueError):
        serpapi_extract.extract({"url": url})
    request.assert_not_called()


def test_mixed_public_and_private_dns_answers_fail_closed(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 443))
        for ip in ("93.184.215.14", "10.0.0.1")
    ])
    with pytest.raises(ValueError):
        serpapi_extract.extract({"url": SOURCE})
    serpapi_extract.request_serpapi.assert_not_called()


@pytest.mark.parametrize("arguments", [
    {}, {"url": 123}, {"url": ""}, {"mode": "unknown"},
    {"max_chars": 999}, {"max_chars": 20001}, {"max_chars": True},
    {"max_urls": 0}, {"max_urls": 101}, {"max_pages": 11}, {"max_pages": False},
    {"max_depth": -1}, {"max_depth": 4}, {"timeout": 999}, {"timeout": 120001},
    {"device": "watch"}, {"include_markdown": "false"},
    {"include_subdomains": 1}, {"include_sitemap": "true"}, {"no_cache": "true"},
    {"include_tags": ["main"]}, {"exclude_tags": "x" * 501},
    {"async": True}, {"raw": True}, {"extra_params": {"max_pages": 500}},
    {"engine": "google"}, {"output": "html"},
])
def test_invalid_or_unbounded_arguments_never_call_provider(monkeypatch, capsys, arguments):
    args = {"url": SOURCE, **arguments}
    if not arguments:
        args = {}
    code, result = run_main(monkeypatch, capsys, args)
    assert code == 1 and result["ok"] is False
    serpapi_extract.request_serpapi.assert_not_called()


@pytest.mark.parametrize("payload", [
    [], None, {"search_parameters": {"engine": "google"}, "markdown": BODY},
    {"search_parameters": {"engine": "extract"}},
    {"page_information": {}, "markdown": ""},
    {"page_information": "not-an-object", "markdown": []},
])
def test_unsupported_or_empty_provider_payloads_are_explicit_failures(
    monkeypatch, capsys, payload,
):
    provider(monkeypatch, payload)
    code, result = run_main(monkeypatch, capsys, {"url": SOURCE})
    assert code == 1 and result["ok"] is False
    assert result.get("error")


def test_manifest_has_bounded_schema_guard_class_and_restricted_selected_key():
    path = ROOT / "skills" / "serpapi_extract.tool.json"
    manifest = json.loads(path.read_text())
    assert manifest["availability"]["all_of_env"] == ["SERP_API_KEY"]
    assert manifest["proxy_policy"] == "off"
    assert manifest["prompt_guard_policy"] == "web_content"
    params = manifest["parameters"]
    assert params["required"] == ["url"] and params["additionalProperties"] is False
    assert set(params["properties"]["mode"]["enum"]) == {"scrape", "map", "crawl"}
    assert params["properties"]["max_pages"]["maximum"] == 10
    assert params["properties"]["max_chars"]["maximum"] == 20000
    for name in ("include_markdown", "include_subdomains", "include_sitemap", "no_cache"):
        assert params["properties"][name]["type"] == "boolean"
    schema = ToolSchema.from_json_file(str(path))
    assert schema.child_environment_names == frozenset({"SERP_API_KEY"})
    child = restrict_child_environment({
        "PATH": "/usr/bin", "JARVIS_MODE": "local", "SERP_API_KEY": "other-mode-key",
        "JARVIS_OVERRIDE_SERP_API_KEY": "selected-key", "OPENAI_API_KEY": "unrelated-secret",
        "LOCAL_PROXY": "http://proxy.invalid", "JARVIS_OVERRIDE_LOCAL_PROXY": "",
    }, schema.child_environment_names, home="/tmp/jarvis-extract-test", proxy_policy="off")
    assert child["SERP_API_KEY"] == "selected-key"
    assert child["JARVIS_MODE"] == "local" and child[RESTRICTED_ENV_MARKER] == "1"
    assert not {"OPENAI_API_KEY", "LOCAL_PROXY", "JARVIS_OVERRIDE_SERP_API_KEY"} & child.keys()


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_workflow_article_binding_preserves_reader_payload_and_is_not_search(monkeypatch, mode):
    from orchestrator import pipeline_executor
    from orchestrator.pipeline_executor import PipelineExecutor

    provider(monkeypatch, page_payload())
    tool_result = serpapi_extract.extract({"url": SOURCE})
    monkeypatch.setattr(pipeline_executor, "ToolLogger", Mock())
    monkeypatch.setattr(pipeline_executor, "LLMLogger", Mock())
    execute = Mock(return_value=tool_result)
    llm = SimpleNamespace(chat=Mock(side_effect=AssertionError("Unexpected model request")))
    with config_scope(mode, overrides={"LLM_PROVIDER": "ollama", "OLLAMA_MODEL": "test-model"}):
        pipeline = PipelineExecutor(mode, SimpleNamespace(execute=execute), provider=llm)
        assert pipeline._is_search_tool("serpapi_extract") is False
        result = pipeline.execute({
            "id": "extract_article_fixture",
            "triggers": {"explicit": ["/extract_article_fixture"]},
            "variables": {},
            "steps": [{"step": 1, "tool": "serpapi_extract", "params": {"url": SOURCE},
                       "output_var": "article"}],
            "success_speech": "Read the article.",
        }, "/extract_article_fixture")
    assert result["ok"] is True
    article = result["data"]["variables"]["article"]
    assert article["url"] == FINAL and article["content"] == BODY
    assert article["page_information"]["canonical"] == CANONICAL
    assert "search_results" not in result["data"]["variables"]
    assert execute.call_count == 1


@pytest.fixture
def context_assembler():
    from orchestrator.context_assembler import ContextAssembler

    return ContextAssembler.__new__(ContextAssembler)


def context_result(*, content: str = BODY) -> dict:
    return {"ok": True, "speech": "Read the page.", "data": {
        "provider": "serpapi", "engine": "extract", "mode": "scrape",
        "requested_url": SOURCE, "url": FINAL, "title": "Article title",
        "page_information": page_payload()["page_information"],
        "feeds": [{"title": "Site updates", "url": "https://example.org/feed.xml", "type": "rss"}],
        "content": content, "content_chars": len(content), "content_truncated": False,
        "external_content_trust": "untrusted",
    }}


@pytest.mark.parametrize("content", [BODY, "Useful article facts. " * 800])
def test_immediate_context_keeps_structured_article_and_full_source_identity(
    context_assembler, content,
):
    result = context_result(content=content)
    original = deepcopy(result)
    rendered, total, shown, truncated = context_assembler.build_llm_result_context_preview(
        "serpapi_extract", result,
    )
    projected = json.loads(rendered)
    data = projected["data"]
    assert context_assembler.tool_context_max_chars("serpapi_extract") == 10000
    assert shown == len(rendered) <= 10000 and total >= shown
    assert projected["ok"] is True
    assert data["requested_url"] == SOURCE and data["url"] == FINAL
    assert data["page_information"]["canonical"] == CANONICAL
    assert data["page_information"]["final_url"] == FINAL
    assert data["feeds"][0]["url"] == "https://example.org/feed.xml"
    assert data["content_chars"] == len(content)
    if len(content) < 10000:
        assert data["content_excerpt"] == content
        assert truncated is False and data["context_truncated"] is False
    else:
        assert len(data["content_excerpt"]) > 6000
        assert truncated is True and data["context_truncated"] is True
        assert data["content_excerpt_truncated"] is True
    assert result == original


@pytest.mark.parametrize("mode", ["map", "crawl"])
def test_immediate_context_keeps_site_and_page_identities(context_assembler, mode):
    data = context_result()["data"]
    data["mode"] = mode
    if mode == "map":
        data["urls"] = [{"url": f"https://example.org/page/{i}", "title": f"Page {i}",
                         "source": "sitemap"} for i in range(3)]
        data.update(urls_count=3, provider_urls_count=3, urls_truncated=False)
    else:
        data["pages"] = [{
            "url": f"https://example.org/page/{i}", "depth": i,
            "title": f"Page {i}", "content": f"Distinct page {i} fact. " * 100,
            "content_chars": 2200, "content_truncated": False,
        } for i in range(3)]
        data.update(pages_count=3, provider_pages_count=3, pages_truncated=False)
    rendered, _total, shown, _truncated = context_assembler.build_llm_result_context_preview(
        "serpapi_extract", {"ok": True, "data": data},
    )
    assert shown == len(rendered) <= 10000
    projected = json.loads(rendered)["data"]
    assert projected["requested_url"] == SOURCE and projected["mode"] == mode
    rows = projected["candidates"] if mode == "map" else projected["pages"]
    assert len(rows) == 3
    for i, row in enumerate(rows):
        assert row["url"] == f"https://example.org/page/{i}" and row["title"] == f"Page {i}"
        if mode == "crawl":
            assert row["depth"] == i and f"Distinct page {i} fact." in row["content_excerpt"]
            assert len(row["content_excerpt"]) > 400
        else:
            assert row["source"] == "sitemap"


@pytest.mark.parametrize("budget", [6000, 800])
def test_native_continuation_reprojects_to_budget_as_valid_json(context_assembler, budget):
    result = context_result(content="The requested article contains useful facts. " * 600)
    original = deepcopy(result)
    message, metadata = context_assembler.build_provider_tool_result_message(
        tool_name="serpapi_extract", arguments={"url": SOURCE}, result=result,
        tool_call_id="extract-call", duration_ms=123, max_chars=budget,
    )
    assert len(message) <= budget
    payload = json.loads(message.split("\nResult:\n", 1)[1])
    assert payload["result"]["ok"] is True
    assert isinstance(payload["result"]["data"], dict)
    assert "result_preview_text" not in payload
    assert metadata["result_truncated"] is True
    data = payload["result"]["data"]
    assert data["context_truncated"] is True
    if budget == 6000:
        assert data["requested_url"] == SOURCE and data["url"] == FINAL
        assert data["page_information"]["canonical"] == CANONICAL
        assert data["feeds"][0]["url"] == "https://example.org/feed.xml"
        assert len(data["content_excerpt"]) > 400
    else:
        # An identity may be omitted at the smallest budget, but never shortened
        # into a different URL or left inside an arbitrary text fragment.
        for field, expected in (("requested_url", SOURCE), ("url", FINAL)):
            if field in data:
                assert data[field] == expected
    assert result == original


def test_failed_extraction_context_keeps_error_in_preview_and_native_continuation(
    context_assembler,
):
    result = {"ok": False, "error": "The page could not be read; HTTP 403.",
              "speech": "The page could not be read."}
    preview, _total, shown, _truncated = context_assembler.build_llm_result_context_preview(
        "serpapi_extract", result,
    )
    assert shown == len(preview) <= 10000
    assert json.loads(preview)["error"] == result["error"]
    message, metadata = context_assembler.build_provider_tool_result_message(
        tool_name="serpapi_extract", arguments={"url": SOURCE}, result=result, max_chars=6000,
    )
    payload = json.loads(message.split("\nResult:\n", 1)[1])
    assert payload["result"]["ok"] is False and metadata["ok"] is False
    assert payload["result"]["error"] == result["error"]


def test_accumulated_context_preserves_already_saved_article_excerpt(context_assembler):
    from lib.serpapi_extract_context import project_serpapi_extract_runs

    result = context_result(content="Useful saved facts. " * 100 + "EXCERPT_END_SENTINEL")
    projected = project_serpapi_extract_runs(result, max_chars=6000)
    assert "content_excerpt" in projected and "content" not in projected
    rendered = context_assembler.extract_useful_data(
        {"serpapi_extract": projected},
        has_text_summarizer_summary_for_ref=lambda _item, _ref: False,
    )
    saved = json.loads(rendered.split("=== serpapi_extract ===", 1)[1].strip())
    assert saved["content_excerpt"] == projected["content_excerpt"]
    assert "EXCERPT_END_SENTINEL" in saved["content_excerpt"]
    assert saved["requested_url"] == SOURCE and saved["url"] == FINAL
    assert saved["page_information"]["canonical"] == CANONICAL


@pytest.mark.parametrize("count", [50, 100])
def test_complete_map_reaches_immediate_context_without_generic_search_candidate_cap(
    context_assembler, count,
):
    urls = [{"url": f"https://example.org/{i}", "title": str(i), "source": "page"}
            for i in range(count)]
    result = {"ok": True, "data": {
        "provider": "serpapi", "engine": "extract", "mode": "map", "requested_url": SOURCE,
        "url": SOURCE, "urls": urls, "urls_count": count, "provider_urls_count": count,
        "urls_truncated": False, "external_content_trust": "untrusted",
    }}
    preview, _total, shown, truncated = context_assembler.build_llm_result_context_preview(
        "serpapi_extract", result,
    )
    data = json.loads(preview)["data"]
    assert shown == len(preview) <= 10000
    assert data["candidates"] == [{**row, "ordinal": index + 1} for index, row in enumerate(urls)]
    assert data["candidates"][14]["url"] == urls[14]["url"]
    assert data["candidates"][-1]["url"] == urls[-1]["url"]
    assert data["candidates_truncated"] is False and truncated is False
    assert data["context_truncated"] is False


@pytest.mark.parametrize(("count", "budget"), [(50, 6000), (100, 10000)])
def test_native_map_keeps_every_returned_url_when_serialized_collection_fits(
    context_assembler, count, budget,
):
    urls = [{"url": f"https://example.org/{i}", "title": str(i), "source": "page"}
            for i in range(count)]
    result = {"ok": True, "data": {
        "provider": "serpapi", "engine": "extract", "mode": "map",
        "requested_url": SOURCE, "url": SOURCE,
        "urls": urls, "urls_count": count, "provider_urls_count": count, "urls_truncated": False,
    }}
    message, metadata = context_assembler.build_provider_tool_result_message(
        tool_name="serpapi_extract", arguments={"url": SOURCE, "mode": "map"},
        result=result, max_chars=budget,
    )
    assert len(message) <= budget
    payload = json.loads(message.split("\nResult:\n", 1)[1])
    assert payload["result"]["data"]["candidates"] == [
        {**row, "ordinal": index + 1} for index, row in enumerate(urls)
    ]
    assert payload["result_truncated"] is False and metadata["result_truncated"] is False


@pytest.mark.parametrize("provider_omission", [None, "content_truncated", "feeds_truncated"])
def test_metadata_only_read_is_complete_unless_provider_actually_omitted_results(
    context_assembler, provider_omission,
):
    result = context_result(content="")
    result["data"].update(content_omitted=True, content_chars=0)
    if provider_omission:
        result["data"][provider_omission] = True
    expected_truncated = provider_omission is not None
    preview, _total, _shown, truncated = context_assembler.build_llm_result_context_preview(
        "serpapi_extract", result,
    )
    data = json.loads(preview)["data"]
    assert data["content_omitted"] is True and "content_excerpt" not in data
    assert data["page_information"]["canonical"] == CANONICAL
    assert data["requested_url"] == SOURCE and data["url"] == FINAL
    assert data["context_truncated"] is expected_truncated and truncated is expected_truncated
    message, metadata = context_assembler.build_provider_tool_result_message(
        tool_name="serpapi_extract", arguments={"url": SOURCE, "include_markdown": False},
        result=result, max_chars=6000,
    )
    payload = json.loads(message.split("\nResult:\n", 1)[1])
    assert payload["result"]["data"]["content_omitted"] is True
    assert payload["result_truncated"] is expected_truncated
    assert metadata["result_truncated"] is expected_truncated


def test_default_native_map_continuation_preserves_complete_hundred_url_collection(
    context_assembler,
):
    urls = [{"url": f"https://example.org/docs/{i}", "title": f"Page {i}",
             "source": "sitemap"} for i in range(100)]
    result = {"ok": True, "data": {
        "provider": "serpapi", "engine": "extract", "mode": "map",
        "requested_url": SOURCE, "url": SOURCE, "urls": urls,
        "urls_count": 100, "provider_urls_count": 100, "urls_truncated": False,
    }}
    assert context_assembler.provider_result_max_chars(result, 6000) == 11200
    message, metadata = context_assembler.build_provider_tool_result_message(
        tool_name="serpapi_extract", arguments={"url": SOURCE, "mode": "map"}, result=result,
    )
    payload = json.loads(message.split("\nResult:\n", 1)[1])
    assert len(message) <= 11200
    assert payload["result"]["data"]["candidates"] == [
        {**row, "ordinal": index + 1} for index, row in enumerate(urls)
    ]
    assert payload["result_truncated"] is False and metadata["result_truncated"] is False


def test_map_compacts_very_long_labels_before_omitting_source_identities():
    from lib.serpapi_extract_context import project_serpapi_extract_runs

    urls = [{"url": f"https://e.test/{i}", "title": "Long optional label " * 30,
             "source": "sitemap"} for i in range(100)]
    result = project_serpapi_extract_runs({
        "provider": "serpapi", "engine": "extract", "mode": "map",
        "requested_url": SOURCE, "url": SOURCE, "urls": urls,
        "urls_count": 100, "provider_urls_count": 100, "urls_truncated": False,
    }, max_chars=6000)
    assert len(json.dumps(result, ensure_ascii=False)) <= 6000
    assert [row["url"] for row in result["candidates"]] == [row["url"] for row in urls]
    assert [row["ordinal"] for row in result["candidates"]] == list(range(1, 101))
    assert result["candidates_truncated"] is False
    assert result["context_metadata_truncated"] is True and result["context_truncated"] is True
