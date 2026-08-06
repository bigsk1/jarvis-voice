#!/usr/bin/env python3
"""Regression coverage for the SerpApi Google Local Services tool."""

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
from serpapi_google_local_services import (
    GOOGLE_LOCAL_SERVICES_TIMEOUT,
    _serpapi_request,
    common_location_cid,
    main,
    normalize_provider,
    normalize_service_query,
)


def search_payload():
    return {
        "search_metadata": {
            "id": "local-services-123",
            "status": "Success",
            "cached": True,
        },
        "search_information": {
            "google_local_services_url": "https://www.google.com/localservices/prolist?scp=public"
        },
        "local_ads": [
            {
                "title": "North Star Electric",
                "link": "https://www.google.com/localservices/profile?north-star",
                "rating": 4.9,
                "reviews": 321,
                "phone": "+15035550101",
                "badge": "GOOGLE GUARANTEED",
                "type": "Electrician",
                "service_area": "Portland",
                "years_in_business": 12,
                "bookings_nearby": 8,
                "thumbnail": "https://images.example/electrician.jpg",
                "hours": {
                    "currently": "Open 24 hours",
                    "week": [{"monday": "Open 24 hours"}],
                },
                "cid": "327189293",
                "bid": "2517727928",
                "pid": "2521525020",
                "serpapi_link": "https://serpapi.com/search.json?api_key=do-not-keep",
            },
            {
                "title": "River City Electric",
                "service_area": "Portland",
                "cid": "1226868474",
                "bid": "3480172827",
                "pid": "9999999999",
            },
        ],
    }


def maps_payload(*, country="United States", data_cid="112233445566"):
    return {
        "search_metadata": {"id": "maps-resolver-123", "status": "Success"},
        "place_results": {
            "title": "Phoenix",
            "address": "Phoenix, Arizona, United States",
            "country": country,
            "data_cid": data_cid,
        },
    }


def detail_payload():
    return {
        "search_metadata": {"id": "local-services-detail-123", "status": "Success"},
        "local_place": {
            "title": "North Star Electric",
            "rating": 4.9,
            "reviews": 321,
            "rating_stars": [{"stars": 5, "amount": 300}],
            "address": "123 Main St",
            "phone": "+15035550101",
            "website": "https://northstar.example/",
            "badge": "GOOGLE GUARANTEED",
            "type": "Electrical",
            "checks": ["Oregon contractor license 123"],
            "description": ["24/7 emergency service", "Free consultation"],
            "services": ["Restore power", "Repair panel"],
            "service_area": "Portland",
            "years_in_business": 12,
            "images": ["https://images.example/detail.jpg"],
            "hours": {
                "currently": "Open",
                "week": [{"monday": "Open 24 hours"}],
            },
        },
    }


def run_main(arguments, responses, config=None):
    stdout = StringIO()
    argv = ["serpapi_google_local_services.py", json.dumps(arguments)]
    values = config or {}
    config_lookup = lambda key, default="": values.get(key, default)
    side_effect = responses if isinstance(responses, (list, Exception)) else None
    return_value = None if side_effect is not None else responses
    with patch("serpapi_google_local_services.load_config"), patch(
        "serpapi_google_local_services.get_config_value", side_effect=config_lookup
    ), patch(
        "serpapi_google_local_services._serpapi_request",
        side_effect=side_effect,
        return_value=return_value,
    ) as request, patch.object(sys, "argv", argv), redirect_stdout(stdout):
        exit_code = main()
    return exit_code, json.loads(stdout.getvalue()), request


def test_common_location_aliases_are_local_and_do_not_consume_resolver_search():
    assert common_location_cid("New York, NY, USA")[0] == "14414772292044717666"
    assert common_location_cid("Austin, Texas, United States")[0] == "6745062158417646970"
    assert common_location_cid("Portland, Oregon")[0] == "2033016683438900625"
    assert common_location_cid("97201")[0] == "2033016683438900625"

    exit_code, result, request = run_main(
        {"query": "electrician"},
        search_payload(),
        {
            "JARVIS_DEFAULT_LOCATION": "Portland, Oregon",
            "JARVIS_DEFAULT_POSTAL_CODE": "97201",
        },
    )

    assert exit_code == 0
    assert request.call_count == 1
    assert request.call_args.args[0]["engine"] == "google_local_services"
    assert request.call_args.args[0]["data_cid"] == "2033016683438900625"
    data = result["data"]
    assert data["data_cid_source"] == "common_location"
    assert data["location_source"] == "jarvis_default_location"
    assert data["resolved_location"] == "Portland, Oregon"
    assert data["serpapi_searches_used"] == 1


