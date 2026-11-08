"""Image tables retain their grid, source order, and complete cell contents."""

import io

import fitz
import pytest
from PIL import Image

from lib import pdf_rendering, stash_helper


@pytest.fixture
def image_refs(tmp_path, monkeypatch):
    root = tmp_path / "stash"
    root.mkdir()
    monkeypatch.setenv("JARVIS_OVERRIDE_STASH_DIR", str(root))
    space = stash_helper.StashSpace("space_image_tables", root)
    space.create()
    references = []
    for index, color in enumerate(((220, 40, 30), (20, 100, 230))):
        data = io.BytesIO()
        Image.new("RGB", (120, 60), color).save(data, "PNG")
        saved = stash_helper.StashFile(space).save_binary(
            data.getvalue(), f"chart-{index}.png", mime_type="image/png",
        )
        references.append(saved["ref"])
    return references


def _render(tmp_path, source):
    path = tmp_path / "table.pdf"
    metadata = pdf_rendering.render_markdown_pdf(source, str(path), "Image table report")
    return path, metadata


def _text(document):
    return " ".join(" ".join(page.get_text() for page in document).split())


def test_mixed_image_cell_keeps_grid_caption_and_text_order(tmp_path, image_refs):
    path, metadata = _render(tmp_path, (
        "Before table.\n\n| Region | Findings |\n| --- | --- |\n"
        f"| West | Cell lead ![Revenue chart]({image_refs[0]}) cell tail. |\n"
        "| East | Complete finding. |\n\nAfter table."
    ))
    with fitz.open(path) as document:
        assert len(document) == 1
        page = document[0]
        text = _text(document)
        assert "Table row" not in text and "[Image:" not in text
        for phrase in ("Before table.", "Region", "Findings", "West", "Cell lead", "Revenue chart", "cell tail.", "East", "Complete finding.", "After table."):
            assert phrase in text
        image_rect = page.get_image_rects(page.get_images()[0][0])[0]
        assert page.search_for("Cell lead")[0].y1 < image_rect.y0
        assert image_rect.y1 < page.search_for("Revenue chart")[0].y0
        assert page.search_for("Revenue chart")[0].y1 < page.search_for("cell tail.")[0].y0
        assert page.search_for("West")[0].x0 < image_rect.x0
        rectangles = [item[1] for drawing in page.get_drawings() for item in drawing["items"] if item[0] == "re"]
        assert len(rectangles) == 6
        assert any(rect.contains(image_rect) for rect in rectangles)
    assert metadata["warnings"] == []


def test_multiple_images_and_link_destinations_remain_in_one_cell(tmp_path, image_refs):
    path, metadata = _render(tmp_path, (
        "| Topic | Detail |\n| --- | --- |\n"
        f"| Results | Intro ![First]({image_refs[0]}) middle "
        f"[![Second]({image_refs[1]})](https://example.invalid/report) final. |"
    ))
    with fitz.open(path) as document:
        page = document[0]
        text = _text(document)
        assert len(page.get_images()) == 2
        for phrase in ("Intro", "First", "middle", "Second", "https://example.invalid/report", "final."):
            assert phrase in text
        assert text.index("Intro") < text.index("First") < text.index("middle") < text.index("Second") < text.index("final.")
        image_rects = sorted(
            (page.get_image_rects(image[0])[0] for image in page.get_images()),
            key=lambda rect: rect.y0,
        )
        assert image_rects[0].y1 < image_rects[1].y0
        assert image_rects[0].x0 == pytest.approx(image_rects[1].x0)
    assert metadata["warnings"] == []


