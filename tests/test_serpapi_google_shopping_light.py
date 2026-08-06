#!/usr/bin/env python3
"""Regression coverage for the SerpApi Google Shopping Light tool."""

import json
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT / "skills"))
sys.path.insert(0, str(ROOT / "lib"))

import serpapi_client
from serpapi_google_shopping_light import (
    GOOGLE_SHOPPING_LIGHT_TIMEOUT,
    _google_shopping_light_request,
    extract_shopping_results,
    main,
)


def shopping_payload():
    return {
        "search_metadata": {
            "id": "shopping-light-123",
            "status": "Success",
            "cached": True,
            "google_shopping_light_url": "https://www.google.com/search?udm=28&q=headphones",
        },
        "search_parameters": {
            "engine": "google_shopping_light",
            "q": "noise cancelling headphones",
            "location": "Portland, Oregon, United States",
        },
        "search_information": {
            "query_displayed": "noise cancelling headphones",
            "shopping_results_state": "Results for exact spelling",
        },
        "shopping_results": [
            {
                "position": 1,
                "title": "Acme Quiet 5 Wireless Headphones",
                "product_link": "https://www.google.com/shopping/product/quiet-5",
                "product_id": "quiet-5",
                "source": "Audio Shop",
                "multiple_sources": True,
                "price": "$199.99",
                "extracted_price": 199.99,
                "old_price": "$249.99",
                "extracted_old_price": 249.99,
                "rating": 4.8,
                "reviews": 1500,
                "delivery": "Free delivery",
                "thumbnail": "https://images.example/quiet-5.jpg",
                "serpapi_thumbnail": "https://serpapi.example/quiet-5.jpg",
                "tag": "20% OFF",
                "extensions": ["20% OFF", "Black", "Bluetooth"],
            }
        ],
        "inline_shopping_results": [
            {
                "position": 1,
                "block_position": "top",
                "title": "Acme Quiet 4 Headphones",
                "link": "https://retailer.example/quiet-4",
                "source": "Retailer Example",
                "price": "$149.00",
                "extracted_price": 149,
                "rating": 4.6,
                "reviews": 800,
                "thumbnail": "https://images.example/quiet-4.jpg",
                "installment": {
                    "price": "$24.84",
                    "extracted_price": 24.84,
                    "period": 6,
                },
            }
        ],
        "categorized_shopping_results": [
            {
                "title": "Noise-cancelling headphones",
                "shopping_results": [
                    {
                        "position": 1,
                        "title": "Acme Quiet 5 Wireless Headphones",
                        "product_link": "https://www.google.com/shopping/product/quiet-5",
                        "product_id": "quiet-5",
                        "source": "Audio Shop",
                        "price": "$199.99",
                        "extracted_price": 199.99,
                    }
                ],
            }
        ],
        "serpapi_pagination": {
            "current": 1,
            "next": "https://serpapi.com/search?engine=google_shopping_light&q=headphones&start=10",
            "previous": "https://serpapi.com/search?engine=google_shopping_light&q=headphones&start=0",
        },
    }


def run_main(arguments, response, config=None):
    stdout = StringIO()
    argv = ["serpapi_google_shopping_light.py", json.dumps(arguments)]
    config = config or {}

    def config_lookup(key, default=""):
        return config.get(key, default)

    with patch("serpapi_google_shopping_light.load_config"), patch(
        "serpapi_google_shopping_light.get_config_value",
        side_effect=config_lookup,
    ), patch(
        "serpapi_google_shopping_light._google_shopping_light_request",
        side_effect=response if isinstance(response, Exception) else None,
        return_value=None if isinstance(response, Exception) else response,
    ) as request, patch.object(sys, "argv", argv), redirect_stdout(stdout):
        exit_code = main()
    return exit_code, json.loads(stdout.getvalue()), request


