#!/usr/bin/env python3
"""Regression tests for the flight_search tool and its result normalization."""

import json
import sys
import unittest
from contextlib import redirect_stdout
from datetime import timedelta
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

from serpapi_client import extract_flight_results, extract_price_insights, format_duration_minutes

import flight_search
from flight_search import convert_fallback_itinerary, main, sort_results


FUTURE_OUT = "2099-09-15"
FUTURE_BACK = "2099-09-20"


def serpapi_itinerary(price, *, segments, total_duration, emissions=142000):
    return {
        "flights": segments,
        "layovers": [],
        "total_duration": total_duration,
        "carbon_emissions": {"this_flight": emissions, "typical_for_this_route": 192000},
        "price": price,
        "type": "Round trip",
    }


def segment(flight_number, airline, origin, destination, depart, arrive, duration):
    return {
        "departure_airport": {"name": f"{origin} Airport", "id": origin, "time": depart},
        "arrival_airport": {"name": f"{destination} Airport", "id": destination, "time": arrive},
        "duration": duration,
        "airplane": "Boeing 737",
        "airline": airline,
        "airline_logo": "https://example.test/logo.png",
        "travel_class": "Economy",
        "flight_number": flight_number,
        "legroom": "30 in",
        "overnight": False,
        "often_delayed_by_over_30_min": False,
    }


SAMPLE_PAYLOAD = {
    "search_metadata": {"google_flights_url": "https://www.google.com/travel/flights?tfs=abc"},
    "best_flights": [
        serpapi_itinerary(
            312,
            segments=[segment("AS 1234", "Alaska", "PDX", "PHX", "2099-09-15 07:03", "2099-09-15 09:51", 168)],
            total_duration=168,
        )
    ],
    "other_flights": [
        serpapi_itinerary(
            257,
            segments=[segment("WN 900", "Southwest", "PDX", "PHX", "2099-09-15 18:25", "2099-09-15 21:00", 155)],
            total_duration=155,
        )
    ],
    "price_insights": {
        "lowest_price": 257,
        "price_level": "low",
        "typical_price_range": [240, 420],
        "price_history": [[1700000000, 300]],
    },
}


def run_tool(payload_args, *, serpapi=True, response=None, capture=None):
    """Invoke main() with a stubbed provider and return the parsed JSON result."""
    def fake_request(params, timeout=25, **kwargs):
        if capture is not None:
            capture["params"] = dict(params)
            capture["timeout"] = timeout
        return response if response is not None else SAMPLE_PAYLOAD

    buffer = StringIO()
    with patch.object(sys, "argv", ["flight_search.py", json.dumps(payload_args)]), patch(
        "flight_search.load_config"
    ), patch(
        "flight_search.serpapi_configured", return_value=serpapi
    ), patch(
        "flight_search.get_proxy_enabled", return_value=False
    ), patch(
        "flight_search.request_serpapi", side_effect=fake_request
    ), redirect_stdout(buffer):
        exit_code = main()
    return exit_code, json.loads(buffer.getvalue())


