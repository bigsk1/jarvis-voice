#!/usr/bin/env python3
"""Regression coverage for the dedicated SerpApi Google News Light tool."""

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
from serpapi_google_news_light import (
    GOOGLE_NEWS_LIGHT_TIMEOUT,
    _google_news_light_request,
    extract_news_results,
    extract_top_stories,
    main,
)


def news_payload():
    return {
        "search_metadata": {
            "id": "news-light-123",
            "status": "Success",
            "cached": True,
            "google_news_light_url": "https://www.google.com/search?q=agentic+AI&tbm=nws",
        },
        "search_information": {
            "query_displayed": "agentic AI",
            "news_results_state": "Results for exact spelling",
        },
        "news_results": [
            {
                "position": 1,
                "title": "Agentic AI attracts new funding",
                "link": "https://news.example/agentic-funding",
                "source": "Example News",
                "thumbnail": "https://images.example/funding.jpg",
                "snippet": "Several agent startups announced new rounds.",
                "date": "2 hours ago",
            },
            {
                "position": 2,
                "title": "Enterprises test autonomous agents",
                "link": "https://business.example/agents",
                "source": "Business Example",
                "date": "Yesterday",
            },
        ],
        "top_stories": [
            {
                "title": "AI funding",
                "stories": [
                    {
                        "title": "Investors return to AI agents",
                        "link": "https://finance.example/ai-agents",
                        "source": "Finance Example",
                        "date": "1 hour ago",
                    },
                    {
                        "title": "A second investor view",
                        "link": "https://markets.example/agents",
                        "source": "Markets Example",
                        "date": "3 hours ago",
                    },
                ],
            },
            {
                "title": "Enterprise agents",
                "stories": [
                    {
                        "title": "CIOs evaluate agent platforms",
                        "link": "https://cio.example/platforms",
                        "source": "CIO Example",
                        "date": "Today",
                    }
                ],
            },
        ],
        "serpapi_pagination": {
            "current": 1,
            "next": "https://serpapi.com/search?engine=google_news_light&q=agentic+AI&start=10",
            "previous": "https://serpapi.com/search?engine=google_news_light&q=agentic+AI&start=0",
        },
    }


def run_main(arguments, response):
    stdout = StringIO()
    argv = ["serpapi_google_news_light.py", json.dumps(arguments)]
    with patch("serpapi_google_news_light.load_config"), patch(
        "serpapi_google_news_light._google_news_light_request",
        side_effect=response if isinstance(response, Exception) else None,
        return_value=None if isinstance(response, Exception) else response,
    ) as request, patch.object(sys, "argv", argv), redirect_stdout(stdout):
        exit_code = main()
    return exit_code, json.loads(stdout.getvalue()), request


def test_result_normalization_preserves_articles_and_bounded_top_stories():
    results, provider_count = extract_news_results(news_payload(), max_results=1)
    groups, group_count, article_count = extract_top_stories(
        news_payload(), max_groups=1, max_stories_per_group=1
    )

    assert provider_count == 2
    assert results == [{
        "position": 1,
        "title": "Agentic AI attracts new funding",
        "url": "https://news.example/agentic-funding",
        "source": "Example News",
        "thumbnail": "https://images.example/funding.jpg",
        "snippet": "Several agent startups announced new rounds.",
        "date": "2 hours ago",
    }]
    assert group_count == 2
    assert article_count == 3
    assert groups[0]["provider_stories_count"] == 2
    assert groups[0]["stories"] == [{
        "position": 1,
        "title": "Investors return to AI agents",
        "url": "https://finance.example/ai-agents",
        "source": "Finance Example",
        "date": "1 hour ago",
    }]