def test_normalization_combines_sections_and_deduplicates_products():
    results, counts = extract_shopping_results(shopping_payload(), max_results=10)

    assert counts == {
        "provider_shopping_results_count": 1,
        "provider_inline_results_count": 1,
        "provider_category_groups_count": 1,
        "provider_categorized_results_count": 1,
        "provider_results_count": 3,
    }
    assert len(results) == 2
    assert results[0] == {
        "position": 1,
        "provider_position": 1,
        "section": "shopping",
        "title": "Acme Quiet 5 Wireless Headphones",
        "url": "https://www.google.com/shopping/product/quiet-5",
        "product_link": "https://www.google.com/shopping/product/quiet-5",
        "product_id": "quiet-5",
        "source": "Audio Shop",
        "multiple_sources": True,
        "price": "$199.99",
        "extracted_price": 199.99,
        "old_price": "$249.99",
        "extracted_old_price": 249.99,
        "rating": 4.8,
        "reviews": 1500,
        "delivery": "Free delivery",
        "thumbnail": "https://images.example/quiet-5.jpg",
        "serpapi_thumbnail": "https://serpapi.example/quiet-5.jpg",
        "tag": "20% OFF",
        "extensions": ["20% OFF", "Black", "Bluetooth"],
    }
    assert results[1]["position"] == 2
    assert results[1]["section"] == "inline"
    assert results[1]["url"] == "https://retailer.example/quiet-4"
    assert results[1]["installment"] == {
        "price": "$24.84",
        "extracted_price": 24.84,
        "period": 6,
    }


def test_normalization_encodes_illegal_spaces_without_double_encoding_urls():
    payload = {
        "shopping_results": [
            {
                "title": "NVIDIA RTX 4090",
                "product_link": (
                    "https://www.google.com/search?ibp=oshop&q=nvidia rtx 4090"
                    "&prds=productid:11568490360883240100,headlineOfferDocid:11568490360883240100"
                    "&hl=en&coupon=save%20now&label=50% off"
                ),
                "source": "Example Retailer",
                "price": "$1,999.99",
            }
        ]
    }

    results, _counts = extract_shopping_results(payload, max_results=5)

    assert results[0]["url"] == (
        "https://www.google.com/search?ibp=oshop&q=nvidia%20rtx%204090"
        "&prds=productid:11568490360883240100,headlineOfferDocid:11568490360883240100"
        "&hl=en&coupon=save%20now&label=50%25%20off"
    )
    assert results[0]["product_link"] == results[0]["url"]
    assert " " not in results[0]["url"]
    assert "%2520" not in results[0]["url"]


def test_search_uses_documented_filters_and_mode_default_location():
    exit_code, result, request = run_main(
        {
            "query": "noise cancelling headphones",
            "country": "us",
            "language": "en",
            "google_domain": "google.com",
            "min_price": 100,
            "max_price": 250,
            "sort_by": "price_low_to_high",
            "free_shipping": True,
            "on_sale": True,
            "small_business": True,
            "start": 10,
            "device": "mobile",
            "no_cache": True,
            "max_results": 10,
        },
        shopping_payload(),
        config={"JARVIS_DEFAULT_LOCATION": "Portland, Oregon, United States"},
    )

    assert exit_code == 0
    assert result["ok"] is True
    assert request.call_args.args[0] == {
        "engine": "google_shopping_light",
        "q": "noise cancelling headphones",
        "google_domain": "google.com",
        "start": 10,
        "device": "mobile",
        "no_cache": "true",
        "location": "Portland, Oregon, United States",
        "gl": "us",
        "hl": "en",
        "min_price": 100,
        "max_price": 250,
        "sort_by": "1",
        "free_shipping": "true",
        "on_sale": "true",
        "small_business": "true",
    }
    data = result["data"]
    assert data["location_source"] == "jarvis_default_location"
    assert data["provider_location_used"] == "Portland, Oregon, United States"
    assert data["results_count"] == 2
    assert data["provider_results_count"] == 3
    assert data["merchants"] == ["Audio Shop", "Retailer Example"]
    assert data["lowest_returned_price"]["extracted_price"] == 149
    assert data["top_url"] == "https://www.google.com/shopping/product/quiet-5"
    assert data["next_start"] == 10
    assert "SerpApi" not in data["comparison_note"]
    assert "Lowest returned price: $149.00" in result["speech"]