class FlightSearchParamsTests(unittest.TestCase):
    def test_round_trip_is_a_single_request_with_price_sort(self):
        capture = {}
        exit_code, result = run_tool(
            {
                "departure_id": "pdx",
                "arrival_id": "phx",
                "outbound_date": FUTURE_OUT,
                "return_date": FUTURE_BACK,
            },
            capture=capture,
        )

        self.assertEqual(exit_code, 0)
        params = capture["params"]
        self.assertEqual(params["engine"], "google_flights")
        self.assertEqual(params["type"], 1)
        self.assertEqual(params["return_date"], FUTURE_BACK)
        self.assertEqual(params["departure_id"], "PDX")
        self.assertEqual(params["arrival_id"], "PHX")
        self.assertEqual(params["sort_by"], 2)
        self.assertEqual(params["travel_class"], 1)
        self.assertEqual(params["adults"], 1)
        self.assertNotIn("stops", params)
        self.assertEqual(result["data"]["trip_type"], "round_trip")
        self.assertEqual(result["data"]["price_basis"], "round_trip_total")
        self.assertEqual(result["data"]["serpapi_searches_used"], 1)

    def test_missing_return_date_is_one_way(self):
        capture = {}
        _, result = run_tool(
            {"departure_id": "PDX", "arrival_id": "PHX", "outbound_date": FUTURE_OUT},
            capture=capture,
        )

        self.assertEqual(capture["params"]["type"], 2)
        self.assertNotIn("return_date", capture["params"])
        self.assertEqual(result["data"]["trip_type"], "one_way")
        self.assertEqual(result["data"]["price_basis"], "one_way_total")

    def test_filters_map_to_serpapi_codes(self):
        capture = {}
        run_tool(
            {
                "departure_id": "PDX",
                "arrival_id": "PHX",
                "outbound_date": FUTURE_OUT,
                "travel_class": "business",
                "stops": "nonstop",
                "sort_by": "duration",
                "max_price": 400,
                "outbound_times": "4,18",
            },
            capture=capture,
        )

        params = capture["params"]
        self.assertEqual(params["travel_class"], 3)
        self.assertEqual(params["stops"], 1)
        self.assertEqual(params["sort_by"], 5)
        self.assertEqual(params["max_price"], 400)
        self.assertEqual(params["outbound_times"], "4,18")

    def test_include_airlines_supersedes_exclude(self):
        capture = {}
        run_tool(
            {
                "departure_id": "PDX",
                "arrival_id": "PHX",
                "outbound_date": FUTURE_OUT,
                "include_airlines": ["as", "aa"],
                "exclude_airlines": "wn",
            },
            capture=capture,
        )

        self.assertEqual(capture["params"]["include_airlines"], "AS,AA")
        self.assertNotIn("exclude_airlines", capture["params"])

    def test_deep_search_raises_the_http_timeout(self):
        capture = {}
        run_tool(
            {
                "departure_id": "PDX",
                "arrival_id": "PHX",
                "outbound_date": FUTURE_OUT,
                "deep_search": True,
            },
            capture=capture,
        )

        self.assertEqual(capture["params"]["deep_search"], "true")
        self.assertEqual(capture["timeout"], flight_search.SERPAPI_DEEP_SEARCH_TIMEOUT)

    def test_multiple_departure_airports_are_normalized(self):
        capture = {}
        run_tool(
            {
                "departure_id": "ewr, jfk ,lga",
                "arrival_id": "PHX",
                "outbound_date": FUTURE_OUT,
            },
            capture=capture,
        )

        self.assertEqual(capture["params"]["departure_id"], "EWR,JFK,LGA")


class FlightSearchResultTests(unittest.TestCase):
    def test_results_default_to_cheapest_first_across_both_buckets(self):
        _, result = run_tool(
            {"departure_id": "PDX", "arrival_id": "PHX", "outbound_date": FUTURE_OUT}
        )

        results = result["data"]["results"]
        self.assertEqual([item["price"] for item in results], [257, 312])
        self.assertEqual(result["data"]["cheapest_price"], 257)
        self.assertEqual(results[0]["airlines"], ["Southwest"])
        self.assertEqual(results[0]["flight_numbers"], ["WN 900"])
        self.assertEqual(results[0]["stops_label"], "Nonstop")
        self.assertEqual(results[0]["duration_display"], "2h 35m")

    def test_speech_leads_with_best_price_and_price_level(self):
        _, result = run_tool(
            {"departure_id": "PDX", "arrival_id": "PHX", "outbound_date": FUTURE_OUT}
        )

        self.assertIn("$257", result["speech"])
        self.assertIn("Southwest", result["speech"])
        self.assertIn("low price", result["speech"])

    def test_booking_url_is_surfaced_for_manual_booking(self):
        _, result = run_tool(
            {"departure_id": "PDX", "arrival_id": "PHX", "outbound_date": FUTURE_OUT}
        )

        self.assertEqual(
            result["data"]["booking_url"], "https://www.google.com/travel/flights?tfs=abc"
        )

    def test_num_results_is_clamped(self):
        _, result = run_tool(
            {
                "departure_id": "PDX",
                "arrival_id": "PHX",
                "outbound_date": FUTURE_OUT,
                "num_results": 1,
            }
        )

        self.assertEqual(result["data"]["results_count"], 1)

    def test_empty_results_stay_successful_with_clear_speech(self):
        _, result = run_tool(
            {"departure_id": "PDX", "arrival_id": "PHX", "outbound_date": FUTURE_OUT},
            response={"best_flights": [], "other_flights": []},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["results_count"], 0)
        self.assertIn("No one way flights found", result["speech"])


