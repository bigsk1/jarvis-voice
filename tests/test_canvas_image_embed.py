#!/usr/bin/env python3
"""Regression tests for Canvas image embedding support."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import skills.canvas as canvas_module  # noqa: E402
from skills.canvas import _embed_image_markdown, create_page, update_page  # noqa: E402


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


def test_embed_image_markdown_does_not_confuse_plain_stash_note_with_image():
    stash_ref = "stash://space_20260622_205701_7d28320e/f_c8f620d42d44"
    content = f"# Bug Identification\n\nStash reference preserved: {stash_ref}"

    result = _embed_image_markdown(content, stash_ref, "Boxelder bug photo")

    assert result.startswith(f"![Boxelder bug photo]({stash_ref})")
    assert f"Stash reference preserved: {stash_ref}" in result
    assert result.count(stash_ref) == 2


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


def test_canvas_page_url_uses_public_url(monkeypatch):
    def fake_config(key, default=None):
        values = {
            "CANVAS_INTERNAL_URL": "http://localhost:8890",
            "CANVAS_PUBLIC_URL": "http://203.0.113.10:8890/",
        }
        return values.get(key, default)

    monkeypatch.setattr(canvas_module, "get_config_value", fake_config)

    assert canvas_module.get_canvas_internal_url() == "http://localhost:8890"
    assert canvas_module.get_canvas_public_url() == "http://203.0.113.10:8890"
    assert (
        canvas_module.get_canvas_page_url("page_20260331_121401")
        == "http://203.0.113.10:8890/page_20260331_121401"
    )


def test_canvas_public_url_falls_back_when_blank(monkeypatch):
    def fake_config(key, default=None):
        values = {
            "CANVAS_INTERNAL_URL": "http://localhost:8890/",
            "CANVAS_PUBLIC_URL": "   ",
        }
        return values.get(key, default)

    monkeypatch.setattr(canvas_module, "get_config_value", fake_config)

    assert canvas_module.get_canvas_public_url() == "http://localhost:8890"


def test_create_page_updates_existing_page_with_same_title():
    original_health = canvas_module.check_canvas_health
    original_api = canvas_module.api_request
    original_save = canvas_module.save_to_memory
    original_config = canvas_module.get_config_value

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

    def fake_config(key, default=None):
        values = {
            "CANVAS_INTERNAL_URL": "http://localhost:8890",
            "CANVAS_PUBLIC_URL": "http://canvas.lan:8890/",
        }
        return values.get(key, default)

    try:
        canvas_module.check_canvas_health = fake_health
        canvas_module.api_request = fake_api
        canvas_module.save_to_memory = lambda page: None
        canvas_module.get_config_value = fake_config

        result = create_page(
            "Godzilla Sleep Pajama Pants (B0DT78LB7Z)",
            "Price: $22.50",
            tags=["shopping", "amazon"],
        )
    finally:
        canvas_module.check_canvas_health = original_health
        canvas_module.api_request = original_api
        canvas_module.save_to_memory = original_save
        canvas_module.get_config_value = original_config

    assert result["ok"] is True
    assert result["data"]["page_id"] == "page_existing"
    assert result["data"]["url"] == "http://canvas.lan:8890/page_existing"
    assert result["data"]["base_url"] == "http://canvas.lan:8890"
    assert result["data"]["updated_existing"] is True
    assert not any(method == "POST" and endpoint == "/pages" for method, endpoint, _ in calls)


def test_create_page_rejects_empty_content_before_api_call(monkeypatch):
    calls = []

    monkeypatch.setattr(canvas_module, "check_canvas_health", lambda: True)

    def fake_api(method, endpoint, data=None):
        calls.append((method, endpoint, data))
        raise AssertionError(f"Unexpected API call: {method} {endpoint}")

    monkeypatch.setattr(canvas_module, "api_request", fake_api)

    result = create_page(
        "Hillsboro Kids Activities - July 15-16, 2026",
        "",
        tags=["activities"],
        source_query="activities 7/15-7/16 nephew 10yo Hillsboro",
        pinned=True,
    )

    assert result["ok"] is False
    assert "requires content or an image" in result["error"]
    assert calls == []


def test_update_page_normalizes_literal_newline_escapes(monkeypatch):
    calls = []

    monkeypatch.setattr(canvas_module, "check_canvas_health", lambda: True)
    monkeypatch.setattr(canvas_module, "save_to_memory", lambda page: None)

    def fake_api(method, endpoint, data=None):
        calls.append((method, endpoint, data))
        return {
            "id": "page_existing",
            "title": "Research",
            "content": data["content"],
            "tags": [],
        }

    monkeypatch.setattr(canvas_module, "api_request", fake_api)

    result = update_page("page_existing", content="Line 1\\nLine 2")

    assert result["ok"] is True
    assert calls == [
        (
            "PUT",
            "/pages/page_existing",
            {"content": "Line 1\nLine 2"},
        )
    ]
