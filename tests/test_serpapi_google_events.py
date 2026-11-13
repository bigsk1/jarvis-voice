#!/usr/bin/env python3
"""Regression coverage for the dedicated SerpApi Google Events tool."""

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
from serpapi_google_events import (
    GOOGLE_EVENTS_TIMEOUT,
    _google_events_request,
    main,
    normalize_events,
)


def events_payload():
    return {
        "search_metadata": {
            "id": "google-events-123",
            "status": "Success",
            "cached": True,
            "google_events_url": "https://www.google.com/search?q=live+music+in+Portland",
            "json_endpoint": "https://serpapi.com/searches/private.json",
        },
        "search_parameters": {
            "engine": "google_events",
            "q": "live music in Portland, Oregon",
        },
        "search_information": {"events_results_state": "Results for exact spelling"},
        "events_results": [
            {
                "title": "Waterfront Jazz Night",
                "date": {"start_date": "Aug 14", "when": "Fri, Aug 14, 7:30 PM PDT"},
                "type": "Concert",
                "address": ["Waterfront Park", "Portland, OR"],
                "link": "https://events.example/waterfront-jazz",
                "description": "An outdoor summer jazz concert.",
                "ticket_info": [
                    {
                        "source": "Tickets Example",
                        "link": "https://tickets.example/jazz",
                        "link_type": "tickets",
                        "price": "$25",
                    }
                ],
                "venue": {
                    "name": "Waterfront Park",
                    "rating": 4.7,
                    "reviews": 1250,
                    "link": "https://www.google.com/search?q=Waterfront+Park",
                },
                "event_location_map": {
                    "image": "https://images.example/map.png",
                    "link": "https://www.google.com/maps/place/Waterfront+Park",
                    "serpapi_link": "https://serpapi.com/search.json?api_key=do-not-keep",
                },
                "thumbnail": "https://images.example/jazz-small.jpg",
                "image": "https://images.example/jazz.jpg",
                "event_token": "opaque-event-handle-123",
                "serpapi_event_details_link": "https://serpapi.com/search.json?engine=google_event_details&api_key=do-not-keep",
            },
            {
                "title": "Community Market",
                "date": "Saturday, 10 AM",
                "venue": "Eastside Plaza",
                "ticket_info": {
                    "source": "Market site",
                    "link": "https://market.example/details",
                    "link_type": "more info",
                },
            },
        ],
        "serpapi_pagination": {
            "current": 1,
            "next": "https://serpapi.com/search.json?engine=google_events&start=10",
        },
    }


def run_main(arguments, response, config=None):
    stdout = StringIO()
    argv = ["serpapi_google_events.py", json.dumps(arguments)]
    values = config or {}
    config_lookup = lambda key, default="": values.get(key, default)
    with patch("serpapi_google_events.load_config"), patch(
        "serpapi_google_events.get_config_value", side_effect=config_lookup
    ), patch(
        "serpapi_google_events._google_events_request",
        side_effect=response if isinstance(response, Exception) else None,
        return_value=None if isinstance(response, Exception) else response,
    ) as request, patch.object(sys, "argv", argv), redirect_stdout(stdout):
        exit_code = main()
    return exit_code, json.loads(stdout.getvalue()), request


def test_normalization_keeps_public_event_ticket_venue_and_map_fields():
    events, provider_count = normalize_events(events_payload()["events_results"], limit=2)

    assert provider_count == 2
    assert events[0]["url"] == "https://events.example/waterfront-jazz"
    assert events[0]["start_date"] == "Aug 14"
    assert events[0]["address_text"] == "Waterfront Park, Portland, OR"
    assert events[0]["venue"]["name"] == "Waterfront Park"
    assert events[0]["ticket_info"][0]["link"] == "https://tickets.example/jazz"
    assert events[0]["event_location_map"] == {
        "image": "https://images.example/map.png",
        "link": "https://www.google.com/maps/place/Waterfront+Park",
    }
    assert "serpapi_link" not in json.dumps(events)
    assert events[0]["event_token"] == "opaque-event-handle-123"
    assert "serpapi_event_details_link" not in json.dumps(events)
    assert events[1]["venue"] == {"name": "Eastside Plaza"}
    assert events[1]["url"] == "https://market.example/details"


def test_date_and_virtual_preferences_use_query_wording_without_removed_filter_chips():
    exit_code, result, request = run_main(
        {
            "query": "live music",
            "location": "Portland, Oregon",
            "date_filter": "week",
            "virtual": True,
            "country": "us",
            "language": "en",
            "start": 0,
            "max_results": 1,
            "no_cache": True,
        },
        events_payload(),
    )

    assert exit_code == 0
    assert result["ok"] is True
    assert request.call_args.args[0] == {
        "engine": "google_events",
        "q": "virtual live music in Portland, Oregon this week",
        "no_cache": "true",
        "location": "Portland, Oregon",
    }
    data = result["data"]
    assert data["effective_query"] == "virtual live music in Portland, Oregon this week"
    assert data["query_preferences"] == {"date_filter": "week", "virtual": True}
    assert "not strict filters" in data["query_preferences_note"]
    assert "not strict filters" in result["speech"]
    assert data["country"] == "us" and data["language"] == "en"
    assert data["location_source"] == "explicit"
    assert data["results_count"] == 1
    assert data["provider_results_count"] == 2
    assert data["pagination_supported"] is False
    assert not {"filters", "date_filter", "virtual", "start", "next_start", "has_more", "pagination"} & data.keys()
    assert data["external_content_trust"] == "untrusted"
    assert data["google_events_url"].startswith("https://www.google.com/")
    assert "json_endpoint" not in json.dumps(data)


