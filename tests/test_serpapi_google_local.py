#!/usr/bin/env python3
"""Regression coverage for the dedicated SerpApi Google Local tool."""

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
from serpapi_google_local import (
    GOOGLE_LOCAL_TIMEOUT,
    _google_local_request,
    main,
    normalize_discover_more,
    normalize_places,
)


def local_payload():
    return {
        "search_metadata": {
            "id": "google-local-123",
            "status": "Success",
            "cached": True,
            "google_local_url": "https://www.google.com/search?q=coffee&tbm=lcl",
        },
        "search_parameters": {
            "engine": "google_local",
            "q": "coffee",
            "location_requested": "Portland, Oregon, United States",
            "location_used": "Portland,Oregon,United States",
        },
        "local_map": {"image": "https://images.example/local-map.png"},
        "local_results": [
            {
                "position": 1,
                "title": "North Star Coffee",
                "rating": 4.8,
                "reviews_original": "(321)",
                "reviews": 321,
                "price": "$$",
                "type": "Coffee shop",
                "address": "123 Market St",
                "hours": "Open until 8 PM",
                "description": "Independent neighborhood coffee shop",
                "place_id": "15667002398697190332",
                "provider_id": "provider-1",
                "thumbnail": "https://images.example/coffee-small.jpg",
                "thumbnail_large": "https://images.example/coffee-large.jpg",
                "gps_coordinates": {"latitude": 45.52, "longitude": -122.68},
                "extensions": ["Dine-in", "Takeout"],
                "links": {
                    "website": "https://northstar.example/",
                    "directions": "https://maps.google.com/north-star",
                    "phone": "tel:+15035550101",
                    "unexpected": "https://secret.example/ignore",
                },
                "service_options": {
                    "dine_in": True,
                    "takeout": True,
                    "no_delivery": False,
                },
            },
            {
                "position": 2,
                "title": "River Coffee",
                "place_id": "8277114589593241915",
                "place_id_search": "https://serpapi.com/search.json?engine=google_local&ludocid=8277114589593241915",
                "address": "8 River Rd",
            },
        ],
        "ads_results": [
            {
                "position": 1,
                "ad_title": "Fresh coffee all day",
                "displayed_link": "sponsor.example",
                "title": "Sponsored Coffee",
                "rating": 4.1,
                "reviews": 70,
                "address": "5 Ad Ave",
                "place_id": "14482539134301609407",
                "place_id_search": "https://serpapi.com/search.json?engine=google_local&ludocid=14482539134301609407",
            }
        ],
        "discover_more_places": [
            {
                "title": "Best coffee",
                "link": "https://www.google.com/search?q=best+coffee&tbm=lcl",
                "serpapi_link": "https://serpapi.com/search.json?api_key=do-not-keep",
                "thumbnail": "https://images.example/best.jpg",
                "places": ["North Star Coffee", "River Coffee"],
            }
        ],
        "serpapi_pagination": {
            "current": 1,
            "next": "https://serpapi.com/search.json?engine=google_local&q=coffee&start=20",
        },
    }


def run_main(arguments, response, config=None):
    stdout = StringIO()
    argv = ["serpapi_google_local.py", json.dumps(arguments)]
    values = config or {}
    config_lookup = lambda key, default="": values.get(key, default)
    with patch("serpapi_google_local.load_config"), patch(
        "serpapi_google_local.get_config_value", side_effect=config_lookup
    ), patch(
        "serpapi_google_local._google_local_request",
        side_effect=response if isinstance(response, Exception) else None,
        return_value=None if isinstance(response, Exception) else response,
    ) as request, patch.object(sys, "argv", argv), redirect_stdout(stdout):
        exit_code = main()
    return exit_code, json.loads(stdout.getvalue()), request


