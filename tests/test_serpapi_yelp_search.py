#!/usr/bin/env python3
"""Regression tests for serpapi_yelp_search helpers."""

import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch
import json

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

from serpapi_yelp_search import (
    extract_yelp_results,
    extract_yelp_reviews,
    main,
    normalize_attrs,
    normalize_sort_by,
    sort_yelp_results,
)


class SerpApiYelpSearchTests(unittest.TestCase):
    def test_normalize_attrs_appends_dogs_allowed(self):
        self.assertEqual(
            normalize_attrs(["GoodForKids"], dogs_allowed=True),
            "GoodForKids,DogsAllowed",
        )

    def test_normalize_sort_by_maps_reviews(self):
        self.assertEqual(normalize_sort_by("reviews"), "review_count")

    def test_normalize_sort_by_rejects_provider_distance_mode(self):
        with self.assertRaisesRegex(ValueError, "recommended, rating, or review_count"):
            normalize_sort_by("distance")

    def test_extract_yelp_results_preserves_place_fields(self):
        payload = {
            "organic_results": [
                {
                    "title": "Pup Cup Coffee",
                    "link": "https://www.yelp.com/biz/pup-cup-coffee",
                    "place_id": "pup-cup-coffee-seattle",
                    "rating": 4.7,
                    "reviews": 321,
                    "price": "$$",
                    "phone": "(555) 111-2222",
                    "address": ["123 Market St", "Seattle, WA 98101"],
                    "categories": ["Coffee & Tea", "Cafes"],
                    "thumbnail": "https://s3-media.example.com/pup.jpg",
                }
            ]
        }
        results = extract_yelp_results(payload, limit=5)
        self.assertEqual(results[0]["place_id"], "pup-cup-coffee-seattle")
        self.assertEqual(results[0]["address"], "123 Market St, Seattle, WA 98101")
        self.assertEqual(results[0]["price"], "$$")

    def test_extract_yelp_results_handles_current_place_ids_and_category_objects(self):
        payload = {
            "organic_results": [
                {
                    "position": 1,
                    "title": "Cabana do Cafe",
                    "link": "https://www.yelp.com/biz/cabana-do-cafe-hillsboro",
                    "place_ids": ["provider-id", "cabana-do-cafe-hillsboro"],
                    "rating": 4.8,
                    "reviews": 24,
                    "categories": [
                        {"title": "Cafes", "link": "https://www.yelp.com/search?cflt=cafes"},
                        {"title": "Coffee & Tea"},
                    ],
                    "neighborhoods": "Hillsboro",
                    "open_state": "Open until 8:00 pm",
                    "service_options": {"takeout": True},
                    "highlights": ["Outdoor seating"],
                }
            ]
        }

        result = extract_yelp_results(payload)[0]

        self.assertEqual(result["place_id"], "provider-id")
        self.assertEqual(
            result["place_ids"], ["provider-id", "cabana-do-cafe-hillsboro"]
        )
        self.assertEqual(result["categories"], ["Cafes", "Coffee & Tea"])
        self.assertEqual(result["neighborhoods"], "Hillsboro")
        self.assertEqual(result["open_state"], "Open until 8:00 pm")
        self.assertEqual(result["service_options"], {"takeout": True})

    def test_extract_yelp_results_derives_grounded_title_from_url_when_missing(self):
        results = extract_yelp_results(
            {
                "organic_results": [
                    {
                        "link": "https://www.yelp.com/biz/copperhead-coffee-hillsboro?osq=coffee",
                        "place_ids": ["provider-id"],
                    }
                ]
            }
        )

        self.assertEqual(results[0]["title"], "Copperhead Coffee Hillsboro")
        self.assertEqual(results[0]["title_source"], "url_slug")

    def test_sort_yelp_results_orders_complete_page_locally(self):
        results = [
            {"title": "Many Reviews", "rating": 4.5, "reviews": 500},
            {"title": "Highest Rated", "rating": 4.9, "reviews": 20},
            {"title": "Missing", "rating": None, "reviews": None},
        ]

        self.assertEqual(
            [item["title"] for item in sort_yelp_results(results, "rating")],
            ["Highest Rated", "Many Reviews", "Missing"],
        )
        self.assertEqual(
            [item["title"] for item in sort_yelp_results(results, "review_count")],
            ["Many Reviews", "Highest Rated", "Missing"],
        )

    def test_extract_yelp_reviews_preserves_text_and_user(self):
        payload = {
            "reviews": [
                {
                    "rating": 5,
                    "date": "2026-04-01",
                    "text": "Great patio and dog treats.",
                    "user": {
                        "name": "Alex",
                        "link": "https://www.yelp.com/user_details?userid=123",
                    },
                }
            ]
        }
        reviews = extract_yelp_reviews(payload, limit=3)
        self.assertEqual(reviews[0]["user_name"], "Alex")
        self.assertIn("dog treats", reviews[0]["text"])

    def test_extract_yelp_reviews_handles_current_comment_shape(self):
        payload = {
            "reviews": [
                {
                    "position": 1,
                    "rating": 5,
                    "date": "2026-07-15T10:30:00Z",
                    "comment": {"text": "Excellent espresso.", "language": "en"},
                    "user": {
                        "name": "Sam R.",
                        "user_id": "user-7",
                        "link": "https://www.yelp.com/user_details?userid=user-7",
                        "address": "Hillsboro, OR",
                    },
                    "photos": [{"link": "https://example.test/photo.jpg", "caption": "Latte"}],
                    "feedback": {"useful": 2},
                }
            ]
        }

        review = extract_yelp_reviews(payload, limit=3)[0]

        self.assertEqual(review["text"], "Excellent espresso.")
        self.assertEqual(review["language"], "en")
        self.assertEqual(review["user_id"], "user-7")
        self.assertEqual(review["user_location"], "Hillsboro, OR")
        self.assertEqual(review["photos"][0]["caption"], "Latte")

    def test_main_sorts_locally_without_sending_provider_sortby(self):
        payload = {
            "organic_results": [
                {"title": "Busy Cafe", "place_ids": ["busy"], "rating": 4.5, "reviews": 800},
                {"title": "Top Cafe", "place_ids": ["top"], "rating": 4.9, "reviews": 40},
            ],
            "search_metadata": {"status": "Success"},
        }
        stdout = StringIO()
        argv = [
            "serpapi_yelp_search.py",
            json.dumps({"find_desc": "coffee", "find_loc": "Hillsboro, OR", "sort_by": "rating"}),
        ]

        with patch("serpapi_yelp_search.load_config"), patch(
            "serpapi_yelp_search.request_serpapi", return_value=payload
        ) as request_mock, patch.object(sys, "argv", argv), redirect_stdout(stdout):
            exit_code = main()

        result = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["data"]["results"][0]["title"], "Top Cafe")
        self.assertEqual(result["data"]["sort_basis"], "local_sort_of_returned_page")
        self.assertNotIn("sortby", request_mock.call_args.args[0])

    def test_main_uses_jarvis_default_location_when_find_loc_is_omitted(self):
        payload = {
            "organic_results": [
                {
                    "title": "Default Cafe",
                    "place_ids": ["default-cafe"],
                    "rating": 4.6,
                }
            ],
            "search_metadata": {"status": "Success"},
        }
        stdout = StringIO()
        argv = ["serpapi_yelp_search.py", json.dumps({"find_desc": "coffee"})]

        with patch("serpapi_yelp_search.load_config"), patch(
            "serpapi_yelp_search.get_default_location",
            return_value="Hillsboro, Oregon",
        ), patch(
            "serpapi_yelp_search.request_serpapi", return_value=payload
        ) as request_mock, patch.object(sys, "argv", argv), redirect_stdout(stdout):
            exit_code = main()

        result = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["data"]["find_loc"], "Hillsboro, Oregon")
        self.assertEqual(
            request_mock.call_args.args[0]["find_loc"],
            "Hillsboro, Oregon",
        )

    def test_main_fetches_requested_reviews_with_first_supported_place_id(self):
        search_payload = {
            "organic_results": [
                {"title": "Cabana do Cafe", "place_ids": ["provider-id", "slug-id"], "rating": 4.8}
            ],
            "search_metadata": {"status": "Success"},
        }
        review_payload = {
            "search_information": {"business": "Cabana do Cafe", "total_results": 24},
            "search_metadata": {"status": "Success"},
            "reviews": [
                {
                    "rating": 5,
                    "comment": {"text": "Great coffee.", "language": "en"},
                    "user": {"name": "Alex"},
                }
            ],
        }
        stdout = StringIO()
        argv = [
            "serpapi_yelp_search.py",
            json.dumps(
                {
                    "find_desc": "coffee",
                    "find_loc": "Hillsboro, OR",
                    "include_reviews": True,
                    "review_limit": 1,
                }
            ),
        ]

        with patch("serpapi_yelp_search.load_config"), patch(
            "serpapi_yelp_search.request_serpapi",
            side_effect=[search_payload, review_payload],
        ) as request_mock, patch.object(sys, "argv", argv), redirect_stdout(stdout):
            exit_code = main()

        result = json.loads(stdout.getvalue())
        review_request = request_mock.call_args_list[1].args[0]
        self.assertEqual(exit_code, 0)
        self.assertEqual(review_request["place_id"], "provider-id")
        self.assertEqual(review_request["num"], 1)
        self.assertEqual(result["data"]["serpapi_searches_used"], 2)
        self.assertEqual(result["data"]["review_data"]["reviews"][0]["text"], "Great coffee.")

    def test_main_treats_empty_yelp_results_as_success(self):
        payload = {
            "error": "Yelp hasn't returned any results for this query.",
            "search_information": {"organic_results_state": "Fully empty"},
            "search_metadata": {"status": "Success"},
        }
        stdout = StringIO()
        argv = [
            "serpapi_yelp_search.py",
            json.dumps({
                "find_desc": "arcade pinball kids activities",
                "find_loc": "Hillsboro, OR",
                "num_results": 8,
            }),
        ]

        with patch("serpapi_yelp_search.load_config"), patch(
            "serpapi_yelp_search.request_serpapi", return_value=payload
        ) as request_mock, patch.object(sys, "argv", argv), redirect_stdout(stdout):
            exit_code = main()

        result = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["results_count"], 0)
        self.assertEqual(result["data"]["serpapi_error"], payload["error"])
        self.assertIn("No Yelp results found", result["speech"])
        self.assertEqual(
            request_mock.call_args.kwargs["allowed_error_substrings"],
            ("Yelp hasn't returned any results",),
        )


if __name__ == "__main__":
    unittest.main()
