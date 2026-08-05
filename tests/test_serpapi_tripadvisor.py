#!/usr/bin/env python3
"""Regression coverage for the unified SerpApi Tripadvisor tool."""

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
from serpapi_tripadvisor import (
    SERPAPI_TIMEOUT,
    _tripadvisor_request,
    extract_interesting_places,
    extract_tripadvisor_place,
    extract_tripadvisor_reviews,
    extract_tripadvisor_search_results,
    main,
    normalize_category,
)


def run_main(arguments, responses):
    stdout = StringIO()
    argv = ["serpapi_tripadvisor.py", json.dumps(arguments)]
    side_effect = responses if isinstance(responses, list) else None
    return_value = None if side_effect is not None else responses
    with patch("serpapi_tripadvisor.load_config"), patch(
        "serpapi_tripadvisor._tripadvisor_request",
        side_effect=side_effect,
        return_value=return_value,
    ) as request, patch.object(sys, "argv", argv), redirect_stdout(stdout):
        exit_code = main()
    return exit_code, json.loads(stdout.getvalue()), request


def search_payload():
    return {
        "search_metadata": {
            "status": "Success",
            "tripadvisor_url": "https://www.tripadvisor.com/Search?q=Rome",
        },
        "places": [
            {
                "position": 1,
                "title": "Rome",
                "place_id": 187791,
                "place_type": "GEO",
                "link": "https://www.tripadvisor.com/Tourism-g187791-Rome.html",
                "description": "Historic city with museums, food, and monuments.",
                "location": "Lazio, Italy",
                "thumbnail": "https://images.example/rome.jpg",
            },
            {
                "position": 2,
                "title": "Colosseum Tour",
                "place_id": 11449756,
                "place_type": "ATTRACTION_PRODUCT",
                "rating": 4.8,
                "reviews": 5785,
                "link": "https://www.tripadvisor.com/AttractionProductReview-d11449756.html",
                "highlighted_review": {"text": "A fascinating tour", "mention_count": 1160},
            },
        ],
    }


def detail_payload():
    return {
        "search_metadata": {
            "status": "Success",
            "tripadvisor_place_url": "https://www.tripadvisor.com/Tourism-g187791-Rome.html",
        },
        "place_result": {
            "type": "destination",
            "name": "Rome, Italy",
            "description": "Ancient sites, lively neighborhoods, and memorable food.",
            "images": ["https://images.example/rome-detail.jpg"],
            "travel_advice": [
                {"title": "Best time to visit", "link": "https://example.test/advice"}
            ],
            "attraction_suggestions": {
                "items": [
                    {
                        "name": "Colosseum",
                        "place_id": "192285",
                        "link": "https://www.tripadvisor.com/Attraction_Review-d192285.html",
                        "thumbnail": "https://images.example/colosseum.jpg",
                        "rating": 4.7,
                        "reviews": 155000,
                        "categories": ["Historic Sites", "Ancient Ruins"],
                    }
                ]
            },
            "nearby": {
                "restaurants": [
                    {
                        "name": "Roman Table",
                        "place_id": "restaurant-7",
                        "rating": 4.6,
                        "distance": "0.2 mi",
                        "cuisines": ["Italian", "Roman"],
                    }
                ]
            },
        },
    }


def reviews_payload():
    return {
        "search_metadata": {
            "status": "Success",
            "tripadvisor_reviews_url": "https://www.tripadvisor.com/187791",
        },
        "search_information": {"total_reviews": 47},
        "reviews": [
            {
                "position": 1,
                "title": "Wonderful history and food",
                "snippet": "We loved walking the old streets and finding neighborhood restaurants.",
                "rating": 5,
                "review_id": "review-1",
                "link": "https://www.tripadvisor.com/ShowUserReviews-r1.html",
                "date": "2026-07-20",
                "language": "en",
                "original_language": "en",
                "trip_info": {"date": "2026-07", "type": "FAMILY"},
                "author": {
                    "username": "traveler7",
                    "display_name": "Traveler Seven",
                    "avatar": "https://images.example/avatar.jpg",
                    "hometown": "Portland, Oregon",
                },
            }
        ],
    }


def test_things_to_do_preserves_official_uppercase_category_code():
    assert normalize_category("things to do") == ("things_to_do", "A")


def test_search_result_normalization_preserves_drilldown_fields():
    results = extract_tripadvisor_search_results(search_payload())
    assert results[0]["place_id"] == "187791"
    assert results[0]["place_type"] == "GEO"
    assert results[1]["rating"] == 4.8
    assert results[1]["highlighted_review"]["mention_count"] == 1160


def test_place_normalization_collects_bounded_interesting_places():
    place, interesting = extract_tripadvisor_place(detail_payload(), "187791")
    assert place["title"] == "Rome, Italy"
    assert place["thumbnail"] == "https://images.example/rome-detail.jpg"
    assert place["travel_advice"][0]["title"] == "Best time to visit"
    assert [item["title"] for item in interesting] == ["Colosseum", "Roman Table"]
    assert interesting[1]["categories"] == ["Italian", "Roman"]


def test_interesting_places_deduplicate_place_ids_across_sections():
    place = detail_payload()["place_result"]
    place["nearby"]["attractions"] = [
        {"name": "Colosseum duplicate", "place_id": "192285"}
    ]
    interesting = extract_interesting_places(place)
    assert [item["place_id"] for item in interesting].count("192285") == 1


