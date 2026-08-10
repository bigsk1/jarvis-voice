#!/usr/bin/env python3
"""Regression tests for the SerpApi Google Travel Explore tool."""

import json
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

import serpapi_travel_explore as travel_explore  # noqa: E402
from serpapi_client import extract_travel_explore_destinations  # noqa: E402

FUTURE_OUT = "2099-08-11"
FUTURE_BACK = "2099-08-18"

SAMPLE_PAYLOAD = {
    "search_metadata": {
        "id": "explore_123",
        "status": "Success",
        "total_time_taken": 2.4,
        "cached": False,
        "json_endpoint": "https://serpapi.example/explore_123.json",
        "google_travel_explore_url": "https://www.google.com/travel/explore?tfs=search",
    },
    "destinations": [
        {
            "destination_id": "/m/030qb3t",
            "name": "Zion National Park",
            "country": "United States",
            "gps_coordinates": {"latitude": 37.2982, "longitude": -113.0263},
            "thumbnail": "https://images.example/zion.jpg",
            "destination_airport": {
                "code": "LAS",
                "location": "Las Vegas",
                "location_id": "/m/0cv3w",
            },
            "start_date": "2026-10-09",
            "end_date": "2026-10-16",
            "flight_price": 246,
            "hotel_price": 167,
            "flight_duration": 135,
            "number_of_stops": 0,
            "airline": "Alaska",
            "airline_code": "AS",
            "car_duration": 164,
            "link": "https://www.google.com/travel/explore/zion",
            "serpapi_link": "https://serpapi.com/search.json?api_key=secret",
        },
        {
            "destination_id": "/m/030qb3",
            "name": "Las Vegas",
            "country": "United States",
            "destination_airport": {
                "code": "LAS",
                "location": "Las Vegas",
                "location_id": "/m/0cv3w",
            },
            "start_date": "2026-11-02",
            "end_date": "2026-11-09",
            "flight_price": 118,
            "hotel_price": 210,
            "flight_duration": 142,
            "number_of_stops": 1,
            "airline": "Spirit",
            "airline_code": "NK",
            "link": "https://www.google.com/travel/explore/las-vegas",
        },
        {
            "destination_id": "/m/0d6lp",
            "name": "Los Angeles",
            "country": "United States",
            "destination_airport": {
                "code": "LAX",
                "location": "Los Angeles",
                "location_id": "/m/030qb3t",
            },
            "start_date": "2026-09-01",
            "end_date": "2026-09-08",
            "flight_price": 150,
            "hotel_price": 130,
            "flight_duration": 125,
            "number_of_stops": 2,
            "airline": "Delta",
            "airline_code": "DL",
            "link": "https://www.google.com/travel/explore/los-angeles",
        },
        {
            "destination_id": "/m/0empty",
            "name": "Unpriced Island",
            "country": "United States",
            "destination_airport": {"code": "KOA"},
            "start_date": "not-a-date",
            "end_date": "also-not-a-date",
            "number_of_stops": "unknown",
        },
    ],
}


def run_tool(payload_args, *, response=None, capture=None, request_error=None):
    def fake_request(params, timeout=25, **kwargs):
        if capture is not None:
            capture["params"] = dict(params)
            capture["timeout"] = timeout
            capture["calls"] = capture.get("calls", 0) + 1
        if request_error is not None:
            raise request_error
        return response if response is not None else SAMPLE_PAYLOAD

    output = StringIO()
    with patch.object(
        sys,
        "argv",
        ["serpapi_travel_explore.py", json.dumps(payload_args)],
    ), patch(
        "serpapi_travel_explore.load_config"
    ), patch(
        "serpapi_travel_explore.request_serpapi", side_effect=fake_request
    ), patch(
        "serpapi_travel_explore.get_proxy_enabled", return_value=False
    ), redirect_stdout(output):
        exit_code = travel_explore.main()
    return exit_code, json.loads(output.getvalue())


