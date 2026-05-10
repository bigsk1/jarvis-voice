#!/usr/bin/env python3
"""Regression tests for serpapi_home_depot helpers."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

from serpapi_home_depot import extract_home_depot_results, extract_home_depot_product, main, normalize_sort


class SerpApiHomeDepotTests(unittest.TestCase):
    def test_normalize_sort_maps_us_friendly_values(self):
        key, value = normalize_sort("us", "price_low")
        self.assertEqual(key, "hd_sort")
        self.assertEqual(value, "price_low_to_high")

    def test_normalize_sort_maps_canada_friendly_values(self):
        key, value = normalize_sort("ca", "top_rated")
        self.assertEqual(key, "sort")
        self.assertEqual(value, "reviewAvgRating")

    def test_extract_home_depot_results_preserves_product_fields(self):
        payload = {
            "products": [
                {
                    "position": 1,
                    "product_id": "304602833",
                    "title": "Lillith Navy Blue Mid Century Modern Chair",
                    "thumbnails": [[
                        "https://images.example.com/chair-small.jpg",
                        "https://images.example.com/chair-large.jpg",
                    ]],
                    "link": "https://www.homedepot.com/p/example/304602833",
                    "serpapi_link": "https://serpapi.com/search.json?engine=home_depot_product&product_id=304602833",
                    "model_number": "LK-LGFSP1GU3051",
                    "brand": "Lifestyle Solutions",
                    "rating": 4.393,
                    "reviews": 430,
                    "price": 224.63,
                    "price_was": 249.0,
                    "delivery": {"free": True},
                    "pickup": {"free_ship_to_store": True},
                }
            ]
        }

        results = extract_home_depot_results(payload, limit=5)
        self.assertEqual(
            results[0]["url"],
            "https://www.homedepot.com/p/example/304602833",
        )
        self.assertEqual(results[0]["product_id"], "304602833")
        self.assertEqual(results[0]["brand"], "Lifestyle Solutions")
        self.assertEqual(results[0]["model_number"], "LK-LGFSP1GU3051")
        self.assertEqual(results[0]["thumbnail"], "https://images.example.com/chair-small.jpg")
        self.assertEqual(results[0]["image_url"], "https://images.example.com/chair-large.jpg")
        self.assertEqual(results[0]["price_formatted"], "$224.63")
        self.assertEqual(results[0]["delivery"], {"free": True})

    def test_extract_home_depot_product_preserves_detail_images(self):
        payload = {
            "product_results": {
                "product_id": "206667220",
                "title": "12-Cup Programmable Coffee Maker",
                "description": "Thermal carafe coffee maker.",
                "link": "https://www.homedepot.com/p/example/206667220",
                "model_number": "CM2035B",
                "brand": {"name": "BLACK+DECKER"},
                "rating": "3.1783",
                "reviews": "589",
                "price": 62.99,
                "images": [[
                    "https://images.example.com/coffee-65.jpg",
                    "https://images.example.com/coffee-1000.jpg",
                ]],
                "highlights": ["Serves up to 12 cups"],
            }
        }

        product = extract_home_depot_product(payload)
        self.assertEqual(product["product_id"], "206667220")
        self.assertEqual(product["brand"], "BLACK+DECKER")
        self.assertEqual(product["thumbnail"], "https://images.example.com/coffee-65.jpg")
        self.assertEqual(product["image_url"], "https://images.example.com/coffee-1000.jpg")
        self.assertEqual(product["price_formatted"], "$62.99")

    def test_extract_home_depot_results_formats_canada_currency(self):
        payload = {
            "products": [
                {
                    "product_id": "1001580444",
                    "title": "Graphite Sling Stacking Patio Dining Chair",
                    "link": "https://www.homedepot.ca/product/example/1001580444",
                    "price": 16.98,
                    "currency": "CAD",
                    "thumbnails": [["https://images.example.com/chair.jpg"]],
                }
            ]
        }

        results = extract_home_depot_results(payload, limit=5, country="ca")
        self.assertEqual(results[0]["price_formatted"], "CAD 16.98")
        self.assertEqual(results[0]["thumbnail"], "https://images.example.com/chair.jpg")

    def test_extract_rewrites_apionline_to_www_storefront_us(self):
        payload = {
            "products": [
                {
                    "product_id": "100074405",
                    "title": "Hardie Panel",
                    "link": "https://apionline.homedepot.com/p/James-Hardie-Example/100074405",
                    "thumbnails": [["https://images.example.com/p.jpg"]],
                }
            ]
        }
        results = extract_home_depot_results(payload, limit=5, country="us")
        self.assertEqual(
            results[0]["url"],
            "https://www.homedepot.com/p/James-Hardie-Example/100074405",
        )

    def test_extract_rewrites_apionline_to_www_storefront_ca(self):
        payload = {
            "products": [
                {
                    "product_id": "1001580444",
                    "title": "Chair",
                    "link": "https://apionline.homedepot.ca/p/example-chair/1001580444",
                    "thumbnails": [["https://images.example.com/c.jpg"]],
                }
            ]
        }
        results = extract_home_depot_results(payload, limit=5, country="ca")
        self.assertEqual(
            results[0]["url"],
            "https://www.homedepot.ca/p/example-chair/1001580444",
        )

    def test_extract_upgrades_http_homedepot_to_https(self):
        payload = {
            "products": [
                {
                    "product_id": "1",
                    "title": "x",
                    "link": "http://www.homedepot.com/p/a/1",
                    "thumbnails": [["https://images.example.com/i.jpg"]],
                }
            ]
        }
        results = extract_home_depot_results(payload, limit=5)
        self.assertEqual(results[0]["url"], "https://www.homedepot.com/p/a/1")

    def test_extract_home_depot_product_rewrites_apionline(self):
        payload = {
            "product_results": {
                "product_id": "206667220",
                "title": "Coffee Maker",
                "link": "https://apionline.homedepot.com/p/slug/206667220",
                "images": [["https://images.example.com/z.jpg"]],
            }
        }
        product = extract_home_depot_product(payload, country="us")
        self.assertEqual(product["url"], "https://www.homedepot.com/p/slug/206667220")

    def test_main_defaults_us_delivery_zip_from_env(self):
        captured = {}

        def fake_request(params, timeout=25, **kwargs):
            captured["params"] = dict(params)
            captured["timeout"] = timeout
            return {"products": []}

        with patch.object(sys, "argv", ["serpapi_home_depot.py", '{"query":"drill"}']), patch(
            "serpapi_home_depot.load_config"
        ), patch("serpapi_home_depot.get_config_value", return_value="97201"), patch(
            "serpapi_home_depot.request_serpapi", side_effect=fake_request
        ):
            self.assertEqual(main(), 0)

        self.assertEqual(captured["params"]["delivery_zip"], "97201")
        self.assertEqual(captured["params"]["no_cache"], "false")
        self.assertEqual(captured["timeout"], 90)

    def test_main_does_not_fetch_product_details_by_default(self):
        calls = []

        def fake_request(params, timeout=25, **kwargs):
            calls.append(dict(params))
            return {
                "products": [
                    {
                        "product_id": "341725053",
                        "title": "Milorganite Fertilizer",
                        "link": "https://www.homedepot.com/p/example/341725053",
                        "thumbnails": [["https://images.example.com/milorganite.jpg"]],
                    }
                ]
            }

        with patch.object(sys, "argv", ["serpapi_home_depot.py", '{"query":"Milorganite"}']), patch(
            "serpapi_home_depot.load_config"
        ), patch("serpapi_home_depot.get_config_value", return_value="97201"), patch(
            "serpapi_home_depot.request_serpapi", side_effect=fake_request
        ):
            self.assertEqual(main(), 0)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["engine"], "home_depot")
        self.assertEqual(calls[0]["no_cache"], "false")

    def test_main_can_lookup_product_id_details_without_query(self):
        captured = {}

        def fake_request(params, timeout=25, **kwargs):
            captured["params"] = dict(params)
            captured["timeout"] = timeout
            return {
                "product_results": {
                    "product_id": "206667220",
                    "title": "12-Cup Programmable Coffee Maker",
                    "link": "https://www.homedepot.com/p/example/206667220",
                    "price": 62.99,
                    "images": [["https://images.example.com/coffee.jpg"]],
                }
            }

        with patch.object(sys, "argv", ["serpapi_home_depot.py", '{"product_id":"206667220"}']), patch(
            "serpapi_home_depot.load_config"
        ), patch("serpapi_home_depot.get_config_value", return_value="97201"), patch(
            "serpapi_home_depot.request_serpapi", side_effect=fake_request
        ):
            self.assertEqual(main(), 0)

        self.assertEqual(captured["params"]["engine"], "home_depot_product")
        self.assertEqual(captured["params"]["product_id"], "206667220")
        self.assertEqual(captured["params"]["delivery_zip"], "97201")
        self.assertEqual(captured["params"]["no_cache"], "false")
        self.assertEqual(captured["timeout"], 90)

    def test_main_keeps_explicit_delivery_zip(self):
        captured = {}

        def fake_request(params, timeout=25, **kwargs):
            captured["params"] = dict(params)
            captured["timeout"] = timeout
            return {"products": []}

        input_json = '{"query":"drill","delivery_zip":"97006"}'
        with patch.object(sys, "argv", ["serpapi_home_depot.py", input_json]), patch(
            "serpapi_home_depot.load_config"
        ), patch("serpapi_home_depot.get_config_value", return_value="97201"), patch(
            "serpapi_home_depot.request_serpapi", side_effect=fake_request
        ):
            self.assertEqual(main(), 0)

        self.assertEqual(captured["params"]["delivery_zip"], "97006")
        self.assertEqual(captured["timeout"], 90)

    def test_main_does_not_apply_us_zip_to_canada_search(self):
        captured = {}

        def fake_request(params, timeout=25, **kwargs):
            captured["params"] = dict(params)
            captured["timeout"] = timeout
            return {"products": []}

        input_json = '{"query":"chair","country":"ca"}'
        with patch.object(sys, "argv", ["serpapi_home_depot.py", input_json]), patch(
            "serpapi_home_depot.load_config"
        ), patch("serpapi_home_depot.get_config_value", return_value="97201"), patch(
            "serpapi_home_depot.request_serpapi", side_effect=fake_request
        ):
            self.assertEqual(main(), 0)

        self.assertNotIn("delivery_zip", captured["params"])
        self.assertEqual(captured["timeout"], 90)


if __name__ == "__main__":
    unittest.main()
