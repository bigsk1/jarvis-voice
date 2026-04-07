#!/usr/bin/env python3
"""Regression tests for Canvas image embedding support."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import skills.canvas as canvas_module  # noqa: E402
from skills.canvas import _embed_image_markdown, create_page  # noqa: E402


def test_embed_image_markdown_prepends_image():
    content = "# Product Details\n\nPrice: $17.79"
    image_url = "https://example.com/product.jpg"
    result = _embed_image_markdown(content, image_url, "Amazon product image")

    assert result.startswith("![Amazon product image](https://example.com/product.jpg)")
    assert "# Product Details" in result


def test_embed_image_markdown_no_duplicate_if_url_already_present():
    content = "![Amazon product image](https://example.com/product.jpg)\n\nExisting content"
    result = _embed_image_markdown(
        content,
        "https://example.com/product.jpg",
        "Amazon product image",
    )

    assert result.count("https://example.com/product.jpg") == 1


def test_embed_image_markdown_allows_image_only_canvas_page():
    result = _embed_image_markdown("", "stash://space_xxx/file_yyy", "Generated image")
    assert result == "![Generated image](stash://space_xxx/file_yyy)"


def test_embed_image_markdown_extracts_inline_image_label():
    content = (
        "Product: Godzilla Pajama Pants\n"
        "Image: https://example.com/godzilla.jpg\n\n"
        "Price: $22.50"
    )
    result = _embed_image_markdown(content, None, "Amazon product image")

    assert result.startswith("![Amazon product image](https://example.com/godzilla.jpg)")
    assert "Image: https://example.com/godzilla.jpg" not in result
    assert "Price: $22.50" in result


def test_embed_image_markdown_extracts_multiline_image_label():
    content = (
        "Product: Godzilla Pajama Pants\n"
        "Image:\n"
        "https://example.com/godzilla.jpg\n\n"
        "Price: $22.50"
    )
    result = _embed_image_markdown(content, None, "Amazon product image")

    assert result.startswith("![Amazon product image](https://example.com/godzilla.jpg)")
    assert "Image:\nhttps://example.com/godzilla.jpg" not in result
    assert "Price: $22.50" in result


def test_create_page_updates_existing_page_with_same_title():
    original_health = canvas_module.check_canvas_health
    original_api = canvas_module.api_request
    original_save = canvas_module.save_to_memory

    calls = []

    def fake_health():
        return True

    def fake_api(method, endpoint, data=None):
        calls.append((method, endpoint, data))
        if method == "GET" and endpoint == "/pages":
            return [
                {
                    "id": "page_existing",
                    "title": "Godzilla Sleep Pajama Pants (B0DT78LB7Z)",
                    "created": "2026-04-07T10:00:00Z",
                    "updated": "2026-04-07T10:00:01Z",
                    "tags": ["shopping"],
                }
            ]
        if method == "PUT" and endpoint == "/pages/page_existing":
            return {
                "id": "page_existing",
                "title": data["title"],
                "content": data["content"],
                "tags": data["tags"],
                "updated": "2026-04-07T10:00:02Z",
            }
        raise AssertionError(f"Unexpected API call: {method} {endpoint}")

    try:
        canvas_module.check_canvas_health = fake_health
        canvas_module.api_request = fake_api
        canvas_module.save_to_memory = lambda page: None

        result = create_page(
            "Godzilla Sleep Pajama Pants (B0DT78LB7Z)",
            "Price: $22.50",
            tags=["shopping", "amazon"],
        )
    finally:
        canvas_module.check_canvas_health = original_health
        canvas_module.api_request = original_api
        canvas_module.save_to_memory = original_save

    assert result["ok"] is True
    assert result["data"]["page_id"] == "page_existing"
    assert result["data"]["updated_existing"] is True
    assert not any(method == "POST" and endpoint == "/pages" for method, endpoint, _ in calls)