class TravelExploreParameterTests(unittest.TestCase):
    def test_default_is_one_bounded_discovery_search(self):
        capture = {}
        exit_code, result = run_tool({"departure_id": "pdx"}, capture=capture)

        self.assertEqual(exit_code, 0)
        self.assertEqual(capture["calls"], 1)
        self.assertEqual(capture["timeout"], travel_explore.SERPAPI_TIMEOUT)
        self.assertEqual(
            capture["params"],
            {
                "engine": "google_travel_explore",
                "departure_id": "PDX",
                "type": 1,
                "travel_duration": 2,
                "travel_class": 1,
                "adults": 1,
                "children": 0,
                "infants_in_seat": 0,
                "infants_on_lap": 0,
                "stops": 0,
                "bags": 0,
                "currency": "USD",
                "hl": "en",
                "gl": "us",
                "no_cache": "false",
            },
        )
        data = result["data"]
        self.assertEqual(data["planning_stage"], "destination_discovery")
        self.assertEqual(data["date_mode"], "flexible")
        self.assertEqual(data["results_count"], 4)
        self.assertEqual(data["serpapi_searches_used"], 1)
        self.assertTrue(data["price_confirmation_required"])
        self.assertEqual(data["flight_price_basis"], "provider_headline_round_trip_fare")
        self.assertEqual(
            data["hotel_price_basis"],
            "provider_headline_lodging_price_unspecified",
        )
        self.assertNotIn("raw", data)

    def test_filters_map_to_provider_contract(self):
        capture = {}
        with patch(
            "serpapi_travel_explore.now_local",
            return_value=datetime(2026, 8, 9, 12, 0, 0),
        ):
            _, result = run_tool(
                {
                    "departure_id": ["pdx", "/m/0d6lp", "PDX"],
                    "arrival_area_id": "/m/02j9z",
                    "month": 10,
                    "travel_duration": "weekend",
                    "travel_class": "business",
                    "adults": 2,
                    "children": 1,
                    "infants_in_seat": 1,
                    "infants_on_lap": 1,
                    "stops": "nonstop",
                    "interest": "beaches",
                    "include_airlines": "as, oneworld",
                    "bags": 3,
                    "max_price": 700,
                    "max_duration": 600,
                    "currency": "eur",
                    "hl": "fr",
                    "gl": "de",
                    "no_cache": True,
                    "extra_params": {"zero_trace": "true"},
                },
                capture=capture,
            )

        params = capture["params"]
        self.assertEqual(params["departure_id"], "PDX,/m/0d6lp")
        self.assertEqual(params["arrival_area_id"], "/m/02j9z")
        self.assertEqual(params["month"], 10)
        self.assertEqual(params["travel_duration"], 1)
        self.assertEqual(params["travel_class"], 3)
        self.assertEqual(params["stops"], 1)
        self.assertEqual(params["interest"], "/m/0b3yr")
        self.assertEqual(params["include_airlines"], "AS,ONEWORLD")
        self.assertEqual(params["bags"], 3)
        self.assertEqual(params["max_price"], 700)
        self.assertEqual(params["max_duration"], 600)
        self.assertEqual(params["currency"], "EUR")
        self.assertEqual(params["no_cache"], "true")
        self.assertEqual(params["zero_trace"], "true")
        self.assertEqual(result["data"]["month_label"], "October")
        self.assertEqual(result["data"]["travelers"]["adults"], 2)

    def test_month_outside_six_selectable_calendar_values_is_rejected(self):
        with patch(
            "serpapi_travel_explore.now_local",
            return_value=datetime(2026, 8, 9, 12, 0, 0),
        ):
            exit_code, result = run_tool({"departure_id": "PDX", "month": 2})

        self.assertEqual(exit_code, 1)
        self.assertIn("six selectable calendar months", result["error"])

    def test_exact_one_way_omits_flexible_duration(self):
        capture = {}
        _, result = run_tool(
            {
                "departure_id": "PDX",
                "trip_type": "one_way",
                "outbound_date": FUTURE_OUT,
            },
            capture=capture,
        )

        self.assertEqual(capture["params"]["type"], 2)
        self.assertEqual(capture["params"]["outbound_date"], FUTURE_OUT)
        self.assertNotIn("travel_duration", capture["params"])
        self.assertEqual(result["data"]["date_mode"], "exact")
        self.assertEqual(result["data"]["travel_duration"], None)

    def test_extra_params_cannot_override_reserved_contract(self):
        capture = {}
        run_tool(
            {
                "departure_id": "PDX",
                "extra_params": {
                    "engine": "google_flights",
                    "departure_id": "SEA",
                    "arrival_id": "LAX",
                    "api_key": "not-a-real-key",
                    "async": "true",
                    "zero_trace": "true",
                },
            },
            capture=capture,
        )
        self.assertEqual(capture["params"]["engine"], "google_travel_explore")
        self.assertEqual(capture["params"]["departure_id"], "PDX")
        self.assertNotIn("arrival_id", capture["params"])
        self.assertNotIn("api_key", capture["params"])
        self.assertNotIn("async", capture["params"])
        self.assertEqual(capture["params"]["zero_trace"], "true")