class FlightSearchValidationTests(unittest.TestCase):
    def test_missing_airports_are_rejected(self):
        exit_code, result = run_tool({"outbound_date": FUTURE_OUT})
        self.assertEqual(exit_code, 1)
        self.assertFalse(result["ok"])
        self.assertIn("departure_id", result["error"])

    def test_non_iso_date_is_rejected_with_guidance(self):
        exit_code, result = run_tool(
            {"departure_id": "PDX", "arrival_id": "PHX", "outbound_date": "Sept 15"}
        )
        self.assertEqual(exit_code, 1)
        self.assertIn("YYYY-MM-DD", result["error"])

    def test_past_date_is_rejected(self):
        past = (flight_search.now_local() - timedelta(days=3)).strftime("%Y-%m-%d")
        exit_code, result = run_tool(
            {"departure_id": "PDX", "arrival_id": "PHX", "outbound_date": past}
        )
        self.assertEqual(exit_code, 1)
        self.assertIn("in the past", result["error"])

    def test_return_before_outbound_is_rejected(self):
        exit_code, result = run_tool(
            {
                "departure_id": "PDX",
                "arrival_id": "PHX",
                "outbound_date": FUTURE_BACK,
                "return_date": FUTURE_OUT,
            }
        )
        self.assertEqual(exit_code, 1)
        self.assertIn("before", result["error"])

    def test_traveler_cap_is_enforced_before_the_request(self):
        exit_code, result = run_tool(
            {
                "departure_id": "PDX",
                "arrival_id": "PHX",
                "outbound_date": FUTURE_OUT,
                "adults": 9,
                "children": 3,
            }
        )
        self.assertEqual(exit_code, 1)
        self.assertIn("9 travelers", result["error"])

    def test_lap_infants_require_an_adult_each(self):
        exit_code, result = run_tool(
            {
                "departure_id": "PDX",
                "arrival_id": "PHX",
                "outbound_date": FUTURE_OUT,
                "adults": 1,
                "infants_on_lap": 2,
            }
        )
        self.assertEqual(exit_code, 1)
        self.assertIn("lap infant", result["error"])

    def test_unknown_enum_values_fall_back_to_defaults(self):
        capture = {}
        run_tool(
            {
                "departure_id": "PDX",
                "arrival_id": "PHX",
                "outbound_date": FUTURE_OUT,
                "travel_class": "luxury",
                "stops": "teleport",
                "sort_by": "vibes",
            },
            capture=capture,
        )

        self.assertEqual(capture["params"]["travel_class"], 1)
        self.assertEqual(capture["params"]["sort_by"], 2)
        self.assertNotIn("stops", capture["params"])


class FlightExtractorTests(unittest.TestCase):
    def test_extract_reads_both_buckets_and_drops_logos(self):
        results = extract_flight_results(SAMPLE_PAYLOAD, limit=0)
        self.assertEqual(len(results), 2)
        self.assertNotIn("airline_logo", results[0])
        self.assertNotIn("airline_logo", results[0]["segments"][0])
        self.assertEqual(results[0]["carbon_kg"], 142)

    def test_limit_zero_returns_everything(self):
        self.assertEqual(len(extract_flight_results(SAMPLE_PAYLOAD, limit=1)), 1)
        self.assertEqual(len(extract_flight_results(SAMPLE_PAYLOAD, limit=0)), 2)

    def test_connection_reports_stops_and_layovers(self):
        payload = {
            "other_flights": [
                {
                    "flights": [
                        segment("AS 1", "Alaska", "PDX", "SEA", "2099-09-15 07:00", "2099-09-15 08:00", 60),
                        segment("AS 2", "Alaska", "SEA", "PHX", "2099-09-15 09:05", "2099-09-15 12:00", 175),
                    ],
                    "layovers": [{"duration": 65, "name": "Seattle", "id": "SEA", "overnight": False}],
                    "total_duration": 300,
                    "price": 199,
                }
            ]
        }
        results = extract_flight_results(payload, limit=0)
        self.assertEqual(results[0]["stops"], 1)
        self.assertEqual(results[0]["stops_label"], "1 stop")
        self.assertEqual(results[0]["layovers"][0]["airport"], "SEA")
        self.assertEqual(results[0]["layovers"][0]["duration_display"], "1h 5m")
        self.assertEqual(results[0]["departure_airport"], "PDX")
        self.assertEqual(results[0]["arrival_airport"], "PHX")

    def test_price_insights_drop_the_history_series(self):
        insights = extract_price_insights(SAMPLE_PAYLOAD)
        self.assertEqual(insights["price_level"], "low")
        self.assertNotIn("price_history", insights)

    def test_duration_formatting(self):
        self.assertEqual(format_duration_minutes(168), "2h 48m")
        self.assertEqual(format_duration_minutes(120), "2h")
        self.assertEqual(format_duration_minutes(45), "45m")
        self.assertIsNone(format_duration_minutes(None))
        self.assertIsNone(format_duration_minutes(0))

    def test_sort_results_puts_unpriced_itineraries_last(self):
        rows = [{"price": None}, {"price": 300}, {"price": 120}]
        self.assertEqual([row["price"] for row in sort_results(rows, "price")], [120, 300, None])


