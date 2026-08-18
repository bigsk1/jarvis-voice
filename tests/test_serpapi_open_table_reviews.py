#!/usr/bin/env python3
"""Regression tests for the SerpApi OpenTable Reviews tool."""

from __future__ import annotations

import json
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "skills"))
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

import serpapi_client  # noqa: E402
from serpapi_open_table_reviews import (  # noqa: E402
    SERPAPI_TIMEOUT,
    extract_open_table_reviews,
    extract_reviews_summary,
    main,
    normalize_output_format,
    normalize_rid,
)


def _payload() -> dict:
    return {
        "search_metadata": {
            "id": "search-ot-1",
            "status": "Success",
            "total_time_taken": 0.7,
            "open_table_reviews_url": (
                "https://www.opentable.com/r/central-park-boathouse-new-york-2?page=1"
            ),
        },
        "search_information": {"page": 1, "total_pages": 217},
        "reviews_summary": {
            "reviews_count": 1662,
            "ratings_count": 950,
            "ratings_summary": {
                "overall": 4.6,
                "food": 4.4,
                "service": 4.5,
                "ambience": 4.7,
                "value": 4.1,
                "noise": "Moderate",
            },
            "ratings": [{"stars": 5, "count": 688}],
            "ai_summary": "Diners praise the lakeside views, food, and service.",
        },
        "reviews": [
            {
                "id": "OT-1",
                "content": "The view of the lake is stunning.",
                "dined_at": "2026-08-01T17:30:00Z",
                "submitted_at": "2026-08-02T17:35:36Z",
                "user": {
                    "name": "Julie",
                    "number_of_reviews": 13,
                    "location": "Nashville",
                    "vip": True,
                    "avatar": "https://images.example/julie.jpg",
                },
                "rating": {
                    "overall": 5,
                    "food": 5,
                    "service": 5,
                    "ambience": 5,
                    "value": 4,
                    "noise": "Moderate",
                },
                "response": {
                    "content": "Thank you for dining with us.",
                    "date": "2026-08-03T17:42:46Z",
                },
                "images": [
                    {
                        "id": "photo-1",
                        "timestamp": "2026-08-02T17:49:58Z",
                        "variants": [
                            {"size": "small", "url": "https://images.example/small.jpg"},
                            {"size": "medium", "url": "https://images.example/medium.jpg"},
                        ],
                    }
                ],
            }
        ],
    }


@pytest.mark.parametrize(
    "value",
    [
        "r/central-park-boathouse-new-york-2",
        "/r/central-park-boathouse-new-york-2/",
        "https://www.opentable.com/r/central-park-boathouse-new-york-2?corrid=abc",
    ],
)
def test_normalize_rid_accepts_id_or_full_opentable_url(value):
    assert normalize_rid(value) == "r/central-park-boathouse-new-york-2"


@pytest.mark.parametrize(
    "value",
    ["", "central-park-boathouse", "https://example.com/r/restaurant", "restaurant/7"],
)
def test_normalize_rid_rejects_missing_or_non_opentable_ids(value):
    with pytest.raises(ValueError):
        normalize_rid(value)


def test_output_format_maps_markdown_to_provider_md():
    assert normalize_output_format("json") == ("json", "json")
    assert normalize_output_format("html") == ("html", "html")
    assert normalize_output_format("markdown") == ("markdown", "md")


def test_extractors_preserve_live_review_shape():
    reviews = extract_open_table_reviews(_payload())
    summary = extract_reviews_summary(_payload())

    assert reviews == [
        {
            "id": "OT-1",
            "text": "The view of the lake is stunning.",
            "dined_at": "2026-08-01T17:30:00Z",
            "submitted_at": "2026-08-02T17:35:36Z",
            "user": {
                "name": "Julie",
                "location": "Nashville",
                "number_of_reviews": 13,
                "vip": True,
                "avatar": "https://images.example/julie.jpg",
            },
            "rating": {
                "overall": 5,
                "food": 5,
                "service": 5,
                "ambience": 5,
                "value": 4,
                "noise": "Moderate",
            },
            "response": {
                "content": "Thank you for dining with us.",
                "date": "2026-08-03T17:42:46Z",
            },
            "images": [
                {
                    "id": "photo-1",
                    "url": "https://images.example/medium.jpg",
                    "timestamp": "2026-08-02T17:49:58Z",
                }
            ],
        }
    ]
    assert summary["ratings_summary"]["overall"] == 4.6
    assert summary["ai_summary"].startswith("Diners praise")