class TravelExploreResultTests(unittest.TestCase):
    def test_normalization_preserves_destination_and_airport_identities(self):
        rows = extract_travel_explore_destinations(SAMPLE_PAYLOAD, limit=0)
        zion = rows[0]

        self.assertEqual(zion["destination_id"], "/m/030qb3t")
        self.assertEqual(zion["airport_code"], "LAS")
        self.assertEqual(zion["airport_location"], "Las Vegas")
        self.assertEqual(zion["nights"], 7)
        self.assertEqual(zion["flight_duration_display"], "2h 15m")
        self.assertEqual(zion["ground_transfer_display"], "2h 44m")
        self.assertEqual(zion["stops_label"], "Nonstop")
        self.assertEqual(
            zion["google_travel_url"],
            "https://www.google.com/travel/explore/zion",
        )
        self.assertNotIn("serpapi_link", zion)

        malformed = rows[-1]
        self.assertIsNone(malformed["nights"])
        self.assertIsNone(malformed["number_of_stops"])

    def test_local_sort_uses_entire_provider_page_before_cap(self):
        _, result = run_tool(
            {"departure_id": "PDX", "sort_by": "hotel_price", "num_results": 2}
        )
        rows = result["data"]["results"]
        self.assertEqual([row["name"] for row in rows], ["Los Angeles", "Zion National Park"])
        self.assertEqual(result["data"]["provider_results_count"], 4)
        self.assertEqual(result["data"]["results_count"], 2)
        self.assertEqual(result["data"]["sort_basis"], "local_sort_of_returned_page")

    def test_default_preserves_google_order(self):
        _, result = run_tool({"departure_id": "PDX", "num_results": 2})
        self.assertEqual(
            [row["name"] for row in result["data"]["results"]],
            ["Zion National Park", "Las Vegas"],
        )
        self.assertEqual(result["data"]["sort_basis"], "provider_order")
        self.assertIn("exact flight and hotel searches", result["speech"])

    def test_empty_results_are_a_successful_search(self):
        _, result = run_tool(
            {"departure_id": "PDX"},
            response={"search_metadata": {"status": "Success"}, "destinations": []},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["results_count"], 0)
        self.assertIn("no destination ideas", result["speech"])

    def test_raw_payload_is_opt_in_and_metadata_is_compact(self):
        _, normal = run_tool({"departure_id": "PDX"})
        _, raw = run_tool({"departure_id": "PDX", "include_raw": True})

        self.assertNotIn("raw", normal["data"])
        self.assertNotIn("json_endpoint", normal["data"]["search_metadata"])
        self.assertEqual(raw["data"]["raw"], SAMPLE_PAYLOAD)


class TravelExploreValidationTests(unittest.TestCase):
    def assert_invalid(self, args, message):
        exit_code, result = run_tool(args)
        self.assertEqual(exit_code, 1)
        self.assertFalse(result["ok"])
        self.assertIn(message, result["error"])

    def test_origin_and_area_ids_are_validated(self):
        self.assert_invalid({}, "departure_id")
        self.assert_invalid({"departure_id": "Portland"}, "IATA")
        self.assert_invalid(
            {"departure_id": "PDX", "arrival_area_id": "Europe"},
            "KGMID",
        )

    def test_exact_date_relationships_are_validated(self):
        self.assert_invalid(
            {"departure_id": "PDX", "outbound_date": FUTURE_OUT},
            "return_date",
        )
        self.assert_invalid(
            {
                "departure_id": "PDX",
                "outbound_date": FUTURE_OUT,
                "return_date": FUTURE_BACK,
                "travel_duration": "weekend",
            },
            "either exact dates",
        )
        self.assert_invalid(
            {
                "departure_id": "PDX",
                "trip_type": "one_way",
                "return_date": FUTURE_BACK,
            },
            "requires 'outbound_date'",
        )
        self.assert_invalid(
            {
                "departure_id": "PDX",
                "trip_type": "one_way",
                "travel_duration": "weekend",
            },
            "round-trip",
        )
        past = (travel_explore.now_local() - timedelta(days=2)).strftime("%Y-%m-%d")
        self.assert_invalid(
            {"departure_id": "PDX", "trip_type": "one_way", "outbound_date": past},
            "in the past",
        )

    def test_mutually_exclusive_filters_are_rejected(self):
        self.assert_invalid(
            {"departure_id": "PDX", "travel_mode": "flight_only", "interest": "beaches"},
            "cannot be used together",
        )
        self.assert_invalid(
            {
                "departure_id": "PDX",
                "include_airlines": "AS",
                "exclude_airlines": "DL",
            },
            "either 'include_airlines'",
        )

    def test_traveler_bag_and_enum_validation(self):
        self.assert_invalid({"departure_id": "PDX", "adults": 0}, "at least 1")
        self.assert_invalid(
            {"departure_id": "PDX", "adults": 1, "infants_on_lap": 2},
            "cannot exceed",
        )
        self.assert_invalid({"departure_id": "PDX", "bags": 2}, "cannot exceed")
        self.assert_invalid({"departure_id": "PDX", "stops": "direct-ish"}, "stops")
        self.assert_invalid(
            {"departure_id": "PDX", "include_airlines": "Alaska"},
            "2-character",
        )

    def test_timeout_has_specific_user_facing_error(self):
        exit_code, result = run_tool(
            {"departure_id": "PDX"},
            request_error=TimeoutError("connection timed out"),
        )
        self.assertEqual(exit_code, 1)
        self.assertEqual(
            result["error"],
            "SerpApi Travel Explore timed out. Try again or narrow the filters.",
        )

    def test_provider_failure_does_not_echo_api_key(self):
        secret = "provider-secret-value-1234567890"
        exit_code, result = run_tool(
            {"departure_id": "PDX"},
            request_error=RuntimeError(
                f"request failed for https://serpapi.com/search.json?api_key={secret}&output=json"
            ),
        )

        self.assertEqual(exit_code, 1)
        self.assertNotIn(secret, json.dumps(result))
        self.assertIn("api_key=[redacted]", result["error"])


if __name__ == "__main__":
    unittest.main()
