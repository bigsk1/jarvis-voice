#!/usr/bin/env python3
"""Regression coverage for the SerpApi Google Trends tool."""

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
from serpapi_google_trends import (
    GOOGLE_TRENDS_TIMEOUT,
    _google_trends_request,
    extract_interest_over_time,
    extract_region_results,
    extract_related_results,
    main,
    normalize_date,
)


def timeseries_payload():
    return {
        "search_metadata": {
            "id": "trends-123",
            "status": "Success",
            "google_trends_url": "https://trends.google.com/trends/explore?q=coffee,tea",
            "total_time_taken": 1.2,
        },
        "search_parameters": {
            "engine": "google_trends",
            "q": "coffee,tea",
            "date": "now 7-d",
            "tz": "420",
            "data_type": "TIMESERIES",
        },
        "interest_over_time": {
            "timeline_data": [
                {
                    "date": f"Aug {day}, 2026",
                    "timestamp": str(1_700_000_000 + day),
                    "values": [
                        {"query": "coffee", "value": str(coffee), "extracted_value": coffee},
                        {"query": "tea", "value": str(tea), "extracted_value": tea},
                    ],
                }
                for day, coffee, tea in (
                    (1, 40, 70),
                    (2, 50, 65),
                    (3, 55, 60),
                    (4, 60, 55),
                    (5, 80, 50),
                )
            ],
            "averages": [
                {"query": "coffee", "value": 57},
                {"query": "tea", "value": 60},
            ],
        },
    }


def run_main(arguments, response):
    stdout = StringIO()
    argv = ["serpapi_google_trends.py", json.dumps(arguments)]
    with patch("serpapi_google_trends.load_config"), patch(
        "serpapi_google_trends._google_trends_request",
        side_effect=response if isinstance(response, Exception) else None,
        return_value=None if isinstance(response, Exception) else response,
    ) as request, patch.object(sys, "argv", argv), redirect_stdout(stdout):
        exit_code = main()
    return exit_code, json.loads(stdout.getvalue()), request


def test_interest_over_time_uses_documented_params_and_full_series_summary():
    exit_code, result, request = run_main(
        {
            "query": ["coffee", "tea"],
            "data_type": "interest_over_time",
            "date": "now 7-d",
            "geo": "us",
            "language": "en",
            "max_timeline_points": 3,
            "extra_params": {"engine": "google", "q": "override", "custom": "yes"},
        },
        timeseries_payload(),
    )

    assert exit_code == 0
    assert result["ok"] is True
    assert request.call_args.args[0] == {
        "engine": "google_trends",
        "q": "coffee,tea",
        "data_type": "TIMESERIES",
        "date": "now 7-d",
        "tz": 420,
        "cat": 0,
        "no_cache": "false",
        "geo": "US",
        "hl": "en",
        "custom": "yes",
    }
    data = result["data"]
    assert data["search_id"] == "trends-123"
    assert data["timeline_points_original"] == 5
    assert data["timeline_points_returned"] == 3
    assert [point["date"] for point in data["timeline_data"]] == [
        "Aug 1, 2026",
        "Aug 3, 2026",
        "Aug 5, 2026",
    ]
    coffee = data["results"][0]
    assert coffee["latest_value"] == 80
    assert coffee["change_from_previous"] == 20
    assert coffee["change_over_period"] == 40
    assert coffee["direction"] == "rising"
    assert coffee["average_value"] == 57
    assert coffee["peak_date"] == "Aug 5, 2026"


def test_timeseries_extractor_fills_single_query_when_provider_omits_it():
    payload = {
        "interest_over_time": {
            "timeline_data": [
                {"date": "Aug 5", "values": [{"value": "81", "extracted_value": 81}]}
            ]
        }
    }
    timeline, summaries, averages, count = extract_interest_over_time(
        payload,
        ["cartoons"],
        max_points=10,
    )
    assert count == 1
    assert timeline[0]["values"][0]["query"] == "cartoons"
    assert summaries[0]["query"] == "cartoons"
    assert summaries[0]["latest_value"] == 81
    assert averages == []


def test_related_queries_prioritize_rising_and_preserve_links():
    payload = {
        "related_queries": {
            "rising": [
                {
                    "query": "iced coffee protein",
                    "value": "+2,300%",
                    "extracted_value": 2300,
                    "link": "https://trends.google.com/trends/explore?q=iced+coffee+protein",
                }
            ],
            "top": [
                {
                    "query": "coffee near me",
                    "value": "100",
                    "extracted_value": 100,
                    "link": "https://trends.google.com/trends/explore?q=coffee+near+me",
                }
            ],
        }
    }
    combined, rising, top, provider_count = extract_related_results(
        payload,
        "related_queries",
        max_results=10,
    )
    assert provider_count == 2
    assert combined[0]["trend_type"] == "rising"
    assert combined[0]["extracted_value"] == 2300
    assert combined[0]["url"].startswith("https://trends.google.com/")
    assert rising[0]["query"] == "iced coffee protein"
    assert top[0]["query"] == "coffee near me"