class FallbackConversionTests(unittest.TestCase):
    """The keyless provider must land on the same shape as the SerpApi path."""

    def _entry(self):
        leg = SimpleNamespace(
            from_airport=SimpleNamespace(code="PDX", name="Portland International Airport"),
            to_airport=SimpleNamespace(code="PHX", name="Phoenix Sky Harbor"),
            departure=SimpleNamespace(date=[2099, 9, 15], time=[7, 3]),
            arrival=SimpleNamespace(date=[2099, 9, 15], time=[9, 51]),
            duration=168,
            plane_type="Boeing 737",
        )
        return SimpleNamespace(
            type="AS",
            price=257,
            airlines=["Alaska"],
            flights=[leg],
            carbon=SimpleNamespace(typical_on_route=192000, emission=142000),
        )

    def test_fallback_itinerary_matches_serpapi_field_names(self):
        converted = convert_fallback_itinerary(self._entry(), "economy")
        expected = set(extract_flight_results(SAMPLE_PAYLOAD, limit=1)[0].keys())
        self.assertEqual(set(converted.keys()), expected)
        self.assertEqual(converted["price"], 257)
        self.assertEqual(converted["departure_time"], "2099-09-15 07:03")
        self.assertEqual(converted["duration_display"], "2h 48m")
        self.assertEqual(converted["stops_label"], "Nonstop")
        self.assertEqual(converted["carbon_kg"], 142)
        self.assertEqual(converted["flight_numbers"], [])

    def test_hour_only_departure_time_is_padded(self):
        entry = self._entry()
        entry.flights[0].departure = SimpleNamespace(date=[2099, 9, 15], time=[9])
        converted = convert_fallback_itinerary(entry, "economy")
        self.assertEqual(converted["departure_time"], "2099-09-15 09:00")

    def test_layover_duration_is_derived_from_segment_gaps(self):
        entry = self._entry()
        second = SimpleNamespace(
            from_airport=SimpleNamespace(code="SEA", name="Seattle"),
            to_airport=SimpleNamespace(code="PHX", name="Phoenix"),
            departure=SimpleNamespace(date=[2099, 9, 15], time=[11, 0]),
            arrival=SimpleNamespace(date=[2099, 9, 15], time=[14, 0]),
            duration=180,
            plane_type="Airbus A320",
        )
        entry.flights[0].to_airport = SimpleNamespace(code="SEA", name="Seattle")
        entry.flights[0].arrival = SimpleNamespace(date=[2099, 9, 15], time=[9, 51])
        entry.flights.append(second)

        converted = convert_fallback_itinerary(entry, "economy")
        self.assertEqual(converted["stops"], 1)
        self.assertEqual(converted["layovers"][0]["airport"], "SEA")
        self.assertEqual(converted["layovers"][0]["duration_display"], "1h 9m")
        self.assertEqual(converted["total_duration_minutes"], 168 + 69 + 180)


if __name__ == "__main__":
    unittest.main()
