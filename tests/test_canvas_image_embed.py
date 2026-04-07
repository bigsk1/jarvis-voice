#!/usr/bin/env python3
"""Regression tests for Canvas image embedding support."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from skills.canvas import _embed_image_markdown  # noqa: E402


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
