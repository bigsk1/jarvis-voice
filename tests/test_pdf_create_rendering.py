"""Render local raster images through the actual PDF creation helper."""

import sys
from types import SimpleNamespace

import fitz
import pytest
from PIL import Image


def test_pdf_create_preserves_text_and_embeds_local_png(tmp_path, monkeypatch):
    # The legacy tool adds lib/ to sys.path during import. Keep that adjustment
    # local to this test so collection order cannot change unrelated imports.
    with monkeypatch.context() as imports:
        imports.setattr(sys, "path", list(sys.path))
        from skills.pdf_create import create_simple_pdf

    image_path = tmp_path / "local image.png"
    Image.new("RGB", (96, 48), (18, 74, 132)).save(image_path)
    output_path = tmp_path / "rendered.pdf"
    title = "PDF rendering regression"
    heading = "Approved local image"
    paragraph = "This paragraph and its local image must remain in the generated document."

    rendered = create_simple_pdf(
        title,
        [
            {"type": "heading", "level": 1, "content": heading},
            {"type": "text", "content": paragraph},
            {"type": "image", "content": str(image_path)},
        ],
        str(output_path),
    )

    assert rendered == str(output_path)
    assert output_path.read_bytes().startswith(b"%PDF-")
    with fitz.open(output_path) as document:
        assert document.page_count >= 1
        text = " ".join(" ".join(page.get_text() for page in document).split())
        assert title in text
        assert heading in text
        assert paragraph in text
        image_refs = {image[0] for page in document for image in page.get_images(full=True)}
        assert image_refs
        images = [document.extract_image(reference) for reference in image_refs]
        assert any((image["width"], image["height"]) == (96, 48) for image in images)


@pytest.fixture
def pdf_create(monkeypatch):
    with monkeypatch.context() as imports:
        imports.setattr(sys, "path", list(sys.path))
        from skills import pdf_create
    return pdf_create


def test_mixed_pdf_preserves_unicode_title_heading_and_plain_body(tmp_path, pdf_create):
    output = tmp_path / "unicode.pdf"
    metadata = {}
    pdf_create.create_simple_pdf(
        "Owner guide — “quoted”",
        [
            {"type": "heading", "content": "Café — Ω and Ж"},
            {"type": "text", "content": "Literal # text and **asterisks** stay plain — end."},
        ],
        str(output), metadata=metadata,
    )
    with fitz.open(output) as document:
        text = "".join(page.get_text() for page in document)
    assert "Owner guide — “quoted”" in text
    assert "Café — Ω and Ж" in text
    assert "Literal # text and **asterisks** stay plain — end." in text
    assert metadata == {"page_count": 1, "warnings": []}


def test_from_text_requests_plain_body_and_markdown_requests_formatting(pdf_create, monkeypatch):
    received = []
    monkeypatch.setattr(pdf_create, "action_create", lambda args: received.append(args) or {"ok": True})
    pdf_create.action_from_text({"text": "# literal", "title": "Text", "output_name": "text.pdf"})
    pdf_create.action_from_markdown({"text": "# heading", "title": "Markdown"})
    assert received[0]["_text_format"] == "plain"
    assert received[0]["output_name"] == "text.pdf"
    assert received[1]["_text_format"] == "markdown"


def test_missing_stash_source_fails_without_creating_pdf(pdf_create, tmp_path, monkeypatch):
    space = SimpleNamespace(space_id="space_test", space_path=tmp_path, meta={})
    monkeypatch.setattr(pdf_create, "get_space", lambda _: space)
    monkeypatch.setattr(pdf_create, "resolve_file_path", lambda **_: str(tmp_path / "missing.md"))
    with pytest.raises(ValueError, match="Could not load PDF source"):
        pdf_create.action_create({"space_id": "space_test", "files": ["missing.md"], "output_name": "missing.pdf"})
    assert not (tmp_path / "missing.pdf").exists()


