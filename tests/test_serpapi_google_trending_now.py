#!/usr/bin/env python3
"""Regression coverage for the SerpApi Google Trends Trending Now tool."""

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
from serpapi_google_trending_now import (
    TRENDING_NOW_TIMEOUT,
    _trending_now_request,
    extract_news,
    extract_trending_searches,
    main,
)


def trending_payload():
    return {
        "search_metadata": {
            "id": "trending-123",
            "status": "Success",
            "google_trends_trending_now_url": "https://trends.google.com/_/trending",
            "total_time_taken": 1.1,
        },
        "search_parameters": {
            "engine": "google_trends_trending_now",
            "geo": "US",
            "hours": 24,
        },
        "trending_searches": [
            {
                "query": "agentic ai",
                "start_timestamp": 1785891600,
                "active": True,
                "search_volume": 200000,
                "increase_percentage": 1000,
                "categories": [
                    {"id": 18, "name": "Technology"},
                    {"id": 3, "name": "Business and Finance"},
                ],
                "trend_breakdown": ["ai agents", "agent frameworks"],
                "serpapi_google_trends_link": "https://serpapi.com/search.json?engine=google_trends&q=agentic+ai",
                "news_page_token": "token-agentic-ai",
                "serpapi_news_link": "https://serpapi.com/search.json?engine=google_trends_news&page_token=token-agentic-ai",
            },
            {
                "query": "summer travel",
                "start_timestamp": 1785888000,
                "end_timestamp": 1785895200,
                "active": False,
                "search_volume": 50000,
                "increase_percentage": 300,
                "categories": [{"id": 19, "name": "Travel and Transportation"}],
                "news_page_token": "token-summer-travel",
            },
            {
                "query": "climate report",
                "start_timestamp": 1785884400,
                "active": True,
                "search_volume": 10000,
                "increase_percentage": 200,
                "categories": [{"id": 20, "name": "Climate"}],
            },
        ],
    }


def news_payload():
    return {
        "search_metadata": {
            "id": "news-123",
            "status": "Success",
            "google_trends_news_url": "https://trends.google.com/_/news",
        },
        "search_parameters": {
            "engine": "google_trends_news",
            "page_token": "token-agentic-ai",
        },
        "news": [
            {
                "title": "Agentic AI moves into enterprise software",
                "link": "https://news.example/agentic-enterprise",
                "source": "Example News",
                "date": "2 hours ago",
                "thumbnail": "https://images.example/agentic.jpg",
            },
            {
                "title": "What AI agents can do now",
                "link": "https://journal.example/ai-agents",
                "source": "Example Journal",
                "date": "5 hours ago",
            },
        ],
    }


def run_main(arguments, response):
    stdout = StringIO()
    argv = ["serpapi_google_trending_now.py", json.dumps(arguments)]
    with patch("serpapi_google_trending_now.load_config"), patch(
        "serpapi_google_trending_now._trending_now_request",
        side_effect=response if isinstance(response, Exception) else None,
        return_value=None if isinstance(response, Exception) else response,
    ) as request, patch.object(sys, "argv", argv), redirect_stdout(stdout):
        exit_code = main()
    return exit_code, json.loads(stdout.getvalue()), request


def test_trending_now_uses_documented_params_and_normalizes_drill_down_tokens():
    exit_code, result, request = run_main(
        {
            "geo": "us",
            "hours": 24,
            "category_id": 18,
            "only_active": True,
            "language": "en",
            "max_results": 2,
            "max_breakdown_queries": 1,
            "extra_params": {"engine": "google", "geo": "GB", "custom": "yes"},
        },
        trending_payload(),
    )

    assert exit_code == 0
    assert result["ok"] is True
    assert request.call_count == 1
    assert request.call_args.args[0] == {
        "engine": "google_trends_trending_now",
        "geo": "US",
        "hours": 24,
        "only_active": "true",
        "no_cache": "false",
        "category_id": 18,
        "hl": "en",
        "custom": "yes",
    }
    data = result["data"]
    assert data["search_id"] == "trending-123"
    assert data["results_count"] == 2
    assert data["provider_results_count"] == 3
    assert data["active_results_count"] == 2
    assert data["top_query"] == "agentic ai"
    first = data["results"][0]
    assert first["search_volume"] == 200000
    assert first["increase_percentage"] == 1000
    assert first["category_names"] == ["Technology", "Business and Finance"]
    assert first["trend_breakdown"] == ["ai agents"]
    assert first["news_page_token"] == "token-agentic-ai"
    assert first["google_trends_url"].startswith("https://trends.google.com/")
    second = data["results"][1]
    assert second["active"] is False
    assert second["end_time"].endswith("Z")


