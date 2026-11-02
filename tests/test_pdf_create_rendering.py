"""Render local raster images through the actual PDF creation helper."""

import sys

import fitz
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