def test_unsupported_stash_source_fails_instead_of_claiming_complete_content(pdf_create, tmp_path, monkeypatch):
    space = SimpleNamespace(space_id="space_test", space_path=tmp_path, meta={})
    monkeypatch.setattr(pdf_create, "get_space", lambda _: space)
    monkeypatch.setattr(pdf_create, "resolve_file_path", lambda **_: str(tmp_path / "source.docx"))
    with pytest.raises(ValueError, match="Unsupported PDF source format .docx"):
        pdf_create.action_create({"space_id": "space_test", "files": ["file_test"], "output_name": "unsupported.pdf"})
    assert not (tmp_path / "unsupported.pdf").exists()


@pytest.mark.parametrize("filename", ["../escape.pdf", "/tmp/escape.pdf", "dir\\escape.pdf"])
def test_output_name_policy_still_rejects_directories(pdf_create, filename, monkeypatch):
    def unexpected_space(_):
        pytest.fail("Filename must be checked before opening a Stash space")
    monkeypatch.setattr(pdf_create, "get_space", unexpected_space)
    with pytest.raises(ValueError, match="filename without directory"):
        pdf_create.action_create({"space_id": "space_test", "text": "content", "output_name": filename})


@pytest.mark.parametrize("extension", ["md", "markdown"])
def test_stash_markdown_reads_full_source_and_passes_formatted_item(pdf_create, tmp_path, monkeypatch, extension):
    source = tmp_path / f"guide.{extension}"
    content = "# Heading — guide\n\n" + "Complete source paragraph.\n\n" * 800 + "FINAL SOURCE SENTINEL"
    source.write_text(content, encoding="utf-8")
    space = SimpleNamespace(space_id="space_test", space_path=tmp_path, meta={})
    monkeypatch.setattr(pdf_create, "get_space", lambda _: space)
    monkeypatch.setattr(pdf_create, "resolve_file_path", lambda **_: str(source))
    class StopAfterCapture(Exception):
        pass
    captured = []
    def capture(_title, items, _path, **_kwargs):
        captured.extend(items)
        raise StopAfterCapture
    monkeypatch.setattr(pdf_create, "create_simple_pdf", capture)
    with pytest.raises(StopAfterCapture):
        pdf_create.action_create({"space_id": "space_test", "files": ["file_test"], "output_name": "guide.pdf"})
    assert captured == [{"type": "markdown", "content": content}]


def test_missing_explicit_image_fails_instead_of_rendering_error_text(pdf_create, tmp_path):
    output = tmp_path / "missing-image.pdf"
    with pytest.raises(FileNotFoundError, match="PDF image source"):
        pdf_create.create_simple_pdf("Image", [{"type": "image", "content": str(tmp_path / "missing.png")}], str(output))
    assert not output.exists()


def test_markdown_action_returns_pdf_evidence_without_live_stash_or_memory(pdf_create, tmp_path, monkeypatch):
    space = SimpleNamespace(
        space_id="space_test", space_path=tmp_path, meta={}, _meta={"files": []}, _save_meta=lambda: None,
    )
    monkeypatch.setattr(pdf_create, "get_space", lambda _: space)
    monkeypatch.setitem(sys.modules, "memory_db", SimpleNamespace(
        MemoryDB=lambda: SimpleNamespace(remember=lambda **_: None),
    ))
    result = pdf_create.action_from_markdown({
        "space_id": "space_test", "text": "# Complete — source\n\nFinal paragraph.",
        "title": "Unicode — guide", "output_name": "guide.pdf",
    })
    assert result["ok"] is True
    assert result["data"]["mime_type"] == "application/pdf"
    assert result["data"]["source_complete"] is True
    assert result["data"]["page_count"] == 1
    assert result["data"]["warnings"] == []
    assert result["data"]["ref"].startswith("stash://space_test/")
    assert space._meta["files"][0]["name"] == "guide.pdf"
    with fitz.open(tmp_path / "guide.pdf") as document:
        assert "Complete — source" in document[0].get_text()
        assert "Final paragraph." in document[0].get_text()