def test_missing_image_keeps_placeholder_inside_grid_with_valid_image(tmp_path, image_refs):
    path, metadata = _render(tmp_path, (
        "| Valid | Missing |\n| --- | --- |\n"
        f"| ![Chart]({image_refs[0]}) | Before ![Lost](stash://missing/image) after. |"
    ))
    with fitz.open(path) as document:
        page = document[0]
        text = _text(document)
        assert len(page.get_images()) == 1
        assert "[Image: Lost; stash://missing/image]" in text
        assert "Before" in text and "after." in text
        assert "Table row" not in text
        assert page.search_for("Before")[0].x0 > page.get_image_rects(page.get_images()[0][0])[0].x1
    assert metadata["warnings"]
    assert not any("labeled rows" in warning for warning in metadata["warnings"])


def test_image_header_repeats_after_page_breaks_without_spending_image_budget_again(
    tmp_path, image_refs, monkeypatch,
):
    monkeypatch.setattr(pdf_rendering, "MAX_EMBEDDED_IMAGES", 1)
    source = (
        f"| ![Header chart]({image_refs[0]}) | Finding |\n| --- | --- |\n"
        + "\n".join(f"| Region {index:03d} | Detail {index:03d} |" for index in range(65))
        + "\n\nCOMPLETE TABLE TAIL"
    )
    path, metadata = _render(tmp_path, source)
    with fitz.open(path) as document:
        assert len(document) >= 3
        text = _text(document)
        assert "COMPLETE TABLE TAIL" in text
        for index in range(65):
            assert text.count(f"Region {index:03d}") == 1
            assert text.count(f"Detail {index:03d}") == 1
        table_pages = [page for page in document if "Region" in page.get_text()]
        for page in table_pages:
            assert "Header chart" in page.get_text() and "Finding" in page.get_text()
            assert page.get_images()
            for image in page.get_images():
                assert all(rect.y1 < page.rect.height - 40 for rect in page.get_image_rects(image[0]))
    assert metadata["warnings"] == []


def test_tall_image_table_falls_back_without_losing_complete_text(tmp_path, image_refs):
    source = (
        "| Key | Full details |\n| --- | --- |\n"
        f"| Large | Before ![Evidence]({image_refs[0]}) "
        + "complete detail " * 500
        + "FINAL CELL SENTINEL |\n\nFINAL DOCUMENT SENTINEL"
    )
    path, metadata = _render(tmp_path, source)
    with fitz.open(path) as document:
        text = _text(document)
        assert "Table row 1" in text
        assert "FINAL CELL SENTINEL" in text and "FINAL DOCUMENT SENTINEL" in text
        # A footer may interrupt this pair across a page break; count one word.
        assert text.split().count("complete") == 500
        assert any(page.get_images() for page in document)
    assert any("wide or tall" in warning for warning in metadata["warnings"])


def test_wide_image_table_falls_back_with_headers_and_every_cell(tmp_path, image_refs, monkeypatch):
    monkeypatch.setattr(pdf_rendering, "MAX_EMBEDDED_IMAGES", 1)
    source = (
        "| A | B | C | D | E | F | G |\n|---|---|---|---|---|---|---|\n"
        f"| FIRST | b | c | ![Chart]({image_refs[0]}) | e | f | LAST |"
    )
    path, metadata = _render(tmp_path, source)
    with fitz.open(path) as document:
        text = _text(document)
        assert "Table row 1" in text and "FIRST" in text and "LAST" in text
        assert "Chart" in text and "[Image:" not in text
        assert any(page.get_images() for page in document)
    assert any("wide or tall" in warning for warning in metadata["warnings"])
    assert not any("image count limit" in warning for warning in metadata["warnings"])


def test_header_only_image_table_remains_a_grid(tmp_path, image_refs):
    path, metadata = _render(tmp_path, (
        f"| ![Header evidence]({image_refs[0]}) | Text heading |\n| --- | --- |"
    ))
    with fitz.open(path) as document:
        assert "Header evidence" in _text(document) and "Text heading" in _text(document)
        assert document[0].get_images()
        rectangles = [item for drawing in document[0].get_drawings() for item in drawing["items"] if item[0] == "re"]
        assert len(rectangles) == 2
    assert metadata["warnings"] == []