def test_unknown_location_uses_bounded_google_maps_resolver_then_local_services():
    exit_code, result, request = run_main(
        {
            "query": "plumber",
            "location": "Phoenix, Arizona",
            "language": "es",
            "job_type": "repair_pipe",
            "max_results": 1,
            "no_cache": True,
        },
        [maps_payload(), search_payload()],
    )

    assert exit_code == 0
    assert request.call_count == 2
    resolver = request.call_args_list[0].args[0]
    provider = request.call_args_list[1].args[0]
    assert resolver == {
        "engine": "google_maps",
        "type": "search",
        "q": "Phoenix, Arizona",
        "hl": "es",
        "no_cache": "true",
    }
    assert provider["engine"] == "google_local_services"
    assert provider["data_cid"] == "112233445566"
    assert provider["job_type"] == "repair_pipe"
    data = result["data"]
    assert data["resolved_location"] == "Phoenix"
    assert data["data_cid_source"] == "google_maps_resolver"
    assert data["serpapi_searches_used"] == 2
    assert data["resolver_search_metadata"]["id"] == "maps-resolver-123"
    assert data["results_count"] == 1
    assert data["provider_results_count"] == 2


def test_natural_car_repair_query_uses_provider_slug_after_default_location_resolution():
    exit_code, result, request = run_main(
        {"query": "car repair shop", "max_results": 10},
        [maps_payload(), search_payload()],
        {
            "JARVIS_DEFAULT_LOCATION": "Phoenix, Arizona",
            "JARVIS_DEFAULT_POSTAL_CODE": "85001",
        },
    )

    assert exit_code == 0
    assert request.call_count == 2
    resolver = request.call_args_list[0].args[0]
    provider = request.call_args_list[1].args[0]
    assert resolver["engine"] == "google_maps"
    assert resolver["q"] == "Phoenix, Arizona"
    assert provider["engine"] == "google_local_services"
    assert provider["q"] == "auto_repair_shop"
    assert provider["data_cid"] == "112233445566"
    data = result["data"]
    assert data["query"] == "car repair shop"
    assert data["provider_query"] == "auto_repair_shop"
    assert data["location_source"] == "jarvis_default_location"
    assert data["serpapi_searches_used"] == 2


def test_query_normalization_accepts_supported_phrases_and_rejects_unknown_categories():
    assert normalize_service_query("AC repair") == ("AC repair", "hvac")
    assert normalize_service_query("air conditioning repair") == (
        "air conditioning repair",
        "hvac",
    )
    assert normalize_service_query("Auto Repair Shop") == (
        "Auto Repair Shop",
        "auto_repair_shop",
    )
    assert normalize_service_query("mechanic") == ("mechanic", "auto_repair_shop")
    assert normalize_service_query("house cleaner") == (
        "house cleaner",
        "cleaning_service",
    )
    assert normalize_service_query("electricians") == (
        "electricians",
        "electrician",
    )

    exit_code, result, request = run_main(
        {"query": "restaurant", "location": "Phoenix, Arizona"},
        [maps_payload(), search_payload()],
    )
    assert exit_code == 1
    assert "Unsupported Google Local Services query" in result["error"]
    assert "serpapi_google_local" in result["error"]
    request.assert_not_called()


def test_explicit_data_cid_uses_one_search_without_requiring_location():
    exit_code, result, request = run_main(
        {
            "query": "house cleaner",
            "data_cid": "14414772292044717666",
            "extra_params": {
                "custom_option": "enabled",
                "engine": "google",
                "data_cid": "999",
                "async": "true",
            },
        },
        search_payload(),
    )

    assert exit_code == 0
    assert request.call_count == 1
    params = request.call_args.args[0]
    assert params["engine"] == "google_local_services"
    assert params["q"] == "cleaning_service"
    assert params["data_cid"] == "14414772292044717666"
    assert params["custom_option"] == "enabled"
    assert "async" not in params
    assert result["data"]["data_cid_source"] == "explicit"
    assert result["data"]["serpapi_searches_used"] == 1


def test_search_normalization_preserves_followup_ids_and_public_links_only():
    exit_code, result, _request = run_main(
        {"query": "electrician", "location": "Austin, Texas"},
        search_payload(),
    )

    assert exit_code == 0
    data = result["data"]
    top = data["results"][0]
    assert top["url"].startswith("https://www.google.com/localservices/profile")
    assert top["badge"] == "GOOGLE GUARANTEED"
    assert top["hours_current"] == "Open 24 hours"
    assert top["hours_week"] == [{"monday": "Open 24 hours"}]
    assert (top["cid"], top["bid"], top["pid"]) == (
        "327189293",
        "2517727928",
        "2521525020",
    )
    assert data["google_local_services_url"].startswith(
        "https://www.google.com/localservices/"
    )
    assert "serpapi_link" not in json.dumps(data)
    assert "api_key" not in json.dumps(data)