def test_extract_trending_searches_counts_full_provider_set_before_output_limit():
    results, provider_count, active_count = extract_trending_searches(
        trending_payload(),
        geo="US",
        max_results=1,
        max_breakdown_queries=0,
    )

    assert len(results) == 1
    assert provider_count == 3
    assert active_count == 2
    assert "trend_breakdown" not in results[0]


def test_topic_like_query_is_not_sent_and_scope_is_explicit():
    exit_code, result, request = run_main(
        {
            "query": "agentic ai",
            "max_results": 1,
        },
        trending_payload(),
    )

    assert exit_code == 0
    assert "query" not in request.call_args.args[0]
    data = result["data"]
    assert data["requested_topic"] == "agentic ai"
    assert "seedless feed" in data["scope_notice"]
    assert "was not used as a filter" in result["speech"]


def test_news_action_requires_token_and_returns_fetchable_articles():
    exit_code, result, request = run_main(
        {
            "action": "news",
            "page_token": "token-agentic-ai",
            "trend_query": "agentic ai",
            "max_results": 1,
            "extra_params": {"page_token": "override", "custom": "yes"},
        },
        news_payload(),
    )

    assert exit_code == 0
    assert request.call_count == 1
    assert request.call_args.args[0] == {
        "engine": "google_trends_news",
        "page_token": "token-agentic-ai",
        "no_cache": "false",
        "custom": "yes",
    }
    data = result["data"]
    assert data["action"] == "news"
    assert data["provider_results_count"] == 2
    assert data["results_count"] == 1
    assert data["trend_query"] == "agentic ai"
    assert data["top_url"] == "https://news.example/agentic-enterprise"
    assert data["results"][0] == {
        "position": 1,
        "title": "Agentic AI moves into enterprise software",
        "url": "https://news.example/agentic-enterprise",
        "source": "Example News",
        "date": "2 hours ago",
        "thumbnail": "https://images.example/agentic.jpg",
    }


def test_news_extractor_preserves_provider_count_when_bounded():
    results, provider_count = extract_news(news_payload(), max_results=1)
    assert len(results) == 1
    assert provider_count == 2


def test_action_specific_validation_happens_before_network():
    cases = (
        ({"action": "unknown"}, "action"),
        ({"geo": "USA"}, "geo"),
        ({"hours": 12}, "hours"),
        ({"category_id": 12}, "category_id"),
        ({"action": "news"}, "page_token"),
        ({"page_token": "unexpected"}, "only for the news"),
        (
            {"action": "news", "page_token": "token", "trend_query": "x" * 101},
            "trend_query",
        ),
    )
    for arguments, error_fragment in cases:
        exit_code, result, request = run_main(arguments, trending_payload())
        assert exit_code == 1
        assert error_fragment in result["error"]
        request.assert_not_called()


def test_timeout_proxy_manifest_and_availability_contract():
    exit_code, result, _ = run_main({}, TimeoutError("timed out"))
    assert exit_code == 1
    assert result["error"] == "SerpApi Google Trends request timed out."

    with patch("serpapi_google_trending_now.request_serpapi", return_value={}) as request:
        _trending_now_request({"engine": "google_trends_trending_now", "geo": "US"})
    assert request.call_args.kwargs == {
        "timeout": TRENDING_NOW_TIMEOUT,
        "use_proxy": True,
        "fallback_on_proxy_fail": True,
    }

    manifest = json.loads(
        (ROOT / "skills" / "serpapi_google_trending_now.tool.json").read_text()
    )
    assert manifest["proxy_policy"] == "off"
    description = manifest["description"].lower()
    assert len(manifest["description"]) < 750
    assert "what is trending now?" in description
    assert "latest trends on google" in description
    assert "show current search trends" in description
    assert "examples" not in manifest
    assert manifest["availability"]["all_of_env"] == ["SERP_API_KEY"]
    assert manifest["permissions"] == {
        "dangerous": False,
        "bash": False,
        "network": True,
        "filesystem": False,
        "auto_approve": True,
    }


def test_status_diagnostics_select_engine_by_action():
    assert serpapi_client.serpapi_engines_for_tool(
        "serpapi_google_trending_now",
        {},
    ) == ("google_trends_trending_now",)
    assert serpapi_client.serpapi_engines_for_tool(
        "serpapi_google_trending_now",
        {"action": "news", "page_token": "token"},
    ) == ("google_trends_news",)
