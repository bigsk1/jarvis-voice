#!/usr/bin/env python3
"""Regression tests for serpapi_amazon_search parameter normalization."""

import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

from serpapi_amazon_search import main, normalize_sort_by


class SerpApiAmazonSearchParamsTests(unittest.TestCase):
    def test_amazon_review_sort_mapping(self):
        key, value = normalize_sort_by("amazon", "review_score")
        self.assertEqual(key, "s")
        self.assertEqual(value, "review-rank")

    def test_amazon_price_sort_mapping(self):
        key, value = normalize_sort_by("amazon", "price_low")
        self.assertEqual(key, "s")
        self.assertEqual(value, "price-asc-rank")

    def test_amazon_product_sort_passthrough(self):
        key, value = normalize_sort_by("amazon_product", "review_score")
        self.assertEqual(key, "sort_by")
        self.assertEqual(value, "review_score")

    def test_amazon_defaults_delivery_zip_from_config(self):
        captured = {}

        def fake_request(params, timeout=25, **kwargs):
            captured["params"] = dict(params)
            return {"organic_results": []}

        with patch.object(
            sys,
            "argv",
            ["serpapi_amazon_search.py", '{"engine":"amazon","query":"usb c charger"}'],
        ), patch("serpapi_amazon_search.load_config"), patch(
            "serpapi_amazon_search.get_config_value", return_value="97201"
        ), patch(
            "serpapi_amazon_search.request_serpapi", side_effect=fake_request
        ), redirect_stdout(
            StringIO()
        ):
            self.assertEqual(main(), 0)

        self.assertEqual(captured["params"]["delivery_zip"], "97201")

    def test_amazon_keeps_explicit_delivery_zip_and_shipping_location(self):
        captured = {}

        def fake_request(params, timeout=25, **kwargs):
            captured["params"] = dict(params)
            return {"organic_results": [{"title": "Charger", "link": "https://example.com"}]}

        tool_input = (
            '{"engine":"amazon","query":"usb c charger",'
            '"delivery_zip":"97006","shipping_location":"US"}'
        )
        with patch.object(sys, "argv", ["serpapi_amazon_search.py", tool_input]), patch(
            "serpapi_amazon_search.load_config"
        ), patch("serpapi_amazon_search.get_config_value", return_value="97201"), patch(
            "serpapi_amazon_search.request_serpapi", side_effect=fake_request
        ), redirect_stdout(
            StringIO()
        ):
            self.assertEqual(main(), 0)

        self.assertEqual(captured["params"]["delivery_zip"], "97006")
        self.assertEqual(captured["params"]["shipping_location"], "US")

    def test_amazon_product_uses_domain_language_and_default_delivery_zip(self):
        captured = {}

        def fake_request(params, timeout=25, **kwargs):
            captured["params"] = dict(params)
            return {
                "product_results": {
                    "title": "Charger",
                    "asin": "B000TEST",
                    "link": "https://example.com",
                }
            }

        tool_input = (
            '{"engine":"amazon_product","asin":"B000TEST",'
            '"amazon_domain":"amazon.com","language":"en_US"}'
        )
        with patch.object(sys, "argv", ["serpapi_amazon_search.py", tool_input]), patch(
            "serpapi_amazon_search.load_config"
        ), patch("serpapi_amazon_search.get_config_value", return_value="97201"), patch(
            "serpapi_amazon_search.request_serpapi", side_effect=fake_request
        ), redirect_stdout(
            StringIO()
        ):
            self.assertEqual(main(), 0)

        self.assertEqual(captured["params"]["amazon_domain"], "amazon.com")
        self.assertEqual(captured["params"]["language"], "en_US")
        self.assertEqual(captured["params"]["delivery_zip"], "97201")

    def test_non_amazon_engine_is_rejected_before_request(self):
        stdout = StringIO()
        with patch.object(
            sys,
            "argv",
            ["serpapi_amazon_search.py", '{"engine":"google","query":"usb c charger"}'],
        ), patch("serpapi_amazon_search.load_config"), patch(
            "serpapi_amazon_search.request_serpapi"
        ) as request, redirect_stdout(stdout):
            self.assertEqual(main(), 1)

        request.assert_not_called()
        output = json.loads(stdout.getvalue())
        self.assertFalse(output["ok"])
        self.assertIn("only amazon or amazon_product", output["error"])

    def test_amazon_can_merge_localized_product_details_into_search_rows(self):
        calls = []

        def fake_request(params, timeout=25, **kwargs):
            calls.append(dict(params))
            if params["engine"] == "amazon":
                return {
                    "organic_results": [
                        {
                            "title": "Anker Charger",
                            "asin": "B000ANKER",
                            "link": "https://amazon.com/search-link-anker",
                            "price": "$24.99",
                            "rating": 4.7,
                            "reviews": 21000,
                        },
                        {
                            "title": "INIU Charger",
                            "asin": "B000INIU",
                            "link": "https://amazon.com/search-link-iniu",
                            "price": "$19.77",
                            "rating": 4.7,
                            "reviews": 1200,
                        },
                    ]
                }
            asin = params["asin"]
            product = {
                "title": f"Detail {asin}",
                "asin": asin,
                "link": f"https://amazon.com/detail/{asin}",
                "price": "$18.00" if asin == "B000INIU" else "$24.99",
                "delivery": [
                    "Prime members get FREE delivery Tomorrow"
                    if asin == "B000INIU"
                    else "FREE Prime delivery Today"
                ],
                "stock": "In Stock",
            }
            if asin == "B000ANKER":
                product["prime"] = True
            return {"product_results": product}

        tool_input = (
            '{"engine":"amazon","query":"65w charger","num_results":2,'
            '"include_product_details":true,"product_details_limit":2}'
        )
        stdout = StringIO()
        with patch.object(sys, "argv", ["serpapi_amazon_search.py", tool_input]), patch(
            "serpapi_amazon_search.load_config"
        ), patch("serpapi_amazon_search.get_config_value", return_value="97201"), patch(
            "serpapi_amazon_search.request_serpapi", side_effect=fake_request
        ), redirect_stdout(
            stdout
        ):
            self.assertEqual(main(), 0)

        output = json.loads(stdout.getvalue())
        rows = output["data"]["results"]

        self.assertEqual([call["engine"] for call in calls], [
            "amazon",
            "amazon_product",
            "amazon_product",
        ])
        self.assertEqual(calls[1]["delivery_zip"], "97201")
        self.assertEqual(rows[0]["url"], "https://amazon.com/search-link-anker")
        self.assertEqual(rows[1]["url"], "https://amazon.com/search-link-iniu")
        self.assertTrue(rows[0]["prime_eligible"])
        self.assertTrue(rows[1]["prime_eligible"])
        self.assertEqual(rows[1]["delivery"], ["Prime members get FREE delivery Tomorrow"])
        self.assertEqual(rows[1]["stock"], "In Stock")
        self.assertTrue(rows[1]["detail_enriched"])
        self.assertEqual(output["data"]["product_details_requested"], 2)
        self.assertEqual(output["data"]["product_details_succeeded"], 2)
        self.assertEqual(output["data"]["product_details_failed_asins"], [])

    def test_manifest_and_files_use_amazon_specific_identity(self):
        manifest_path = PROJECT_ROOT / "skills" / "serpapi_amazon_search.tool.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["name"], "serpapi_amazon_search")
        self.assertEqual(manifest["script"], "serpapi_amazon_search.py")
        self.assertEqual(
            manifest["parameters"]["properties"]["engine"]["enum"],
            ["amazon", "amazon_product"],
        )
        self.assertFalse((PROJECT_ROOT / "skills" / "serpapi_search.py").exists())
        self.assertFalse(
            (PROJECT_ROOT / "skills" / "serpapi_search.tool.json").exists()
        )


if __name__ == "__main__":
    unittest.main()