def test_related_provider_count_is_not_reduced_by_output_limit():
    payload = {
        "related_queries": {
            "rising": [
                {"query": f"rising {index}", "extracted_value": index}
                for index in range(4)
            ],
            "top": [
                {"query": f"top {index}", "extracted_value": index}
                for index in range(3)
            ],
        }
    }

    combined, rising, top, provider_count = extract_related_results(
        payload,
        "related_queries",
        max_results=2,
    )

    assert len(combined) == 2
    assert len(rising) == 2
    assert len(top) == 2
    assert provider_count == 7


def test_relative_hour_windows_are_case_tolerant_and_canonicalized():
    assert normalize_date("now 1-h") == "now 1-H"
    assert normalize_date("NOW 4-H") == "now 4-H"


def test_related_topics_flatten_topic_identity_and_type():
    payload = {
        "related_topics": {
            "rising": [
                {
                    "topic": {
                        "value": "/g/11qrhc4zy2",
                        "title": "Coffee and lemon",
                        "type": "Food",
                    },
                    "value": "+2,300%",
                    "extracted_value": 2300,
                    "link": "https://trends.google.com/trends/explore?q=/g/11qrhc4zy2",
                }
            ]
        }
    }
    combined, _, _, _ = extract_related_results(
        payload,
        "related_topics",
        max_results=10,
    )
    assert combined == [
        {
            "title": "Coffee and lemon",
            "topic_id": "/g/11qrhc4zy2",
            "topic_type": "Food",
            "trend_type": "rising",
            "value": "+2,300%",
            "extracted_value": 2300,
            "url": "https://trends.google.com/trends/explore?q=/g/11qrhc4zy2",
        }
    ]


def test_regional_comparison_normalizes_values_and_filters():
    payload = {
        "compared_breakdown_by_region": [
            {
                "geo": "US-OR",
                "location": "Oregon",
                "values": [
                    {"query": "coffee", "value": "70%", "extracted_value": 70},
                    {"query": "tea", "value": "30%", "extracted_value": 30},
                ],
            }
        ]
    }
    exit_code, result, request = run_main(
        {
            "query": "coffee, tea",
            "data_type": "compared_by_region",
            "geo": "US",
            "region": "region",
            "property": "news",
            "include_low_search_volume": True,
        },
        payload,
    )
    params = request.call_args.args[0]
    assert exit_code == 0
    assert params["data_type"] == "GEO_MAP"
    assert params["region"] == "REGION"
    assert params["gprop"] == "news"
    assert params["include_low_search_volume"] == "true"
    assert result["data"]["results"][0]["top_query"] == "coffee"
    assert result["data"]["results"][0]["top_value"] == 70


def test_single_interest_by_region_uses_documented_result_shape():
    results, count = extract_region_results(
        {
            "interest_by_region": [
                {"geo": "SG", "location": "Singapore", "value": "100", "extracted_value": 100},
                {"geo": "AU", "location": "Australia", "value": "87", "extracted_value": 87},
            ]
        },
        "interest_by_region",
        max_results=1,
    )
    assert count == 2
    assert results == [
        {
            "title": "Singapore",
            "location": "Singapore",
            "geo": "SG",
            "value": "100",
            "extracted_value": 100,
        }
    ]


def test_query_count_and_view_specific_validation_happen_before_network():
    cases = (
        ({}, "query"),
        ({"query": ["a", "b", "c", "d", "e", "f"]}, "at most 5"),
        ({"query": ["coffee", "tea"], "data_type": "related_queries"}, "exactly 1"),
        ({"query": "coffee", "data_type": "compared_by_region"}, "at least 2"),
        ({"query": "coffee", "include_low_search_volume": True}, "regional"),
        ({"query": "coffee", "date": "yesterday"}, "date"),
    )
    for arguments, error_fragment in cases:
        exit_code, result, request = run_main(arguments, timeseries_payload())
        assert exit_code == 1
        assert error_fragment in result["error"]
        request.assert_not_called()


def test_timeout_and_proxy_policy_contract():
    exit_code, result, _ = run_main(
        {"query": "AI agents"},
        TimeoutError("timed out"),
    )
    assert exit_code == 1
    assert result["error"] == "SerpApi Google Trends request timed out."

    with patch("serpapi_google_trends.request_serpapi", return_value={}) as request:
        _google_trends_request({"engine": "google_trends", "q": "AI agents"})
    assert request.call_args.kwargs == {
        "timeout": GOOGLE_TRENDS_TIMEOUT,
        "use_proxy": True,
        "fallback_on_proxy_fail": True,
    }
    manifest = json.loads(
        (ROOT / "skills" / "serpapi_google_trends.tool.json").read_text()
    )
    assert manifest["proxy_policy"] == "off"
    assert manifest["availability"]["all_of_env"] == ["SERP_API_KEY"]
    assert manifest["permissions"] == {
        "dangerous": False,
        "bash": False,
        "network": True,
        "filesystem": False,
        "auto_approve": True,
    }


def test_status_diagnostics_register_google_trends_engine():
    assert serpapi_client.serpapi_engines_for_tool(
        "serpapi_google_trends",
        {"query": "AI agents"},
    ) == ("google_trends",)