def test_place_normalization_preserves_local_actions_and_labels_ads():
    results, provider_count = normalize_places(
        local_payload()["local_results"], limit=2, sponsored=False
    )
    ads, provider_ads_count = normalize_places(
        local_payload()["ads_results"], limit=3, sponsored=True
    )

    assert provider_count == 2
    assert results[0]["url"] == "https://northstar.example/"
    assert results[0]["google_maps_url"] == (
        "https://www.google.com/maps?cid=15667002398697190332"
    )
    assert results[0]["thumbnail"] == "https://images.example/coffee-large.jpg"
    assert results[0]["links"] == {
        "website": "https://northstar.example/",
        "directions": "https://maps.google.com/north-star",
        "phone": "tel:+15035550101",
    }
    assert results[0]["service_options"] == {
        "dine_in": True,
        "takeout": True,
        "no_delivery": False,
    }
    assert results[0]["sponsored"] is False
    assert results[1]["url"] == (
        "https://www.google.com/maps?cid=8277114589593241915"
    )
    assert provider_ads_count == 1
    assert ads[0]["sponsored"] is True
    assert ads[0]["ad_title"] == "Fresh coffee all day"


def test_discover_more_keeps_public_google_link_not_serpapi_link():
    results, provider_count = normalize_discover_more(
        local_payload()["discover_more_places"], limit=5
    )

    assert provider_count == 1
    assert results[0]["url"].startswith("https://www.google.com/")
    assert "api_key" not in json.dumps(results)
    assert results[0]["places"] == ["North Star Coffee", "River Coffee"]


def test_explicit_location_uses_documented_parameters_and_normalizes_payload():
    exit_code, result, request = run_main(
        {
            "query": "coffee",
            "location": "Portland, Oregon, United States",
            "country": "us",
            "language": "en",
            "google_domain": "google.com",
            "place_id": "15667002398697190332",
            "tbs": "lf:1",
            "device": "mobile",
            "start": 20,
            "max_results": 1,
            "max_ads": 1,
            "max_discover_more": 1,
            "no_cache": True,
        },
        local_payload(),
    )

    assert exit_code == 0
    assert result["ok"] is True
    assert request.call_args.args[0] == {
        "engine": "google_local",
        "q": "coffee",
        "google_domain": "google.com",
        "start": 20,
        "device": "mobile",
        "no_cache": "true",
        "location": "Portland, Oregon, United States",
        "gl": "us",
        "hl": "en",
        "ludocid": "15667002398697190332",
        "tbs": "lf:1",
    }
    data = result["data"]
    assert data["location_source"] == "explicit"
    assert data["provider_location_used"] == "Portland,Oregon,United States"
    assert data["results_count"] == 1
    assert data["provider_results_count"] == 2
    assert data["ads_count"] == 1
    assert data["discover_more_count"] == 1
    assert data["next_start"] == 20
    assert data["top_url"] == "https://northstar.example/"
    assert data["local_map_image"] == "https://images.example/local-map.png"
    assert "api_key" not in json.dumps(data["pagination"])


def test_default_location_precedes_default_postal_code():
    exit_code, result, request = run_main(
        {"query": "plumber"},
        local_payload(),
        {
            "JARVIS_DEFAULT_LOCATION": "Hillsboro, Oregon",
            "JARVIS_DEFAULT_POSTAL_CODE": "97124",
        },
    )

    assert exit_code == 0
    assert request.call_args.args[0]["location"] == "Hillsboro, Oregon"
    assert result["data"]["location"] == "Hillsboro, Oregon"
    assert result["data"]["location_source"] == "jarvis_default_location"


def test_default_postal_code_is_used_when_default_location_is_blank():
    exit_code, result, request = run_main(
        {"query": "pharmacy"},
        local_payload(),
        {"JARVIS_DEFAULT_LOCATION": "", "JARVIS_DEFAULT_POSTAL_CODE": "97124"},
    )

    assert exit_code == 0
    assert request.call_args.args[0]["location"] == "97124"
    assert result["data"]["location_source"] == "jarvis_default_postal_code"