def test_postal_fallback_and_provider_default_are_explicit():
    exit_code, result, request = run_main(
        {"query": "cordless drill"},
        shopping_payload(),
        config={"JARVIS_DEFAULT_POSTAL_CODE": "97201"},
    )
    assert exit_code == 0
    assert request.call_args.args[0]["location"] == "97201"
    assert result["data"]["location_source"] == "jarvis_default_postal_code"

    exit_code, result, request = run_main(
        {"query": "cordless drill"}, shopping_payload()
    )
    assert exit_code == 0
    assert "location" not in request.call_args.args[0]
    assert result["data"]["location_source"] == "provider_default"


def test_uule_and_extra_params_cannot_override_core_contract():
    exit_code, _result, request = run_main(
        {
            "query": "robot vacuum",
            "uule": "w+CAIQICImU2FuIEZyYW5jaXNjbyxDYWxpZm9ybmlhLFVuaXRlZCBTdGF0ZXM",
            "extra_params": {
                "shoprs": "advanced-filter-token",
                "engine": "google",
                "q": "override",
                "async": "true",
                "output": "html",
                "max_price": 1,
                "start": 999,
            },
        },
        shopping_payload(),
    )

    assert exit_code == 0
    params = request.call_args.args[0]
    assert params["engine"] == "google_shopping_light"
    assert params["q"] == "robot vacuum"
    assert params["start"] == 0
    assert params["uule"].startswith("w+CAIQ")
    assert params["shoprs"] == "advanced-filter-token"
    assert "async" not in params
    assert "output" not in params
    assert "max_price" not in params


def test_invalid_inputs_fail_before_network():
    cases = (
        ({}, "query"),
        ({"query": "laptop", "location": "Austin", "uule": "encoded"}, "cannot"),
        ({"query": "laptop", "country": "usa"}, "two-letter"),
        ({"query": "laptop", "device": "watch"}, "device"),
        ({"query": "laptop", "sort_by": "rating"}, "sort_by"),
        ({"query": "laptop", "min_price": -1}, "min_price"),
        ({"query": "laptop", "min_price": 500, "max_price": 100}, "greater"),
        ({"query": "laptop", "start": -1}, "start"),
        ({"query": "laptop", "extra_params": []}, "object"),
    )
    for arguments, expected in cases:
        exit_code, result, request = run_main(arguments, shopping_payload())
        assert exit_code == 1
        assert expected in result["error"]
        request.assert_not_called()


def test_raw_payload_is_opt_in_and_empty_results_are_successful():
    exit_code, result, _request = run_main(
        {"query": "headphones"}, shopping_payload()
    )
    assert exit_code == 0
    assert "raw" not in result["data"]

    empty_payload = {
        "shopping_results": [],
        "inline_shopping_results": [],
        "categorized_shopping_results": [],
    }
    exit_code, result, _request = run_main(
        {"query": "unlikely product", "include_raw": True}, empty_payload
    )
    assert exit_code == 0
    assert result["data"]["raw"] == empty_payload
    assert "no products" in result["speech"]


def test_timeout_returns_provider_specific_error():
    exit_code, result, _request = run_main(
        {"query": "headphones"}, TimeoutError("timed out")
    )
    assert exit_code == 1
    assert result["error"] == "SerpApi Google Shopping Light request timed out."


def test_shared_request_is_proxy_capable_but_manifest_defaults_off():
    with patch("serpapi_google_shopping_light.request_serpapi", return_value={}) as request:
        _google_shopping_light_request(
            {"engine": "google_shopping_light", "q": "headphones"}
        )
    assert request.call_args.kwargs == {
        "timeout": GOOGLE_SHOPPING_LIGHT_TIMEOUT,
        "use_proxy": True,
        "fallback_on_proxy_fail": True,
    }
    manifest = json.loads(
        (ROOT / "skills" / "serpapi_google_shopping_light.tool.json").read_text()
    )
    assert manifest["proxy_policy"] == "off"
    assert manifest["availability"]["all_of_env"] == ["SERP_API_KEY"]


def test_status_diagnostics_register_google_shopping_light_engine():
    assert serpapi_client.serpapi_engines_for_tool(
        "serpapi_google_shopping_light", {"query": "headphones"}
    ) == ("google_shopping_light",)
