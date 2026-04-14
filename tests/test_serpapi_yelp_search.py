#!/usr/bin/env python3
"""Regression tests for serpapi_yelp_search helpers."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

from serpapi_yelp_search import (
    extract_yelp_results,
    extract_yelp_reviews,
    normalize_attrs,
    normalize_sort_by,
)


class SerpApiYelpSearchTests(unittest.TestCase):
    def test_normalize_attrs_appends_dogs_allowed(self):
        self.assertEqual(
            normalize_attrs(["GoodForKids"], dogs_allowed=True),
            "GoodForKids,DogsAllowed",
        )

    def test_normalize_sort_by_maps_reviews(self):
        self.assertEqual(normalize_sort_by("reviews"), "review_count")

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


if __name__ == "__main__":
    unittest.main()