def test_explicit_uule_bypasses_mode_defaults():
    exit_code, result, request = run_main(
        {"query": "pizza", "uule": "w+CAIQICImU2FuIEZyYW5jaXNjby"},
        local_payload(),
        {
            "JARVIS_DEFAULT_LOCATION": "Hillsboro, Oregon",
            "JARVIS_DEFAULT_POSTAL_CODE": "97124",
        },
    )

    assert exit_code == 0
    params = request.call_args.args[0]
    assert params["uule"].startswith("w+CAIQ")
    assert "location" not in params
    assert result["data"]["location_source"] == "explicit_uule"
    assert result["data"]["uule_used"] is True


def test_missing_and_conflicting_locations_fail_before_network():
    exit_code, result, request = run_main({"query": "coffee"}, local_payload())
    assert exit_code == 1
    assert "JARVIS_DEFAULT_LOCATION" in result["error"]
    request.assert_not_called()

    exit_code, result, request = run_main(
        {"query": "coffee", "location": "Portland", "uule": "encoded"},
        local_payload(),
    )
    assert exit_code == 1
    assert "cannot" in result["error"]
    request.assert_not_called()


def test_invalid_inputs_and_reserved_extra_params_are_handled():
    cases = (
        ({"query": "coffee", "location": "Portland", "country": "usa"}, "two-letter"),
        ({"query": "coffee", "location": "Portland", "device": "watch"}, "device"),
        ({"query": "coffee", "location": "Portland", "place_id": "cid-7"}, "numeric"),
        ({"query": "coffee", "location": "Portland", "start": -1}, "start"),
        ({"query": "coffee", "location": "Portland", "extra_params": []}, "object"),
    )
    for arguments, expected in cases:
        exit_code, result, request = run_main(arguments, local_payload())
        assert exit_code == 1
        assert expected in result["error"]
        request.assert_not_called()

    exit_code, _result, request = run_main(
        {
            "query": "coffee",
            "location": "Portland",
            "extra_params": {
                "custom_option": "enabled",
                "engine": "google",
                "q": "override",
                "async": "true",
                "location": "Seattle",
            },
        },
        local_payload(),
    )
    params = request.call_args.args[0]
    assert exit_code == 0
    assert params["engine"] == "google_local"
    assert params["q"] == "coffee"
    assert params["location"] == "Portland"
    assert params["custom_option"] == "enabled"
    assert "async" not in params


def test_raw_is_opt_in_empty_results_succeed_and_timeout_is_specific():
    empty = {"local_results": [], "ads_results": [], "discover_more_places": []}
    exit_code, result, _request = run_main(
        {"query": "unlikely", "location": "Portland", "include_raw": True}, empty
    )
    assert exit_code == 0
    assert result["data"]["raw"] == empty
    assert "no places" in result["speech"]

    exit_code, result, _request = run_main(
        {"query": "coffee", "location": "Portland"}, TimeoutError("timed out")
    )
    assert exit_code == 1
    assert result["error"] == "SerpApi Google Local request timed out."


def test_shared_request_is_proxy_capable_manifest_defaults_off_and_status_is_registered():
    with patch("serpapi_google_local.request_serpapi", return_value={}) as request:
        _google_local_request({"engine": "google_local", "q": "coffee"})
    assert request.call_args.kwargs == {
        "timeout": GOOGLE_LOCAL_TIMEOUT,
        "use_proxy": True,
        "fallback_on_proxy_fail": True,
    }
    manifest = json.loads(
        (ROOT / "skills" / "serpapi_google_local.tool.json").read_text()
    )
    assert manifest["proxy_policy"] == "off"
    assert manifest["availability"]["all_of_env"] == ["SERP_API_KEY"]
    assert serpapi_client.serpapi_engines_for_tool(
        "serpapi_google_local", {"query": "coffee"}
    ) == ("google_local",)
