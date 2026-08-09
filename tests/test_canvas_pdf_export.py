"""Portable and publish-safe Canvas PDF regression coverage."""

from __future__ import annotations

import socket
import sys
from io import BytesIO
from pathlib import Path

import fitz
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "jarvis-canvas", ROOT / "lib"):
    sys.path.insert(0, str(path))

from server.services import pdf_export  # noqa: E402
from server.services.pdf_export import (  # noqa: E402
    build_canvas_pdf_projection,
    has_blocking_findings,
    prepare_canvas_pdf,
    validate_canvas_pdf,
)


def test_projection_replaces_nonportable_media_without_leaking_stash_ids():
    page = {
        "title": "Media notes",
        "content": (
            "![private](stash://space_secret/f_private)\n\n"
            "![public](https://images.example.com/diagram.png)\n\n"
            "https://www.youtube.com/watch?v=public123\n\n"
            "[intranet](https://127.0.0.1:9000/report)\n\n"
            "![relative](/home/boss/private.png)\n\n"
            "![reference][private-image]\n\n"
            "[private-image]: https://localhost/image.png"
        ),
        "source_query": "private source prompt",
    }

    projection = build_canvas_pdf_projection(page)

    assert "space_secret" not in projection["content_markdown"]
    assert "f_private" not in projection["content_markdown"]
    assert "Local Canvas image omitted" in projection["content_markdown"]
    assert "images.example.com/diagram.png" not in projection["content_markdown"]
    assert "youtube.com/watch" not in projection["content_markdown"]
    assert [item["kind"] for item in projection["public_media"]] == ["image", "youtube"]
    assert projection["public_media"][0]["url"] == "https://images.example.com/diagram.png"
    assert projection["public_media"][1]["url"] == "https://www.youtube.com/watch?v=public123"
    assert "127.0.0.1" not in projection["content_markdown"]
    assert "/home/boss/private.png" not in projection["content_markdown"]
    codes = {item["code"] for item in projection["findings"]}
    assert {
        "local_media_omitted",
        "public_image_linked",
        "public_youtube_linked",
        "local_link_omitted",
        "source_query_omitted",
        "unsupported_image_omitted",
    } <= codes


def test_youtube_source_list_and_labeled_source_formats_receive_cards():
    source_list = build_canvas_pdf_projection(
        {
            "title": "Source list",
            "content": (
                "Full Source URLs:\n"
                "- https://www.youtube.com/watch?v=6dSD60ZdpNY\n"
                "- https://example.com/article"
            ),
        }
    )
    labeled_source = build_canvas_pdf_projection(
        {
            "title": "Transcript summary",
            "content": (
                "**Source video:** [Why We Stopped Using RAG]"
                "(https://www.youtube.com/watch?v=l46NJXUL4PM)\n\n"
                "- YouTube video: https://www.youtube.com/watch?v=l46NJXUL4PM"
            ),
        }
    )

    assert [item["url"] for item in source_list["public_media"]] == [
        "https://www.youtube.com/watch?v=6dSD60ZdpNY"
    ]
    source_list_html = pdf_export._markdown_to_html(source_list["content_markdown"])
    assert len(list(pdf_export._MEDIA_HTML_RE.finditer(source_list_html))) == 1
    assert [item["url"] for item in labeled_source["public_media"]] == [
        "https://www.youtube.com/watch?v=l46NJXUL4PM"
    ]
    assert labeled_source["public_media"][0]["label"] == "Why We Stopped Using RAG"


def test_ordinary_inline_youtube_citation_stays_a_compact_link():
    projection = build_canvas_pdf_projection(
        {
            "title": "Inline citation",
            "content": (
                "This analysis compares the "
                "[video](https://www.youtube.com/watch?v=abcdefghijk) with the paper."
            ),
        }
    )

    assert projection["public_media"] == []
    assert "youtube.com/watch" in projection["content_markdown"]


def test_secret_like_content_hard_blocks_publish_but_email_only_warns():
    secret_projection = build_canvas_pdf_projection(
        {"title": "Credentials", "content": "api_key=sk-abcdefghijklmnopqrstuvwxyz123456"}
    )
    email_projection = build_canvas_pdf_projection(
        {"title": "Contact", "content": "Email person@example.com for details."}
    )

    assert has_blocking_findings(secret_projection)
    assert any(item["code"] == "secret_like_content" for item in secret_projection["findings"])
    assert not has_blocking_findings(email_projection)
    assert any(item["code"] == "email_address_present" for item in email_projection["findings"])

    tag_projection = build_canvas_pdf_projection(
        {"title": "Metadata", "content": "Safe body", "tags": ["password=do-not-publish"]}
    )
    assert has_blocking_findings(tag_projection)


