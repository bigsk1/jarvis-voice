#!/usr/bin/env python3
"""Regression tests for the SerpApi Google Immersive Product tool."""

from __future__ import annotations

import json
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT / "skills"))
sys.path.insert(0, str(ROOT / "lib"))

from serpapi_google_immersive_product import (  # noqa: E402
    SERPAPI_TIMEOUT,
    extract_product_results,
    main,
    normalize_output_format,
    normalize_page_token,
)


PAGE_TOKEN = "opaque-product-token+/="
NEXT_TOKEN = "opaque-store-page-token_-="


def product_payload() -> dict:
    return {
        "search_metadata": {
            "id": "immersive-123",
            "status": "Success",
            "cached": True,
            "google_immersive_product_url": "https://www.google.com/shopping/product/123",
        },
        "product_results": {
            "title": "Acme Quiet 5 Wireless Headphones",
            "brand": "Acme",
            "rating": 4.8,
            "reviews": 1500,
            "price_range": "$149–$199",
            "thumbnails": ["https://images.example/quiet-5.jpg"],
            "stores": [
                {
                    "name": "Audio Shop",
                    "link": "https://retailer.example/quiet-5",
                    "logo": "https://images.example/audio-shop.png",
                    "rating": 4.7,
                    "reviews": 800,
                    "price": "$149.00",
                    "extracted_price": 149,
                    "shipping": "Free delivery",
                    "total": "$149.00",
                    "details_and_offers": ["Free returns within 30 days"],
                }
            ],
            "stores_next_page_token": NEXT_TOKEN,
            "about_the_product": {
                "description": "Wireless headphones with adaptive noise cancellation.",
                "features": [{"title": "Battery", "description": "30 hours"}],
            },
            "top_insights": [
                {"title": "Sound quality", "pros": ["Clear and detailed"]}
            ],
            "ratings": [{"stars": 5, "count": 1100}],
            "user_reviews": [
                {"title": "Excellent", "text": "Comfortable for long sessions.", "rating": 5}
            ],
            "videos": [{"title": "Product overview", "link": "https://video.example/1"}],
            "more_options": [
                {
                    "title": "Acme Quiet 5 in blue",
                    "serpapi_link": (
                        "https://serpapi.com/search.json?engine=google_immersive_product"
                        "&page_token=blue-variant-token"
                    ),
                }
            ],
            "variants": [
                {
                    "title": "Color",
                    "items": [
                        {
                            "name": "Blue",
                            "serpapi_link": (
                                "https://serpapi.com/search.json?engine=google_immersive_product"
                                "&page_token=blue-variant-token"
                            ),
                        }
                    ],
                }
            ],
        },
        "related_searches": [{"query": "Acme Quiet 5 case"}],
    }


def run_main(arguments: dict, response) -> tuple[int, dict, object]:
    stdout = StringIO()
    argv = ["serpapi_google_immersive_product.py", json.dumps(arguments)]
    with patch("serpapi_google_immersive_product.load_config"), patch(
        "serpapi_google_immersive_product.get_proxy_enabled", return_value=False
    ), patch(
        "serpapi_google_immersive_product.request_serpapi",
        side_effect=response if isinstance(response, Exception) else None,
        return_value=None if isinstance(response, Exception) else response,
    ) as request, patch.object(sys, "argv", argv), redirect_stdout(stdout):
        exit_code = main()
    return exit_code, json.loads(stdout.getvalue()), request


def test_page_token_accepts_opaque_value_or_official_serpapi_handoff_url():
    assert normalize_page_token(PAGE_TOKEN) == PAGE_TOKEN
    assert normalize_page_token(
        "https://serpapi.com/search.json?engine=google_immersive_product"
        "&page_token=opaque-product-token%2B%2F%3D"
    ) == PAGE_TOKEN


@pytest.mark.parametrize(
    "value",
    ["", "token with spaces", "https://example.com/search?page_token=abc"],
)
def test_page_token_rejects_missing_modified_or_non_serpapi_values(value):
    with pytest.raises(ValueError):
        normalize_page_token(value)


def test_output_format_maps_markdown_to_provider_md():
    assert normalize_output_format("json") == ("json", "json")
    assert normalize_output_format("html") == ("html", "html")
    assert normalize_output_format("markdown") == ("markdown", "md")