def test_search_uses_documented_parameters_and_returns_safe_pagination():
    exit_code, result, request = run_main(
        {
            "query": "agentic AI",
            "location": "Austin, Texas, United States",
            "country": "us",
            "language": "en",
            "language_restrict": "lang_en|lang_fr",
            "google_domain": "google.com",
            "safe": "off",
            "exclude_autocorrected": True,
            "filter_similar": False,
            "start": 10,
            "device": "mobile",
            "no_cache": True,
            "max_results": 2,
            "max_top_story_groups": 1,
            "max_stories_per_group": 1,
        },
        news_payload(),
    )

    params = request.call_args.args[0]
    assert exit_code == 0
    assert result["ok"] is True
    assert params == {
        "engine": "google_news_light",
        "q": "agentic AI",
        "google_domain": "google.com",
        "safe": "off",
        "nfpr": "1",
        "filter": "0",
        "start": 10,
        "device": "mobile",
        "no_cache": "true",
        "location": "Austin, Texas, United States",
        "gl": "us",
        "hl": "en",
        "lr": "lang_en|lang_fr",
    }
    data = result["data"]
    assert data["results_count"] == 2
    assert data["top_stories_count"] == 1
    assert data["top_story_articles_count"] == 1
    assert data["provider_top_story_articles_count"] == 3
    assert data["next_start"] == 10
    assert data["pagination"] == {
        "current": 1,
        "start": 10,
        "has_more": True,
        "next_start": 10,
        "previous_start": 0,
    }
    assert data["top_url"] == "https://news.example/agentic-funding"
    assert "serpapi.com/search" not in json.dumps(data["pagination"])


def test_uule_and_extra_params_preserve_reserved_contract():
    exit_code, _result, request = run_main(
        {
            "query": "robotics",
            "uule": "w+CAIQICImU2FuIEZyYW5jaXNjbyxDYWxpZm9ybmlhLFVuaXRlZCBTdGF0ZXM",
            "extra_params": {
                "custom_option": "enabled",
                "engine": "google",
                "q": "override",
                "async": "true",
                "output": "html",
                "start": 999,
            },
        },
        news_payload(),
    )

    assert exit_code == 0
    params = request.call_args.args[0]
    assert params["engine"] == "google_news_light"
    assert params["q"] == "robotics"
    assert params["start"] == 0
    assert params["uule"].startswith("w+CAIQ")
    assert params["custom_option"] == "enabled"
    assert "async" not in params
    assert "output" not in params


def test_invalid_inputs_fail_before_network():
    cases = (
        ({}, "query"),
        ({"query": "AI", "location": "Austin", "uule": "encoded"}, "cannot"),
        ({"query": "AI", "country": "usa"}, "two-letter"),
        ({"query": "AI", "language_restrict": "en"}, "lang_en"),
        ({"query": "AI", "device": "watch"}, "device"),
        ({"query": "AI", "start": -1}, "start"),
        ({"query": "AI", "extra_params": []}, "object"),
    )
    for arguments, expected in cases:
        exit_code, result, request = run_main(arguments, news_payload())
        assert exit_code == 1
        assert expected in result["error"]
        request.assert_not_called()


def test_raw_payload_is_opt_in_and_empty_results_are_successful():
    exit_code, result, _request = run_main({"query": "AI"}, news_payload())
    assert exit_code == 0
    assert "raw" not in result["data"]

    exit_code, result, _request = run_main(
        {"query": "unlikely phrase", "include_raw": True},
        {"news_results": [], "top_stories": []},
    )
    assert exit_code == 0
    assert result["data"]["raw"] == {"news_results": [], "top_stories": []}
    assert "no news results" in result["speech"]


def test_timeout_returns_provider_specific_error():
    exit_code, result, _request = run_main(
        {"query": "agentic AI"}, TimeoutError("timed out")
    )
    assert exit_code == 1
    assert result["error"] == "SerpApi Google News Light request timed out."


def test_shared_request_is_proxy_capable_but_manifest_defaults_off():
    with patch("serpapi_google_news_light.request_serpapi", return_value={}) as request:
        _google_news_light_request({"engine": "google_news_light", "q": "AI"})
    assert request.call_args.kwargs == {
        "timeout": GOOGLE_NEWS_LIGHT_TIMEOUT,
        "use_proxy": True,
        "fallback_on_proxy_fail": True,
    }
    manifest = json.loads(
        (ROOT / "skills" / "serpapi_google_news_light.tool.json").read_text()
    )
    assert manifest["proxy_policy"] == "off"
    assert manifest["availability"]["all_of_env"] == ["SERP_API_KEY"]


def test_status_diagnostics_register_google_news_light_engine():
    assert serpapi_client.serpapi_engines_for_tool(
        "serpapi_google_news_light", {"query": "agentic AI"}
    ) == ("google_news_light",)
