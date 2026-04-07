#!/usr/bin/env python3
"""Regression tests for SerpApi result normalization."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from serpapi_client import extract_generic_results


class SerpApiClientResultsTests(unittest.TestCase):
    def test_amazon_product_includes_thumbnail(self):
        payload = {
            "product_results": {
                "title": "Example Product",
                "link": "https://amazon.com/dp/B000TEST",
                "asin": "B000TEST",
                "price": "$149.99",
                "extracted_price": 149.99,
                "rating": 4.8,
                "reviews": 1200,
                "thumbnail": "https://example.com/thumb.jpg",
            }
        }
        results = extract_generic_results(payload, engine="amazon_product", limit=5)
        self.assertEqual(results[0]["thumbnail"], "https://example.com/thumb.jpg")
        self.assertEqual(results[0]["asin"], "B000TEST")

    def test_amazon_search_result_includes_thumbnail(self):
        payload = {
            "organic_results": [
                {
                    "title": "Example Search Result",
                    "link": "https://amazon.com/dp/B000TEST2",
                    "asin": "B000TEST2",
                    "price": "$99.99",
                    "extracted_price": 99.99,
                    "rating": 4.5,
                    "reviews": 42,
                    "thumbnail": "https://example.com/item.jpg",
                }
            ]
        }
        results = extract_generic_results(payload, engine="amazon", limit=5)
        self.assertEqual(results[0]["thumbnail"], "https://example.com/item.jpg")
        self.assertEqual(results[0]["extracted_price"], 99.99)


if __name__ == "__main__":
    unittest.main()