def test_focused_provider_requires_all_ids_and_normalizes_local_place():
    ids = {"cid": "327189293", "bid": "2517727928", "pid": "2521525020"}
    exit_code, result, request = run_main(
        {
            "query": "electrician",
            "data_cid": "6745062158417646970",
            **ids,
        },
        detail_payload(),
    )

    assert exit_code == 0
    assert request.call_args.args[0] == {
        "engine": "google_local_services",
        "q": "electrician",
        "data_cid": "6745062158417646970",
        "hl": "en",
        "no_cache": "false",
        **ids,
    }
    data = result["data"]
    assert data["mode"] == "provider_details"
    assert data["detail"]["website"] == "https://northstar.example/"
    assert data["detail"]["services"] == ["Restore power", "Repair panel"]
    assert data["detail"]["checks"] == ["Oregon contractor license 123"]
    assert data["detail"]["cid"] == ids["cid"]

    exit_code, result, request = run_main(
        {"query": "electrician", "data_cid": "123", "cid": "7"},
        detail_payload(),
    )
    assert exit_code == 1
    assert "supplied together" in result["error"]
    request.assert_not_called()


def test_invalid_or_non_us_resolution_fails_before_local_services_call():
    cases = (
        ({"query": "plumber", "data_cid": "cid-7"}, "numeric"),
        ({"query": "plumber", "data_cid": "123", "language": "eng"}, "two-letter"),
        ({"query": "plumber", "data_cid": "123", "max_results": 21}, "max_results"),
        ({"query": "plumber", "data_cid": "123", "extra_params": []}, "object"),
    )
    for arguments, expected in cases:
        exit_code, result, request = run_main(arguments, search_payload())
        assert exit_code == 1
        assert expected in result["error"]
        request.assert_not_called()

    exit_code, result, request = run_main(
        {"query": "plumber", "location": "Vancouver, British Columbia"},
        [maps_payload(country="Canada")],
    )
    assert exit_code == 1
    assert "only in the United States" in result["error"]
    assert request.call_count == 1


def test_raw_is_opt_in_empty_results_succeed_and_timeout_is_specific():
    empty = {"local_ads": []}
    exit_code, result, _request = run_main(
        {
            "query": "plumber",
            "data_cid": "123",
            "include_raw": True,
        },
        empty,
    )
    assert exit_code == 0
    assert result["data"]["raw"] == empty
    assert "no providers" in result["speech"]

    exit_code, result, _request = run_main(
        {"query": "plumber", "data_cid": "123"},
        TimeoutError("timed out"),
    )
    assert exit_code == 1
    assert result["error"] == "SerpApi Google Local Services request timed out."


def test_shared_request_is_proxy_capable_manifest_defaults_off_and_status_is_registered():
    with patch("serpapi_google_local_services.request_serpapi", return_value={}) as request:
        _serpapi_request({"engine": "google_local_services", "q": "plumber"})
    assert request.call_args.kwargs == {
        "timeout": GOOGLE_LOCAL_SERVICES_TIMEOUT,
        "use_proxy": True,
        "fallback_on_proxy_fail": True,
    }
    manifest = json.loads(
        (ROOT / "skills" / "serpapi_google_local_services.tool.json").read_text()
    )
    assert manifest["proxy_policy"] == "off"
    assert manifest["availability"]["all_of_env"] == ["SERP_API_KEY"]
    assert serpapi_client.serpapi_engines_for_tool(
        "serpapi_google_local_services", {"data_cid": "123"}
    ) == ("google_local_services",)
    assert serpapi_client.serpapi_engines_for_tool(
        "serpapi_google_local_services", {"location": "Phoenix"}
    ) == ("google_maps", "google_local_services")


def test_detail_normalization_bounds_provider_lists():
    normalized = normalize_provider(
        {
            "title": "Provider",
            "description": [f"detail-{index}" for index in range(20)],
            "services": [f"service-{index}" for index in range(40)],
            "images": [f"https://images.example/{index}.jpg" for index in range(12)],
        },
        position=1,
    )
    assert len(normalized["description"]) == 12
    assert len(normalized["services"]) == 30
    assert len(normalized["images"]) == 8
