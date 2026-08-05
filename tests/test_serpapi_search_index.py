#!/usr/bin/env python3
"""Regression coverage for the dedicated SerpApi Search Index tool."""

import json
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT / "skills"))
sys.path.insert(0, str(ROOT / "lib"))

import serpapi_client
from serpapi_search_index import (
    SEARCH_INDEX_TIMEOUT,
    _search_index_request,
    extract_related_searches,
    extract_search_index_results,
    main,
)


def search_payload():
    return {
        "search_metadata": {
            "id": "search-index-123",
            "status": "Success",
            "created_at": "2026-08-04 20:00:00 UTC",
            "total_time_taken": 0.42,
        },
        "search_information": {
            "query_displayed": "PostgreSQL queues",
            "total_results": 314,
        },
        "organic_results": [
            {
                "position": 1,
                "title": "PostgreSQL as a durable queue",
                "link": "https://example.test/postgres-queue",
                "displayed_link": "example.test/postgres-queue",
                "snippet": "A practical guide to durable job queues backed by PostgreSQL.",
                "date": "Aug 1, 2026",
                "language": "en",
                "image_url": "https://images.example/postgres.jpg",
                "sitelinks": [
                    {
                        "title": "Queue schema",
                        "link": "https://example.test/postgres-queue/schema",
                    }
                ],
            },
            {
                "position": 2,
                "title": "Skip locked worker patterns",
                "link": "https://docs.example.test/skip-locked",
                "snippet": "Worker coordination patterns using FOR UPDATE SKIP LOCKED.",
            },
        ],
        "related_searches": [
            {"query": "PostgreSQL SKIP LOCKED queue"},
            {"query": "durable database job queue"},
            {"query": "PostgreSQL SKIP LOCKED queue"},
        ],
        "serpapi_pagination": {
            "next": "https://serpapi.com/search?engine=search_index&q=PostgreSQL&start=10"
        },
    }


def run_main(arguments, response):
    stdout = StringIO()
    argv = ["serpapi_search_index.py", json.dumps(arguments)]
    with patch("serpapi_search_index.load_config"), patch(
        "serpapi_search_index._search_index_request",
        side_effect=response if isinstance(response, Exception) else None,
        return_value=None if isinstance(response, Exception) else response,
    ) as request, patch.object(sys, "argv", argv), redirect_stdout(stdout):
        exit_code = main()
    return exit_code, json.loads(stdout.getvalue()), request


def test_result_normalization_preserves_grounding_and_followup_fields():
    results = extract_search_index_results(search_payload(), limit=10)

    assert len(results) == 2
    assert results[0] == {
        "position": 1,
        "title": "PostgreSQL as a durable queue",
        "url": "https://example.test/postgres-queue",
        "displayed_link": "example.test/postgres-queue",
        "snippet": "A practical guide to durable job queues backed by PostgreSQL.",
        "date": "Aug 1, 2026",
        "language": "en",
        "image_url": "https://images.example/postgres.jpg",
        "sitelinks": [
            {
                "title": "Queue schema",
                "url": "https://example.test/postgres-queue/schema",
            }
        ],
    }
    assert results[1]["url"] == "https://docs.example.test/skip-locked"


def test_related_queries_are_deduplicated_in_provider_order():
    assert extract_related_searches(search_payload()) == [
        "PostgreSQL SKIP LOCKED queue",
        "durable database job queue",
    ]


def test_standard_search_uses_documented_parameters_and_returns_next_offset():
    exit_code, result, request = run_main(
        {
            "query": "PostgreSQL queues",
            "num_results": 10,
            "start": 0,
            "safe": "active",
        },
        search_payload(),
    )

    params = request.call_args.args[0]
    assert exit_code == 0
    assert result["ok"] is True
    assert params == {
        "engine": "search_index",
        "q": "PostgreSQL queues",
        "num": 10,
        "start": 0,
        "safe": "active",
        "no_cache": "false",
    }
    assert result["data"]["mode"] == "standard"
    assert result["data"]["search_id"] == "search-index-123"
    assert result["data"]["total_results"] == 314
    assert result["data"]["next_start"] == 10
    assert result["data"]["has_more"] is True
    assert result["data"]["top_url"] == "https://example.test/postgres-queue"


def test_deep_mode_cache_and_restrictor_are_serialized_without_reserved_overrides():
    exit_code, result, request = run_main(
        {
            "query": "Roman concrete primary sources",
            "mode": "deep",
            "safe": "off",
            "no_cache": True,
            "json_restrictor": "organic_results[].{title, link, snippet}",
            "extra_params": {
                "custom_preview_option": "enabled",
                "engine": "google",
                "q": "overridden",
                "async": "true",
            },
        },
        search_payload(),
    )

    params = request.call_args.args[0]
    assert exit_code == 0
    assert params["engine"] == "search_index"
    assert params["q"] == "Roman concrete primary sources"
    assert params["mode"] == "deep"
    assert params["safe"] == "off"
    assert params["no_cache"] == "true"
    assert params["json_restrictor"].startswith("organic_results")
    assert params["custom_preview_option"] == "enabled"
    assert "async" not in params
    assert result["data"]["mode"] == "deep"


def test_missing_query_and_invalid_offset_fail_before_network():
    exit_code, result, request = run_main({}, search_payload())
    assert exit_code == 1
    assert "query" in result["error"]
    request.assert_not_called()

    exit_code, result, request = run_main(
        {"query": "PostgreSQL", "start": -1}, search_payload()
    )
    assert exit_code == 1
    assert "non-negative" in result["error"]
    request.assert_not_called()


def test_timeout_returns_provider_specific_error():
    exit_code, result, _request = run_main(
        {"query": "PostgreSQL queues"}, TimeoutError("timed out")
    )
    assert exit_code == 1
    assert result["error"] == "SerpApi Search Index request timed out."


def test_shared_request_is_proxy_capable_but_manifest_defaults_off():
    with patch("serpapi_search_index.request_serpapi", return_value={}) as request:
        _search_index_request({"engine": "search_index", "q": "PostgreSQL"})
    assert request.call_args.kwargs == {
        "timeout": SEARCH_INDEX_TIMEOUT,
        "use_proxy": True,
        "fallback_on_proxy_fail": True,
    }
    manifest = json.loads(
        (ROOT / "skills" / "serpapi_search_index.tool.json").read_text()
    )
    assert manifest["proxy_policy"] == "off"


def test_status_diagnostics_register_search_index_engine():
    assert serpapi_client.serpapi_engines_for_tool(
        "serpapi_search_index", {"query": "PostgreSQL"}
    ) == ("search_index",)