def test_default_location_precedes_postal_and_is_added_to_query():
    exit_code, result, request = run_main(
        {"query": "family events"},
        events_payload(),
        {
            "JARVIS_DEFAULT_LOCATION": "Hillsboro, Oregon",
            "JARVIS_DEFAULT_POSTAL_CODE": "97124",
        },
    )

    assert exit_code == 0
    assert request.call_args.args[0]["q"] == "family events in Hillsboro, Oregon"
    assert request.call_args.args[0]["location"] == "Hillsboro, Oregon"
    assert result["data"]["location_source"] == "jarvis_default_location"


def test_embedded_query_is_not_duplicated_and_bare_city_warns():
    exit_code, result, request = run_main(
        {"query": "Events in Portland"},
        events_payload(),
        {"JARVIS_DEFAULT_LOCATION": "Hillsboro, Oregon"},
    )

    assert exit_code == 0
    assert request.call_args.args[0]["q"] == "Events in Portland"
    assert result["data"]["query_location_embedded"] is True
    assert "Portland, Oregon" in result["data"]["location_ambiguity_warning"]
    assert "Portland, Maine" in result["data"]["location_ambiguity_warning"]


def test_bare_explicit_city_warns_but_does_not_fail():
    exit_code, result, request = run_main(
        {"query": "events", "location": "Portland"}, events_payload()
    )

    assert exit_code == 0
    assert request.call_args.args[0]["q"] == "events in Portland"
    assert "most popular match" in result["data"]["location_ambiguity_warning"]


def test_uule_missing_location_invalid_inputs_and_reserved_extra_params():
    exit_code, result, request = run_main(
        {
            "query": "concerts in San Francisco",
            "uule": "w+CAIQICImU2FuIEZyYW5jaXNjby",
            "country": "us",
        },
        events_payload(),
    )
    assert exit_code == 0
    assert "location" not in request.call_args.args[0]
    assert result["data"]["uule_used"] is True

    exit_code, result, request = run_main({"query": "events"}, events_payload())
    assert exit_code == 1
    assert "JARVIS_DEFAULT_LOCATION" in result["error"]
    request.assert_not_called()

    invalid_cases = (
        ({"query": "events", "location": "Portland", "country": "fr"}, "US-English"),
        ({"query": "events", "location": "Portland", "language": "fr"}, "US-English"),
        ({"query": "events", "location": "Portland", "start": 10}, "pagination is not supported"),
        ({"query": "events", "location": "Portland", "date_filter": "weekend"}, "date_filter"),
        ({"query": "events", "location": "Portland", "extra_params": []}, "object"),
    )
    for arguments, expected in invalid_cases:
        exit_code, result, request = run_main(arguments, events_payload())
        assert exit_code == 1
        assert expected in result["error"]
        request.assert_not_called()

    exit_code, _result, request = run_main(
        {
            "query": "events",
            "location": "Portland, Oregon",
            "extra_params": {
                "custom_option": "enabled",
                "engine": "google",
                "q": "override",
                "location": "Seattle",
            },
        },
        events_payload(),
    )
    assert exit_code == 0
    assert request.call_args.args[0]["engine"] == "google_events"
    assert request.call_args.args[0]["q"] == "events in Portland, Oregon"
    assert request.call_args.args[0]["location"] == "Portland, Oregon"
    assert request.call_args.args[0]["custom_option"] == "enabled"
    assert "htichips" not in request.call_args.args[0]

    for retired in ("htichips", "event_type", "start", "gl", "hl"):
        exit_code, result, request = run_main(
            {"query": "events", "location": "Paris, France", "extra_params": {retired: "unsupported"}},
            events_payload(),
        )
        assert exit_code == 1 and "no longer supports" in result["error"]
        request.assert_not_called()


def test_query_preferences_preserve_international_destination_and_deduplicate_existing_words():
    exit_code, result, request = run_main(
        {"query": "online conferences in Paris next week", "location": "Paris, France",
         "date_filter": "next_week", "virtual": True},
        events_payload(),
    )
    assert exit_code == 0
    assert request.call_args.args[0]["q"] == "online conferences in Paris next week"
    assert request.call_args.args[0]["location"] == "Paris, France"
    assert result["data"]["country"] == "us" and result["data"]["language"] == "en"
    assert result["data"]["query_preferences"] == {"date_filter": "next_week", "virtual": True}


def test_raw_empty_timeout_manifest_proxy_and_status_registration():
    empty = {"events_results": []}
    exit_code, result, _request = run_main(
        {"query": "unlikely", "location": "Portland, Oregon", "include_raw": True},
        empty,
    )
    assert exit_code == 0
    assert result["data"]["raw"] == empty
    assert "no events" in result["speech"]

    exit_code, result, _request = run_main(
        {"query": "events", "location": "Portland, Oregon"},
        TimeoutError("timed out"),
    )
    assert exit_code == 1
    assert result["error"] == "SerpApi Google Events request timed out."

    with patch("serpapi_google_events.request_serpapi", return_value={}) as request:
        _google_events_request({"engine": "google_events", "q": "events"})
    assert request.call_args.kwargs == {
        "timeout": GOOGLE_EVENTS_TIMEOUT,
        "use_proxy": True,
        "fallback_on_proxy_fail": True,
    }
    manifest = json.loads(
        (ROOT / "skills" / "serpapi_google_events.tool.json").read_text()
    )
    assert manifest["proxy_policy"] == "off"
    assert manifest["availability"]["all_of_env"] == ["SERP_API_KEY"]
    assert not {"country", "language", "start"} & manifest["parameters"]["properties"].keys()
    assert "not a strict date filter" in manifest["parameters"]["properties"]["date_filter"]["description"]
    assert serpapi_client.serpapi_engines_for_tool(
        "serpapi_google_events", {"query": "events"}
    ) == ("google_events",)