def test_title_and_metadata_cannot_inject_local_images_into_pdf():
    page = {
        "id": "page_20260808_020202_test",
        "title": "Report\n\n![private](/home/boss/private.png)",
        "content": "Safe body.",
        "tags": ["https://localhost/private", "/home/boss/private-tag"],
        "created": "not-a-timestamp\n![private](/home/boss/created.png)",
    }

    projection, payload = prepare_canvas_pdf(page)
    inspection = validate_canvas_pdf(payload)

    assert "/home/boss" not in inspection["text"]
    assert "localhost" not in inspection["text"]
    assert any(item["code"] == "invalid_timestamp_omitted" for item in projection["findings"])
    assert any(item["code"] == "metadata_link_omitted" for item in projection["findings"])


def test_pdf_is_valid_searchable_and_keeps_https_links(monkeypatch):
    def unavailable_image(*_args, **_kwargs):
        raise OSError("test media unavailable")

    monkeypatch.setattr(pdf_export, "_fetch_public_image_asset", unavailable_image)
    page = {
        "id": "page_20260808_010101_test",
        "title": "Portable PDF",
        "content": (
            "## Summary\n\n"
            "[Official site](https://example.com/docs)\n\n"
            "![Remote diagram](https://example.com/diagram.png)\n\n"
            "| Item | Value |\n| --- | --- |\n| one | two |"
        ),
        "tags": ["test", "pdf"],
        "created": "2026-08-08T01:01:01Z",
    }

    projection, payload = prepare_canvas_pdf(page)
    _second_projection, second_payload = prepare_canvas_pdf(page)
    inspection = validate_canvas_pdf(payload)

    assert payload.startswith(b"%PDF-")
    assert inspection["pages"] >= 1
    assert inspection["links"] >= 2
    assert "Portable PDF" in inspection["text"]
    assert "Summary" in inspection["text"]
    assert projection["pdf"]["bytes"] == len(payload)
    assert second_payload == payload
    assert inspection["metadata"]["author"] == "Jarvis Canvas"


def test_pdf_light_and_dark_themes_are_distinct_and_searchable():
    page = {
        "id": "page_20260808_020202_theme",
        "title": "Theme preview",
        "content": "## Readable heading\n\nBody text with a [link](https://example.com).",
        "created": "2026-08-08T02:02:02Z",
    }

    dark_projection, dark_payload = prepare_canvas_pdf(page)
    light_projection, light_payload = prepare_canvas_pdf(page, theme="light")
    dark_inspection = validate_canvas_pdf(dark_payload)
    light_inspection = validate_canvas_pdf(light_payload)

    def page_corner_rgb(payload: bytes) -> tuple[int, int, int]:
        with fitz.open(stream=payload, filetype="pdf") as document:
            pixmap = document[0].get_pixmap(alpha=False)
            offset = (5 * pixmap.width + 5) * pixmap.n
            return tuple(pixmap.samples[offset : offset + 3])

    assert dark_projection["pdf"]["theme"] == "dark"
    assert light_projection["pdf"]["theme"] == "light"
    assert dark_payload != light_payload
    assert max(page_corner_rgb(dark_payload)) < 80
    assert min(page_corner_rgb(light_payload)) > 240
    assert "Theme preview" in dark_inspection["text"]
    assert dark_inspection["text"] == light_inspection["text"]


def test_pdf_rejects_unknown_theme():
    with pytest.raises(ValueError, match="light or dark"):
        prepare_canvas_pdf({"title": "Theme", "content": "Body"}, theme="sepia")