def test_extractor_preserves_rich_sections_and_variant_handoff_tokens():
    data = extract_product_results(product_payload(), max_stores=13, max_reviews=10)

    assert data["product_summary"]["title"] == "Acme Quiet 5 Wireless Headphones"
    assert data["stores"][0]["url"] == "https://retailer.example/quiet-5"
    assert data["stores"][0]["details_and_offers"] == ["Free returns within 30 days"]
    assert data["about_the_product"]["features"][0]["title"] == "Battery"
    assert data["user_reviews"][0]["text"] == "Comfortable for long sessions."
    assert data["more_options"][0]["page_token"] == "blue-variant-token"
    assert data["variants"][0]["items"][0]["page_token"] == "blue-variant-token"


def test_main_uses_one_detail_request_and_returns_store_pagination():
    exit_code, result, request = run_main(
        {"page_token": PAGE_TOKEN, "more_stores": True},
        product_payload(),
    )

    assert exit_code == 0
    assert result["ok"] is True
    request.assert_called_once_with(
        {
            "engine": "google_immersive_product",
            "page_token": PAGE_TOKEN,
            "more_stores": "true",
            "no_cache": "false",
        },
        timeout=SERPAPI_TIMEOUT,
    )
    data = result["data"]
    assert data["product_summary"]["brand"] == "Acme"
    assert data["stores_count"] == 1
    assert data["stores_next_page_token"] == NEXT_TOKEN
    assert data["has_more_stores"] is True
    assert data["top_url"] == "https://retailer.example/quiet-5"
    assert data["top_image_url"] == "https://images.example/quiet-5.jpg"
    assert data["serpapi_searches_used"] == 1
    assert data["external_content_trust"] == "untrusted"
    assert "raw" not in data


def test_next_store_page_and_extra_params_cannot_override_core_contract():
    exit_code, _result, request = run_main(
        {
            "page_token": PAGE_TOKEN,
            "next_page_token": NEXT_TOKEN,
            "more_stores": False,
            "no_cache": True,
            "extra_params": {
                "device": "mobile",
                "engine": "google",
                "page_token": "override",
                "next_page_token": "override",
                "more_stores": "true",
                "output": "html",
                "async": "true",
            },
        },
        product_payload(),
    )

    assert exit_code == 0
    assert request.call_args.args[0] == {
        "engine": "google_immersive_product",
        "page_token": PAGE_TOKEN,
        "more_stores": "false",
        "no_cache": "true",
        "next_page_token": NEXT_TOKEN,
        "device": "mobile",
    }


def test_markdown_uses_provider_text_response():
    stdout = StringIO()
    argv = [
        "serpapi_google_immersive_product.py",
        json.dumps({"page_token": PAGE_TOKEN, "output_format": "markdown"}),
    ]
    with patch("serpapi_google_immersive_product.load_config"), patch(
        "serpapi_google_immersive_product.request_serpapi_text",
        return_value="# Product details",
    ) as request, patch.object(sys, "argv", argv), redirect_stdout(stdout):
        exit_code = main()

    result = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert result["data"]["output_format"] == "markdown"
    assert result["data"]["content"] == "# Product details"
    request.assert_called_once_with(
        {
            "engine": "google_immersive_product",
            "page_token": PAGE_TOKEN,
            "more_stores": "true",
            "no_cache": "false",
        },
        "md",
        timeout=SERPAPI_TIMEOUT,
    )


def test_invalid_input_and_timeout_return_clear_errors():
    exit_code, result, request = run_main({}, product_payload())
    assert exit_code == 1
    assert result["error"] == "Parameter 'page_token' is required."
    request.assert_not_called()

    exit_code, result, _request = run_main(
        {"page_token": PAGE_TOKEN}, TimeoutError("timed out")
    )
    assert exit_code == 1
    assert result["error"] == "SerpApi Google Immersive Product request timed out."


def test_manifest_declares_soft_shopping_light_prerequisite():
    manifest = json.loads(
        (ROOT / "skills" / "serpapi_google_immersive_product.tool.json").read_text()
    )
    assert manifest["prerequisite_tools"] == ["serpapi_google_shopping_light"]
    assert manifest["proxy_policy"] == "off"
    assert manifest["availability"]["all_of_env"] == ["SERP_API_KEY"]
