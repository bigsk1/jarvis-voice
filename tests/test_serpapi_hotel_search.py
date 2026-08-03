#!/usr/bin/env python3
"""Regression tests for the SerpApi Google Hotels tool."""

import json
import sys
import unittest
from contextlib import redirect_stdout
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

import serpapi_hotel_search as hotel_search  # noqa: E402
from serpapi_client import extract_hotel_results  # noqa: E402


FUTURE_IN = "2099-08-11"
FUTURE_OUT = "2099-08-13"

SAMPLE_PAYLOAD = {
    "search_metadata": {
        "id": "search_123",
        "status": "Success",
        "total_time_taken": {"float": 2.4},
        "json_endpoint": "https://serpapi.example/search_123.json",
    },
    "search_information": {"hotels_results_state": "Results for exact spelling"},
    "properties": [
        {
            "name": "Desert Grand",
            "property_token": "property-expensive",
            "link": "https://hotel.example/desert-grand",
            "type": "hotel",
            "hotel_class": "4-star hotel",
            "extracted_hotel_class": 4,
            "overall_rating": 4.7,
            "reviews": 400,
            "rate_per_night": {
                "lowest": "$150",
                "extracted_lowest": 150,
                "before_taxes_fees": "$130",
                "extracted_before_taxes_fees": 130,
            },
            "total_rate": {
                "lowest": "$300",
                "extracted_lowest": 300,
                "before_taxes_fees": "$260",
                "extracted_before_taxes_fees": 260,
            },
            "amenities": ["Pool", "Wi-Fi"],
            "nearby_places": [
                {
                    "name": "Convention Center",
                    "transportations": [{"type": "Taxi", "duration": "8 min"}],
                }
            ],
        },
        {
            "name": "Budget Palms",
            "property_token": "property-cheap",
            "type": "hotel",
            "overall_rating": 4.1,
            "reviews": 120,
            "rate_per_night": {"lowest": "$90", "extracted_lowest": 90},
            "total_rate": {"lowest": "$180", "extracted_lowest": 180},
            "images": [
                {
                    "thumbnail": "https://images.example/budget-palms.jpg",
                    "original_image": "https://images.example/budget-palms-original.jpg",
                }
            ],
            "prices": [
                {
                    "source": "HotelSite",
                    "link": "https://book.example/budget-palms",
                    "rate_per_night": {"lowest": "$90", "extracted_lowest": 90},
                    "total_rate": {"lowest": "$180", "extracted_lowest": 180},
                    "free_cancellation": True,
                }
            ],
        },
        {
            "name": "Unpriced Favorite",
            "property_token": "property-unpriced",
            "link": "https://hotel.example/unpriced",
            "type": "hotel",
            "overall_rating": 4.9,
            "reviews": 20,
        },
    ],
    "non_matching_properties": [
        {
            "name": "Fails Active Filters",
            "property_token": "property-non-match",
            "total_rate": {"lowest": "$50", "extracted_lowest": 50},
        }
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
        ["serpapi_hotel_search.py", json.dumps(payload_args)],
    ), patch(
        "serpapi_hotel_search.load_config"
    ), patch(
        "serpapi_hotel_search.request_serpapi", side_effect=fake_request
    ), patch(
        "serpapi_hotel_search.get_proxy_enabled", return_value=True
    ), redirect_stdout(output):
        exit_code = hotel_search.main()
    return exit_code, json.loads(output.getvalue())


class HotelSearchParameterTests(unittest.TestCase):
    def test_default_is_one_price_sorted_serpapi_search(self):
        capture = {}
        exit_code, result = run_tool(
            {
                "destination": "Phoenix, Arizona",
                "check_in_date": FUTURE_IN,
                "check_out_date": FUTURE_OUT,
            },
            capture=capture,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(capture["calls"], 1)
        self.assertEqual(capture["timeout"], hotel_search.SERPAPI_TIMEOUT)
        self.assertEqual(
            capture["params"],
            {
                "engine": "google_hotels",
                "q": "Phoenix, Arizona",
                "check_in_date": FUTURE_IN,
                "check_out_date": FUTURE_OUT,
                "adults": 2,
                "children": 0,
                "currency": "USD",
                "device": "desktop",
                "no_cache": "false",
                "hl": "en",
                "gl": "us",
                "sort_by": 3,
            },
        )
        self.assertEqual(result["data"]["sort_by"], "price")
        self.assertEqual(result["data"]["serpapi_searches_used"], 1)
        self.assertTrue(result["data"]["proxy_enabled"])

    def test_filters_and_guest_fields_map_to_provider_contract(self):
        capture = {}
        _, result = run_tool(
            {
                "destination": "Phoenix",
                "query": "hotels near Phoenix Convention Center",
                "check_in_date": FUTURE_IN,
                "check_out_date": FUTURE_OUT,
                "adults": 2,
                "children": 2,
                "children_ages": [5, 8],
                "sort_by": "rating",
                "min_price": 100,
                "max_price": 400,
                "rating": 8,
                "hotel_class": [3, 4],
                "property_types": [12, 17],
                "amenities": [9, 35],
                "brands": [33],
                "free_cancellation": True,
                "special_offers": True,
                "eco_certified": True,
                "currency": "eur",
                "device": "mobile",
                "no_cache": True,
            },
            capture=capture,
        )

        params = capture["params"]
        self.assertEqual(params["q"], "hotels near Phoenix Convention Center")
        self.assertEqual(params["children_ages"], "5,8")
        self.assertEqual(params["sort_by"], 8)
        self.assertEqual(params["min_price"], 100)
        self.assertEqual(params["max_price"], 400)
        self.assertEqual(params["rating"], 8)
        self.assertEqual(params["hotel_class"], "3,4")
        self.assertEqual(params["property_types"], "12,17")
        self.assertEqual(params["amenities"], "9,35")
        self.assertEqual(params["brands"], "33")
        self.assertEqual(params["free_cancellation"], "true")
        self.assertEqual(params["special_offers"], "true")
        self.assertEqual(params["eco_certified"], "true")
        self.assertEqual(params["currency"], "EUR")
        self.assertEqual(params["device"], "mobile")
        self.assertEqual(params["no_cache"], "true")
        self.assertEqual(
            result["data"]["applied_filters"],
            {
                "min_price": 100,
                "max_price": 400,
                "rating": 8,
                "hotel_class": [3, 4],
                "property_types": [12, 17],
                "amenities": [9, 35],
                "brands": [33],
                "free_cancellation": True,
                "special_offers": True,
                "eco_certified": True,
            },
        )

    def test_relevance_omits_provider_sort_and_numeric_alias_is_compatible(self):
        capture = {}
        run_tool(
            {
                "destination": "Phoenix",
                "check_in_date": FUTURE_IN,
                "check_out_date": FUTURE_OUT,
                "sort_by": "relevance",
            },
            capture=capture,
        )
        self.assertNotIn("sort_by", capture["params"])

        capture = {}
        _, result = run_tool(
            {
                "destination": "Phoenix",
                "check_in_date": FUTURE_IN,
                "check_out_date": FUTURE_OUT,
                "sort_by": 13,
            },
            capture=capture,
        )
        self.assertEqual(capture["params"]["sort_by"], 13)
        self.assertEqual(result["data"]["sort_by"], "reviews")

    def test_extra_params_cannot_override_reserved_contract(self):
        capture = {}
        run_tool(
            {
                "destination": "Phoenix",
                "check_in_date": FUTURE_IN,
                "check_out_date": FUTURE_OUT,
                "extra_params": {
                    "q": "wrong city",
                    "sort_by": 8,
                    "api_key": "not-a-real-key",
                    "async": "true",
                    "property_token": "wrong-search-mode",
                    "zero_trace": "true",
                },
            },
            capture=capture,
        )
        self.assertEqual(capture["params"]["q"], "Phoenix")
        self.assertEqual(capture["params"]["sort_by"], 3)
        self.assertNotIn("api_key", capture["params"])
        self.assertNotIn("async", capture["params"])
        self.assertNotIn("property_token", capture["params"])
        self.assertEqual(capture["params"]["zero_trace"], "true")


class HotelSearchResultTests(unittest.TestCase):
    def test_default_sorts_entire_provider_page_by_stay_total(self):
        _, result = run_tool(
            {
                "destination": "Phoenix",
                "check_in_date": FUTURE_IN,
                "check_out_date": FUTURE_OUT,
            }
        )

        rows = result["data"]["results"]
        self.assertEqual(
            [row["title"] for row in rows],
            ["Budget Palms", "Desert Grand", "Unpriced Favorite"],
        )
        self.assertEqual(result["data"]["nights"], 2)
        self.assertEqual(result["data"]["cheapest_price_total"], 180)
        self.assertEqual(result["data"]["cheapest_price_per_night"], 90)
        self.assertEqual(
            result["data"]["price_basis"], "lowest_listed_total_for_entire_stay"
        )
        self.assertIn("$180 total", result["speech"])
        self.assertIn("$90 per night", result["speech"])

    def test_rating_reviews_and_relevance_ordering(self):
        args = {
            "destination": "Phoenix",
            "check_in_date": FUTURE_IN,
            "check_out_date": FUTURE_OUT,
        }
        _, rating = run_tool({**args, "sort_by": "rating"})
        _, reviews = run_tool({**args, "sort_by": "reviews"})
        _, relevance = run_tool({**args, "sort_by": "relevance"})

        self.assertEqual(rating["data"]["results"][0]["title"], "Unpriced Favorite")
        self.assertEqual(reviews["data"]["results"][0]["title"], "Desert Grand")
        self.assertEqual(relevance["data"]["results"][0]["title"], "Desert Grand")

    def test_normalization_keeps_property_identity_and_booking_fields(self):
        rows = extract_hotel_results(SAMPLE_PAYLOAD, limit=0)
        cheap = rows[1]
        expensive = rows[0]

        self.assertEqual(cheap["property_id"], "property-cheap")
        self.assertEqual(cheap["url"], "https://book.example/budget-palms")
        self.assertEqual(cheap["thumbnail"], "https://images.example/budget-palms.jpg")
        self.assertTrue(cheap["free_cancellation"])
        self.assertEqual(cheap["first_price_source"], "HotelSite")
        self.assertEqual(cheap["booking_options"][0]["price_total"], "$180")
        self.assertEqual(expensive["extracted_hotel_class"], 4)
        self.assertEqual(expensive["extracted_before_taxes_fees_total"], 260)
        self.assertEqual(
            expensive["nearby_places"][0]["transportation"][0]["duration"],
            "8 min",
        )
        self.assertNotIn("Fails Active Filters", [row["title"] for row in rows])

    def test_normalization_tolerates_single_object_provider_buckets(self):
        rows = extract_hotel_results(
            {
                "properties": {
                    "name": "Solo Hotel",
                    "property_token": "property-solo",
                    "images": {"thumbnail": "https://images.example/solo.jpg"},
                    "prices": {
                        "source": "Direct",
                        "link": "https://book.example/solo",
                        "free_cancellation": True,
                    },
                    "nearby_places": {
                        "name": "Airport",
                        "transportations": {"type": "Taxi", "duration": "5 min"},
                    },
                }
            },
            limit=0,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["property_id"], "property-solo")
        self.assertEqual(rows[0]["url"], "https://book.example/solo")
        self.assertEqual(rows[0]["thumbnail"], "https://images.example/solo.jpg")
        self.assertTrue(rows[0]["free_cancellation"])
        self.assertEqual(rows[0]["nearby_places"][0]["name"], "Airport")

    def test_num_results_caps_after_local_sort(self):
        _, result = run_tool(
            {
                "destination": "Phoenix",
                "check_in_date": FUTURE_IN,
                "check_out_date": FUTURE_OUT,
                "num_results": 1,
            }
        )
        self.assertEqual(result["data"]["results_count"], 1)
        self.assertEqual(result["data"]["provider_results_count"], 3)
        self.assertEqual(result["data"]["results"][0]["title"], "Budget Palms")

    def test_empty_results_are_a_successful_search(self):
        _, result = run_tool(
            {
                "destination": "Phoenix",
                "check_in_date": FUTURE_IN,
                "check_out_date": FUTURE_OUT,
            },
            response={"search_metadata": {"status": "Success"}, "properties": []},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["results_count"], 0)
        self.assertIn("No hotel results", result["speech"])

    def test_raw_payload_is_opt_in_and_metadata_is_compact_by_default(self):
        args = {
            "destination": "Phoenix",
            "check_in_date": FUTURE_IN,
            "check_out_date": FUTURE_OUT,
        }
        _, normal = run_tool(args)
        _, raw = run_tool({**args, "include_raw": True})

        self.assertNotIn("raw", normal["data"])
        self.assertNotIn("json_endpoint", normal["data"]["search_metadata"])
        self.assertEqual(raw["data"]["raw"], SAMPLE_PAYLOAD)


class HotelSearchValidationTests(unittest.TestCase):
    def assert_invalid(self, args, message):
        exit_code, result = run_tool(args)
        self.assertEqual(exit_code, 1)
        self.assertFalse(result["ok"])
        self.assertIn(message, result["error"])

    def base_args(self):
        return {
            "destination": "Phoenix",
            "check_in_date": FUTURE_IN,
            "check_out_date": FUTURE_OUT,
        }

    def test_destination_and_both_dates_are_required(self):
        self.assert_invalid(
            {"check_in_date": FUTURE_IN, "check_out_date": FUTURE_OUT},
            "destination",
        )
        self.assert_invalid({"destination": "Phoenix"}, "Both 'check_in_date'")

    def test_non_iso_and_past_dates_are_rejected(self):
        self.assert_invalid(
            {**self.base_args(), "check_in_date": "August 11, 2099"},
            "YYYY-MM-DD",
        )
        past = (hotel_search.now_local() - timedelta(days=2)).strftime("%Y-%m-%d")
        self.assert_invalid({**self.base_args(), "check_in_date": past}, "in the past")

    def test_checkout_must_be_after_checkin(self):
        self.assert_invalid(
            {**self.base_args(), "check_out_date": FUTURE_IN},
            "must be after",
        )

    def test_children_ages_must_match_and_be_in_range(self):
        self.assert_invalid(
            {**self.base_args(), "children": 2, "children_ages": [5]},
            "must match",
        )
        self.assert_invalid(
            {**self.base_args(), "children": 1, "children_ages": [18]},
            "1 through 17",
        )

    def test_children_can_be_searched_without_optional_age_list(self):
        capture = {}
        exit_code, _ = run_tool(
            {**self.base_args(), "children": 2}, capture=capture
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(capture["params"]["children"], 2)
        self.assertNotIn("children_ages", capture["params"])

    def test_invalid_counts_and_price_range_are_rejected(self):
        self.assert_invalid({**self.base_args(), "adults": 0}, "at least 1")
        self.assert_invalid({**self.base_args(), "children": "many"}, "integer")
        self.assert_invalid(
            {**self.base_args(), "min_price": 400, "max_price": 100},
            "cannot be greater",
        )

    def test_invalid_filter_enums_are_rejected(self):
        self.assert_invalid({**self.base_args(), "rating": 6}, "must be 7")
        self.assert_invalid({**self.base_args(), "hotel_class": [1, 4]}, "2, 3, 4, or 5")
        self.assert_invalid({**self.base_args(), "sort_by": "distance"}, "sort_by")
        self.assert_invalid({**self.base_args(), "amenities": [0]}, "at least 1")
        self.assert_invalid({**self.base_args(), "device": "watch"}, "device")
        self.assert_invalid({**self.base_args(), "currency": "dollars"}, "3-letter")

    def test_timeout_has_a_specific_user_facing_error(self):
        exit_code, result = run_tool(
            self.base_args(), request_error=TimeoutError("connection timed out")
        )
        self.assertEqual(exit_code, 1)
        self.assertEqual(
            result["error"],
            "SerpApi hotel search timed out. Try again or narrow the filters.",
        )


if __name__ == "__main__":
    unittest.main()