def _test_png(color: tuple[int, int, int], size: tuple[int, int] = (640, 360)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


def test_public_images_and_youtube_thumbnails_are_embedded_clickable_cards(monkeypatch):
    requested_urls = []

    def download_image(url, **_kwargs):
        requested_urls.append(url)
        color = (220, 38, 38) if "ytimg.com" in url else (37, 99, 235)
        return _test_png(color), "image/png"

    monkeypatch.setattr(pdf_export, "_download_public_https", download_image)
    page = {
        "id": "page_20260808_040404_media",
        "title": "Media cards",
        "content": (
            "Before the image.\n\n"
            "![Public diagram](https://images.example.com/diagram.png)\n\n"
            "[Product walkthrough](https://www.youtube.com/watch?v=abcdefghijk)\n\n"
            "After the video."
        ),
    }

    projection, payload = prepare_canvas_pdf(page)
    inspection = validate_canvas_pdf(payload)
    with fitz.open(stream=payload, filetype="pdf") as document:
        embedded_images = sum(len(page.get_images(full=True)) for page in document)

    assert requested_urls == [
        "https://images.example.com/diagram.png",
        "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg",
    ]
    assert embedded_images >= 2
    assert inspection["links"] >= 2
    assert "Public diagram" in inspection["text"]
    assert "Open original image" in inspection["text"]
    assert "Product walkthrough" in inspection["text"]
    assert "Watch on YouTube" in inspection["text"]
    codes = {item["code"] for item in projection["findings"]}
    assert "public_image_embedded" in codes
    assert "youtube_thumbnail_embedded" in codes
    assert "remote_image_content_unscanned" in codes


def test_remote_media_failure_preserves_clickable_fallbacks(monkeypatch):
    def unavailable_image(*_args, **_kwargs):
        raise OSError("test media unavailable")

    monkeypatch.setattr(pdf_export, "_fetch_public_image_asset", unavailable_image)
    page = {
        "id": "page_20260808_050505_fallback",
        "title": "Media fallback",
        "content": (
            "![Public diagram](https://images.example.com/diagram.png)\n\n"
            "https://youtu.be/abcdefghijk"
        ),
    }

    projection, payload = prepare_canvas_pdf(page)
    inspection = validate_canvas_pdf(payload)

    assert inspection["links"] >= 2
    assert "Image preview unavailable" in inspection["text"]
    assert "Thumbnail unavailable" in inspection["text"]
    codes = {item["code"] for item in projection["findings"]}
    assert "public_image_preview_unavailable" in codes
    assert "youtube_thumbnail_unavailable" in codes


def test_embedded_media_pdf_budget_uses_link_fallback(monkeypatch):
    monkeypatch.setattr(
        pdf_export,
        "_download_public_https",
        lambda *_args, **_kwargs: (_test_png((37, 99, 235)), "image/png"),
    )
    monkeypatch.setattr(pdf_export, "MAX_EMBEDDED_MEDIA_TOTAL_BYTES", 1)

    projection, payload = prepare_canvas_pdf(
        {
            "title": "Bounded media",
            "content": "![Public diagram](https://images.example.com/diagram.png)",
        }
    )
    inspection = validate_canvas_pdf(payload)

    assert inspection["links"] >= 1
    assert "Image preview unavailable" in inspection["text"]
    codes = {item["code"] for item in projection["findings"]}
    assert "public_media_pdf_budget_reached" in codes


def test_remote_media_downloader_rejects_private_dns_before_connect(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 443))
        ],
    )

    def reject_socket(*_args, **_kwargs):
        raise AssertionError("Private media targets must be rejected before connecting")

    monkeypatch.setattr(socket, "socket", reject_socket)
    with pytest.raises(pdf_export._UnsafeRemoteMedia):
        pdf_export._download_public_https(
            "https://images.example.com/private.png",
            timeout=0.25,
        )


def test_blocking_secret_scan_skips_remote_media_fetch(monkeypatch):
    def reject_fetch(*_args, **_kwargs):
        raise AssertionError("Blocked projections must not send remote media requests")

    monkeypatch.setattr(pdf_export, "_fetch_public_image_asset", reject_fetch)
    projection, _payload = prepare_canvas_pdf(
        {
            "title": "Blocked media",
            "content": (
                "![Sensitive image](https://images.example.com/diagram.png)\n\n"
                "api_key=sk-abcdefghijklmnopqrstuvwxyz123456"
            ),
        }
    )

    assert has_blocking_findings(projection)
    codes = {item["code"] for item in projection["findings"]}
    assert "public_media_fetch_skipped" in codes
    assert "public_image_preview_unavailable" in codes


def test_rich_table_links_are_flattened_and_preserved_in_appendix():
    page = {
        "id": "page_20260808_030303_test",
        "title": "Rolling radar",
        "content": (
            "| Project | Source |\n"
            "| --- | --- |\n"
            "| Example | [GitHub](https://github.com/example/project) |\n"
            "| Another | [Docs](https://example.com/docs) |"
        ),
        "updated": "2026-08-08T03:03:03Z",
    }

    projection, payload = prepare_canvas_pdf(page)
    inspection = validate_canvas_pdf(payload)

    assert inspection["pages"] >= 1
    assert inspection["links"] == 2
    assert "Table links" in inspection["text"]
    assert "https://github.com/example/project" in inspection["text"]
    assert any(item["code"] == "table_cells_flattened" for item in projection["findings"])
