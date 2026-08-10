#!/usr/bin/env python3
"""Regression tests for SerpApi result normalization."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from serpapi_client import extract_generic_results, request_serpapi


class SerpApiClientResultsTests(unittest.TestCase):
    def test_request_error_redacts_api_key_from_exception_text(self):
        secret = "provider-secret-value-1234567890"
        with patch("serpapi_client.get_api_key", return_value=secret), patch(
            "serpapi_client.http_request",
            side_effect=RuntimeError(
                f"failed https://serpapi.com/search.json?api_key={secret}&output=json"
            ),
        ):
            with self.assertRaises(RuntimeError) as raised:
                request_serpapi({"engine": "google_travel_explore"})

        message = str(raised.exception)
        self.assertNotIn(secret, message)
        self.assertIn("api_key=[redacted]", message)

    def test_amazon_product_includes_shopping_signals(self):
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
                "prime": True,
                "delivery": ["FREE delivery Tomorrow"],
                "shipping": "Ships from Amazon",
                "availability": "In Stock",
                "old_price": "$179.99",
                "extracted_old_price": 179.99,
                "save_with_coupon": "Save 10% with coupon",
            }
        }
        results = extract_generic_results(payload, engine="amazon_product", limit=5)
        self.assertEqual(results[0]["thumbnail"], "https://example.com/thumb.jpg")
        self.assertEqual(results[0]["asin"], "B000TEST")
        self.assertTrue(results[0]["prime"])
        self.assertEqual(results[0]["delivery"], ["FREE delivery Tomorrow"])
        self.assertEqual(results[0]["shipping"], "Ships from Amazon")
        self.assertEqual(results[0]["availability"], "In Stock")
        self.assertEqual(results[0]["extracted_old_price"], 179.99)
        self.assertEqual(results[0]["save_with_coupon"], "Save 10% with coupon")
        self.assertTrue(results[0]["prime_eligible"])

    def test_amazon_search_result_includes_shopping_signals(self):
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
                    "prime": True,
                    "delivery": ["FREE delivery Wed, Jul 29"],
                    "shipping": "Free shipping",
                    "stock": "Only 8 left in stock",
                    "bought_last_month": "2K+ bought in past month",
                    "badges": ["Overall Pick"],
                }
            ]
        }
        results = extract_generic_results(payload, engine="amazon", limit=5)
        self.assertEqual(results[0]["thumbnail"], "https://example.com/item.jpg")
        self.assertEqual(results[0]["extracted_price"], 99.99)
        self.assertTrue(results[0]["prime"])
        self.assertEqual(results[0]["delivery"], ["FREE delivery Wed, Jul 29"])
        self.assertEqual(results[0]["shipping"], "Free shipping")
        self.assertEqual(results[0]["stock"], "Only 8 left in stock")
        self.assertEqual(results[0]["bought_last_month"], "2K+ bought in past month")
        self.assertEqual(results[0]["badges"], ["Overall Pick"])
        self.assertTrue(results[0]["prime_eligible"])

    def test_amazon_product_derives_prime_eligibility_from_delivery_text(self):
        payload = {
            "product_results": {
                "title": "Example Product",
                "asin": "B000TEST3",
                "link": "https://amazon.com/dp/B000TEST3",
                "delivery": [
                    "FREE delivery Sunday",
                    "Or Prime members get FREE delivery Today on eligible orders",
                ],
                "stock": "In Stock",
            }
        }

        results = extract_generic_results(payload, engine="amazon_product", limit=1)

        self.assertIsNone(results[0]["prime"])
        self.assertTrue(results[0]["prime_eligible"])


if __name__ == "__main__":
    unittest.main()