def test_review_normalization_preserves_author_and_trip_context():
    review = extract_tripadvisor_reviews(reviews_payload())[0]
    assert review["author_name"] == "Traveler Seven"
    assert review["trip_type"] == "FAMILY"
    assert review["text"].startswith("We loved")


def test_search_action_uses_tripadvisor_engine_and_returns_place_ids():
    exit_code, result, request = run_main(
        {"query": "Rome", "category": "things_to_do", "num_results": 2},
        search_payload(),
    )
    params = request.call_args.args[0]
    assert exit_code == 0
    assert result["ok"] is True
    assert params["engine"] == "tripadvisor"
    assert params["ssrc"] == "A"
    assert params["limit"] == 2
    assert result["data"]["place_id"] == "187791"
    assert result["data"]["serpapi_searches_used"] == 1


def test_search_can_enrich_top_result_with_details_and_reviews():
    exit_code, result, request = run_main(
        {
            "query": "Rome",
            "include_details": True,
            "include_reviews": True,
            "review_limit": 1,
        },
        [search_payload(), detail_payload(), reviews_payload()],
    )
    engines = [call.args[0]["engine"] for call in request.call_args_list]
    assert exit_code == 0
    assert engines == ["tripadvisor", "tripadvisor_place", "tripadvisor_reviews"]
    assert result["data"]["serpapi_searches_used"] == 3
    assert result["data"]["detail_data"]["place"]["title"] == "Rome, Italy"
    assert result["data"]["review_data"]["reviews"][0]["author_name"] == "Traveler Seven"


def test_search_extra_params_do_not_leak_into_enrichment_engines():
    exit_code, _result, request = run_main(
        {
            "query": "Rome",
            "include_details": True,
            "include_reviews": True,
            "extra_params": {"custom_search_option": "search-only"},
        },
        [search_payload(), detail_payload(), reviews_payload()],
    )
    search_params, detail_params, review_params = [
        call.args[0] for call in request.call_args_list
    ]
    assert exit_code == 0
    assert search_params["custom_search_option"] == "search-only"
    assert "custom_search_option" not in detail_params
    assert "custom_search_option" not in review_params


def test_search_preserves_primary_results_when_optional_enrichment_fails():
    exit_code, result, _request = run_main(
        {"query": "Rome", "include_details": True},
        [search_payload(), TimeoutError("timed out")],
    )
    assert exit_code == 0
    assert result["ok"] is True
    assert result["data"]["results_count"] == 2
    assert "timed out" in result["data"]["enrichment_errors"]["details"]
    assert result["data"]["serpapi_searches_used"] == 1


def test_details_action_requires_place_id_without_making_request():
    exit_code, result, request = run_main({"action": "details"}, {})
    assert exit_code == 1
    assert "place_id" in result["error"]
    request.assert_not_called()


def test_details_action_exposes_nearby_suggestions_as_results():
    exit_code, result, request = run_main(
        {"action": "details", "place_id": "187791"},
        detail_payload(),
    )
    assert exit_code == 0
    assert request.call_args.args[0]["engine"] == "tripadvisor_place"
    assert result["data"]["action"] == "details"
    assert result["data"]["interesting_places_count"] == 2
    assert result["data"]["results"][0]["title"] == "Rome, Italy"


def test_reviews_action_serializes_supported_filters_and_caps_limit():
    exit_code, result, request = run_main(
        {
            "action": "reviews",
            "place_id": "187791",
            "review_limit": 99,
            "rating": [5, 3],
            "month": "1,12",
            "type_of_visit": ["Family", "Solo"],
            "original_language": "en,fr",
            "translate": True,
            "language": "en",
        },
        reviews_payload(),
    )
    params = request.call_args.args[0]
    assert exit_code == 0
    assert params["engine"] == "tripadvisor_reviews"
    assert params["limit"] == 20
    assert params["rating"] == "5,3"
    assert params["month"] == "1,12"
    assert params["type_of_visit"] == "Family,Solo"
    assert params["original_language"] == "en,fr"
    assert params["translate"] == "true"
    assert result["data"]["total_reviews"] == 47


def test_shared_request_is_proxy_capable_but_manifest_defaults_off():
    with patch("serpapi_tripadvisor.request_serpapi", return_value={}) as request:
        _tripadvisor_request({"engine": "tripadvisor", "q": "Rome"})
    assert request.call_args.kwargs == {
        "timeout": SERPAPI_TIMEOUT,
        "use_proxy": True,
        "fallback_on_proxy_fail": True,
    }
    manifest = json.loads((ROOT / "skills" / "serpapi_tripadvisor.tool.json").read_text())
    assert manifest["proxy_policy"] == "off"


def test_status_diagnostics_select_engine_from_action_and_enrichment_flags():
    assert serpapi_client.serpapi_engines_for_tool(
        "serpapi_tripadvisor", {"action": "details"}
    ) == ("tripadvisor_place",)
    assert serpapi_client.serpapi_engines_for_tool(
        "serpapi_tripadvisor",
        {"action": "search", "include_details": True, "include_reviews": True},
    ) == ("tripadvisor", "tripadvisor_place", "tripadvisor_reviews")