def test_main_returns_normalized_json_with_pagination():
    argv = [
        "serpapi_open_table_reviews.py",
        json.dumps(
            {
                "rid": "https://www.opentable.com/r/central-park-boathouse-new-york-2",
                "page": 1,
            }
        ),
    ]
    stdout = StringIO()
    with patch("serpapi_open_table_reviews.load_config"), patch(
        "serpapi_open_table_reviews.get_proxy_enabled", return_value=False
    ), patch(
        "serpapi_open_table_reviews.request_serpapi", return_value=_payload()
    ) as request, patch.object(sys, "argv", argv), redirect_stdout(stdout):
        exit_code = main()

    result = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert result["ok"] is True
    assert result["data"]["results_count"] == 1
    assert result["data"]["total_pages"] == 217
    assert result["data"]["next_page"] == 2
    assert result["data"]["reviews"][0]["user"]["name"] == "Julie"
    assert result["data"]["external_content_trust"] == "untrusted"
    request.assert_called_once_with(
        {
            "engine": "open_table_reviews",
            "rid": "r/central-park-boathouse-new-york-2",
            "page": 1,
            "no_cache": "false",
        },
        timeout=SERPAPI_TIMEOUT,
    )


def test_main_supports_markdown_provider_output():
    argv = [
        "serpapi_open_table_reviews.py",
        json.dumps(
            {
                "rid": "r/central-park-boathouse-new-york-2",
                "output_format": "markdown",
            }
        ),
    ]
    stdout = StringIO()
    with patch("serpapi_open_table_reviews.load_config"), patch(
        "serpapi_open_table_reviews.get_proxy_enabled", return_value=False
    ), patch(
        "serpapi_open_table_reviews.request_serpapi_text",
        return_value="# OpenTable Reviews\n\n| Rating | Review |",
    ) as request, patch.object(sys, "argv", argv), redirect_stdout(stdout):
        exit_code = main()

    result = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert result["data"]["output_format"] == "markdown"
    assert result["data"]["content"].startswith("# OpenTable Reviews")
    assert result["data"]["content_chars"] == len(result["data"]["content"])
    request.assert_called_once_with(
        {
            "engine": "open_table_reviews",
            "rid": "r/central-park-boathouse-new-york-2",
            "page": 1,
            "no_cache": "false",
        },
        "md",
        timeout=SERPAPI_TIMEOUT,
    )


def test_shared_text_request_uses_search_endpoint_and_output_parameter():
    response = SimpleNamespace(
        status_code=200,
        text="# Reviews",
        headers={"content-type": "text/markdown"},
        json=lambda: {},
    )
    with patch.object(serpapi_client, "get_api_key", return_value="secret"), patch.object(
        serpapi_client, "http_request", return_value=response
    ) as request:
        content = serpapi_client.request_serpapi_text(
            {"engine": "open_table_reviews", "rid": "r/example"},
            "md",
            timeout=45,
            use_proxy=False,
        )

    assert content == "# Reviews"
    request.assert_called_once_with(
        "GET",
        serpapi_client.SERPAPI_SEARCH_ENDPOINT,
        params={
            "engine": "open_table_reviews",
            "rid": "r/example",
            "api_key": "secret",
            "output": "md",
        },
        timeout=45,
        use_proxy=False,
        fallback_on_proxy_fail=True,
    )


def test_manifest_and_incident_mapping_cover_open_table_reviews():
    manifest = json.loads(
        (PROJECT_ROOT / "skills" / "serpapi_open_table_reviews.tool.json").read_text()
    )
    assert manifest["enabled"] is True
    assert manifest["proxy_policy"] == "off"
    assert manifest["availability"]["all_of_env"] == ["SERP_API_KEY"]
    assert manifest["prerequisite_tools"] == ["serpapi_search_index"]
    assert manifest["parameters"]["properties"]["output_format"]["enum"] == [
        "json",
        "html",
        "markdown",
    ]
    assert serpapi_client.serpapi_engines_for_tool(
        "serpapi_open_table_reviews", {}
    ) == ("open_table_reviews",)
    assert "Never fabricate a likely r/ slug" in manifest["description"]
    assert (
        "Never guess or construct this value"
        in manifest["parameters"]["properties"]["rid"]["description"]
    )
