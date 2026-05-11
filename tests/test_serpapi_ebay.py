#!/usr/bin/env python3
"""Regression tests for SerpApi eBay skills helpers."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

from serpapi_ebay_product import extract_ebay_product_summary, _compact_related
from serpapi_ebay_search import extract_ebay_search_results, normalize_ipg, main as ebay_search_main


class SerpApiEbaySearchTests(unittest.TestCase):
    def test_normalize_ipg_allowed(self):
        self.assertEqual(normalize_ipg(50), 50)

    def test_normalize_ipg_rejects_bad(self):
        self.assertIsNone(normalize_ipg(33))

    def test_extract_ebay_search_maps_link_to_url(self):
        payload = {
            "organic_results": [
                {
                    "title": "Widget",
                    "link": "https://www.ebay.com/itm/123",
                    "product_id": "123",
                    "serpapi_link": "https://serpapi.com/search.json?engine=ebay_product&product_id=123",
                    "price": {"raw": "$9.99", "extracted": 9.99},
                }
            ]
        }
        rows = extract_ebay_search_results(payload, limit=5)
        self.assertEqual(rows[0]["url"], "https://www.ebay.com/itm/123")
        self.assertEqual(rows[0]["product_id"], "123")


class SerpApiEbayProductTests(unittest.TestCase):
    def test_extract_summary_counts_variations(self):
        payload = {
            "product_results": {
                "product_id": "999",
                "product_link": "https://www.ebay.com/itm/999",
                "title": "Gadget",
                "buy": {"options": ["buy_it_now"], "buy_it_now": {"price": {"amount": 10, "currency": "USD"}}},
                "shipping": {"status": "available"},
                "variations": {"menus": [{"id": 1}], "combinations": [{}, {}]},
                "media": [
                    {"type": "image", "image": [{"link": "https://i.ebayimg.com/x.jpg", "size": {"width": 1, "height": 1}}]}
                ],
            }
        }
        s = extract_ebay_product_summary(payload)
        self.assertIsNotNone(s)
        self.assertEqual(s["variation_counts"]["variation_menus"], 1)
        self.assertEqual(s["variation_counts"]["variation_combinations"], 2)
        self.assertEqual(s["image_urls"][0], "https://i.ebayimg.com/x.jpg")

    def test_compact_related_respects_limit(self):
        raw = [{"product_id": str(i), "title": "t", "product_link": None, "price": None} for i in range(20)]
        out = _compact_related(raw)
        self.assertEqual(len(out), 12)


class SerpApiEbaySearchMainTests(unittest.TestCase):
    def test_main_requires_query_or_category(self):
        with patch.object(sys, "argv", ["serpapi_ebay_search.py", "{}"]), patch(
            "serpapi_ebay_search.load_config"
        ):
            rc = ebay_search_main()
        self.assertEqual(rc, 1)

    def test_main_smoke_categories_only(self):
        fake_payload = {
            "organic_results": [],
            "search_metadata": {"status": "Success"},
            "categories": [{"name": "All"}],
            "search_information": {"total_results": 0},
        }

        def fake_req(params):
            self.assertEqual(params["engine"], "ebay")
            self.assertEqual(params["category_id"], "9355")
            self.assertEqual(params["no_cache"], "false")
            return fake_payload

        with patch.object(
            sys, "argv", ["serpapi_ebay_search.py", json.dumps({"category_id": "9355"})]
        ), patch("serpapi_ebay_search.load_config"), patch(
            "serpapi_ebay_search.request_serpapi", side_effect=fake_req
        ), patch(
            "serpapi_ebay_search.get_proxy_enabled", return_value=False
        ):
            rc = ebay_search_main()
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
