"""Exercise real offline PDF output, not a private Stash document fixture."""

import fitz
import pytest

from lib.pdf_rendering import (
    MAX_SOURCE_BYTES,
    read_pdf_text_source,
    render_markdown_pdf,
    render_text_pdf,
)


def extracted(path):
    with fitz.open(path) as document:
        return "".join(page.get_text() for page in document)


def test_markdown_formats_headings_lists_tables_code_and_private_links(tmp_path):
    output = tmp_path / "formatted.pdf"
    source = """# Section — Ω Ж

A **bold phrase** and *italic phrase* with a [private link](https://localhost/private?token=preserved).

- First bullet
- Second bullet

3. Third ordered item
4. Fourth ordered item

| Column | Value |
| --- | --- |
| Café | [table target](https://127.0.0.1/report) |

```python
print("Unicode — source")
```
"""
    metadata = render_markdown_pdf(source, str(output), "Title — “quotes”")
    text = extracted(output)
    assert "Title — “quotes”" in text
    assert "Section — Ω Ж" in text
    assert "bold phrase" in text and "**bold phrase**" not in text
    assert "First bullet" in text and "•" in text
    assert "Third ordered item" in text and "3." in text
    assert "Column" in text and "Café" in text and "https://127.0.0.1/report" in text
    assert 'print("Unicode — source")' in text and "```" not in text
    with fitz.open(output) as document:
        links = [link["uri"] for page in document for link in page.get_links() if "uri" in link]
        spans = [span for page in document for block in page.get_text("dict")["blocks"] if "lines" in block for line in block["lines"] for span in line["spans"]]
    assert "https://localhost/private?token=preserved" in links
    assert any("JetBrainsMono" in span["font"] for span in spans)
    assert any("Section —" in span["text"] and span["size"] > 15 for span in spans)
    assert metadata["page_count"] >= 1
    assert metadata["warnings"] == []


def test_list_markers_after_headings_use_the_body_font_size(tmp_path):
    output = tmp_path / "list-marker-sizes.pdf"
    render_markdown_pdf(
        "# Large heading\n\n1. Ordered body\n\n## Another heading\n\n- Bullet body",
        str(output), "List typography",
    )
    with fitz.open(output) as document:
        spans = [
            span for page in document for block in page.get_text("dict")["blocks"]
            if "lines" in block for line in block["lines"] for span in line["spans"]
        ]
    markers = [span for span in spans if span["text"].strip() in {"1.", "•"}]
    bodies = [span for span in spans if span["text"].strip() in {"Ordered body", "Bullet body"}]
    assert len(markers) == 2
    assert len(bodies) == 2
    assert all(span["size"] == pytest.approx(10.5) for span in markers + bodies)


def test_bold_italic_adds_only_local_text_stroke_and_normal_text_stays_filled(tmp_path):
    output = tmp_path / "bold-italic.pdf"
    render_markdown_pdf(
        "*Italic sample*\n\n***Bold italic sample***\n\nNormal tail",
        str(output), "Font styles",
    )
    with fitz.open(output) as document:
        assert document[0].get_text().count("Bold italic sample") == 1
        runs = [
            ("".join(chr(character[0]) for character in span["chars"]), span["type"])
            for span in document[0].get_texttrace()
        ]
    assert ("Italic sample", 0) in runs
    assert ("Italic sample", 1) not in runs
    assert ("Bold italic sample", 0) in runs
    assert ("Bold italic sample", 1) in runs
    assert ("Normal tail", 0) in runs
    assert ("Normal tail", 1) not in runs


@pytest.mark.parametrize("opener", ["**Formatted opener**", "`Formatted opener`"])
def test_list_marker_keeps_body_font_when_first_inline_run_is_formatted(tmp_path, opener):
    output = tmp_path / "formatted-list-opener.pdf"
    render_markdown_pdf(f"# Heading\n\n1. {opener} with body text.", str(output))
    with fitz.open(output) as document:
        spans = [
            span for page in document for block in page.get_text("dict")["blocks"]
            if "lines" in block for line in block["lines"] for span in line["spans"]
        ]
    marker = next(span for span in spans if span["text"].strip() == "1.")
    assert marker["size"] == pytest.approx(10.5)
    assert "Inter" in marker["font"] and "Mono" not in marker["font"]
    assert "Bold" not in marker["font"]


def test_long_source_keeps_its_tail_and_long_code_links_and_table_cells_wrap(tmp_path):
    output = tmp_path / "complete.pdf"
    source = (
        "Introduction — " + "paragraph content. " * 1200 + "\n\n"
        + "https://localhost/" + "abcdefgh" * 250 + "\n\n"
        + "```\n" + "x" * 1500 + "\n```\n\n"
        + "| Header | Value |\n|---|---|\n| Large row | " + "table content " * 1000 + " |\n\n"
        + "FINAL COMPLETE SOURCE SENTINEL"
    )
    metadata = render_markdown_pdf(source, str(output), "Complete guide")
    text = " ".join(extracted(output).split())
    assert "FINAL COMPLETE SOURCE SENTINEL" in text
    assert text.count("paragraph content.") == 1200
    # A page footer can fall between the two words during text extraction.
    assert text.split().count("table") == 1000
    assert metadata["page_count"] > 3
    assert any("labeled rows" in warning for warning in metadata["warnings"])


def test_blocked_or_unresolved_markdown_images_preserve_references(tmp_path, monkeypatch):
    from fpdf import FPDF
    def forbidden(*_args, **_kwargs):
        pytest.fail("Blocked or unresolved images must not reach the PDF image loader")
    monkeypatch.setattr(FPDF, "image", forbidden)
    source = (
        "![Remote diagram](http://127.0.0.1/private.png)\n\n"
        "![Local file](./private.png)\n\n"
        "![File URL](file:///etc/passwd)\n\n"
        "<img src='/etc/passwd'>\n\n"
        "| Image |\n|---|\n| ![Table diagram](http://127.0.0.1/table.png) |"
    )
    output = tmp_path / "images-as-references.pdf"
    metadata = render_markdown_pdf(source, str(output))
    text = extracted(output)
    assert "Remote diagram" in text and "http://127.0.0.1/private.png" in text
    assert "Local file" in text and "./private.png" in text
    assert "Table diagram" in text
    assert any("blocked IP range" in warning for warning in metadata["warnings"])
    assert any("original Markdown source file" in warning for warning in metadata["warnings"])
    with fitz.open(output) as document:
        assert not any(page.get_images() for page in document)


def test_plain_text_preserves_markdown_markers_and_reports_unsupported_glyphs(tmp_path):
    output = tmp_path / "plain.pdf"
    metadata = render_text_pdf("# literal heading\n**literal asterisks** — “café” Ω Ж 日本語 😀", str(output), "Plain — text")
    text = extracted(output)
    assert "# literal heading" in text and "**literal asterisks**" in text
    assert "— “café” Ω Ж" in text
    assert "[U+65E5]" in text and "[U+1F600]" in text
    assert any("Bundled fonts lack" in warning for warning in metadata["warnings"])


def test_bounded_utf8_file_read_is_complete_and_rejects_oversized_input(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("\ufeff# Café — guide\nTAIL", encoding="utf-8")
    assert read_pdf_text_source(source) == "# Café — guide\nTAIL"
    source.write_bytes(b"x" * (MAX_SOURCE_BYTES + 1))
    with pytest.raises(ValueError, match="5 MiB"):
        read_pdf_text_source(source)
    output = tmp_path / "too-large.pdf"
    with pytest.raises(ValueError, match="5 MiB"):
        render_markdown_pdf("x" * (MAX_SOURCE_BYTES + 1), str(output))
    assert not output.exists()
