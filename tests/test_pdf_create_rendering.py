"""Render local raster images through the actual PDF creation helper."""

import base64
import hashlib
import io
import sys
from pathlib import Path
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
    assert captured == [{"type": "markdown", "content": content, "source_path": str(source)}]


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


@pytest.fixture
def markdown_stash(tmp_path, monkeypatch):
    from config_loader import config_scope
    from stash_helper import StashSpace

    monkeypatch.setitem(sys.modules, "memory_db", SimpleNamespace(
        MemoryDB=lambda: SimpleNamespace(remember=lambda **_: None),
    ))
    with config_scope("cloud", overrides={"STASH_DIR": str(tmp_path / "stash")}):
        source_space = StashSpace("space_pdf_sources")
        source_space.create()
        media_space = StashSpace("space_pdf_media")
        media_space.create()
        yield source_space, media_space


def _saved_raster(space, *, animated=False):
    from stash_helper import StashFile

    payload = io.BytesIO()
    image = Image.new("RGB", (80, 40), (220, 30, 20))
    if animated:
        image.save(payload, format="GIF", save_all=True,
                   append_images=[Image.new("RGB", image.size, (20, 30, 220))],
                   duration=[100, 200], loop=0)
    else:
        image.save(payload, format="PNG")
    return StashFile(space).save_binary(
        payload.getvalue(), "chart.gif" if animated else "chart.png",
        mime_type="image/gif" if animated else "image/png",
    )


@pytest.mark.parametrize("action", ["from_markdown", "create_file"])
def test_markdown_actions_embed_cross_space_stash_chart_with_complete_pdf_evidence(
    pdf_create, markdown_stash, action,
):
    from stash_helper import StashFile

    source_space, media_space = markdown_stash
    chart = _saved_raster(media_space)
    original = Path(chart["path"]).read_bytes()
    markdown = f"# Chart report\n\nBefore the chart.\n\n![Revenue chart]({chart['ref']})\n\nFinal report paragraph."
    args = {"space_id": source_space.space_id, "title": "Report — charts", "output_name": "report.pdf"}
    if action == "from_markdown":
        result = pdf_create.action_from_markdown({**args, "text": markdown})
    else:
        saved_source = StashFile(source_space).save_text(markdown, "report.md")
        result = pdf_create.action_create({**args, "files": [saved_source["ref"]]})
        assert Path(saved_source["path"]).read_text() == markdown

    assert result["ok"] is True
    data = result["data"]
    assert data["source_complete"] is True
    assert data["warnings"] == []
    pdf_bytes = Path(data["path"]).read_bytes()
    assert data["size_bytes"] == len(pdf_bytes)
    persisted = next(item for item in pdf_create.get_space(source_space.space_id).meta["files"]
                     if item["file_id"] == data["file_id"])
    assert persisted["hash_sha256"] == hashlib.sha256(pdf_bytes).hexdigest()
    with fitz.open(data["path"]) as document:
        assert document.page_count == data["page_count"]
        text = "".join(page.get_text() for page in document)
        assert "Before the chart." in text
        assert "Final report paragraph." in text
        assert "[Image:" not in text
        assert any((image[2], image[3]) == (80, 40)
                   for page in document for image in page.get_images(full=True))
    assert Path(chart["path"]).read_bytes() == original


def test_markdown_action_keeps_good_chart_and_reports_missing_or_private_images(
    pdf_create, markdown_stash,
):
    source_space, media_space = markdown_stash
    chart = _saved_raster(media_space)
    markdown = (
        f"![Good chart]({chart['ref']})\n\n"
        f"![Expired chart](stash://{media_space.space_id}/file_missing)\n\n"
        "![Private photo](http://127.0.0.1/photo.png)\n\nREPORT TAIL"
    )
    result = pdf_create.action_from_markdown({
        "space_id": source_space.space_id, "text": markdown, "output_name": "partial-media.pdf",
    })
    assert result["ok"] is True
    assert result["data"]["source_complete"] is True
    assert len(result["data"]["warnings"]) >= 2
    with fitz.open(result["data"]["path"]) as document:
        text = "".join(page.get_text() for page in document)
        assert "Expired chart" in text and "Private photo" in text and "REPORT TAIL" in text
        assert any(page.get_images() for page in document)


def test_markdown_action_renders_gif_first_frame_and_returns_warning(
    pdf_create, markdown_stash,
):
    source_space, media_space = markdown_stash
    animation = _saved_raster(media_space, animated=True)
    original = Path(animation["path"]).read_bytes()
    result = pdf_create.action_from_markdown({
        "space_id": source_space.space_id, "text": f"![Animation]({animation['ref']})\n\nTAIL",
        "output_name": "animation-report.pdf",
    })
    assert result["ok"] is True
    assert any("first frame" in warning.lower() for warning in result["data"]["warnings"])
    with fitz.open(result["data"]["path"]) as document:
        references = {image[0] for page in document for image in page.get_images(full=True)}
        assert references
        for reference in references:
            raster = document.extract_image(reference)
            with Image.open(io.BytesIO(raster["image"])) as image:
                assert image.convert("RGB").getpixel((40, 20)) == (220, 30, 20)
    assert Path(animation["path"]).read_bytes() == original


def test_plain_text_action_keeps_stash_markdown_image_literal(pdf_create, markdown_stash):
    source_space, media_space = markdown_stash
    chart = _saved_raster(media_space)
    literal = f"![Literal chart]({chart['ref']})"
    result = pdf_create.action_from_text({
        "space_id": source_space.space_id, "text": literal, "output_name": "literal.pdf",
    })
    assert result["data"]["warnings"] == []
    with fitz.open(result["data"]["path"]) as document:
        assert literal in "".join(page.get_text() for page in document)
        assert not any(page.get_images() for page in document)


def test_stash_markdown_file_resolves_neighbor_image_from_original_source_directory(
    pdf_create, markdown_stash, tmp_path, monkeypatch,
):
    from stash_helper import StashFile

    source_space, _ = markdown_stash
    chart = _saved_raster(source_space)
    markdown = f"Before neighbor.\n\n![Neighbor chart](./{Path(chart['path']).name})\n\nAFTER NEIGHBOR"
    source = StashFile(source_space).save_text(markdown, "neighbor-report.md")
    unrelated = tmp_path / "unrelated-working-directory"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)

    result = pdf_create.action_create({
        "space_id": source_space.space_id, "files": [source["ref"]],
        "output_name": "neighbor-report.pdf",
    })

    assert result["data"]["warnings"] == []
    with fitz.open(result["data"]["path"]) as document:
        assert any(page.get_images() for page in document)
        text = "".join(page.get_text() for page in document)
        assert "Before neighbor." in text and "AFTER NEIGHBOR" in text
        assert "[Image:" not in text
    assert Path(source["path"]).read_text() == markdown


def test_inline_markdown_does_not_resolve_relative_images_from_working_directory(
    pdf_create, markdown_stash, tmp_path, monkeypatch,
):
    source_space, _ = markdown_stash
    Image.new("RGB", (80, 40), "red").save(tmp_path / "chart.png")
    monkeypatch.chdir(tmp_path)

    result = pdf_create.action_from_markdown({
        "space_id": source_space.space_id,
        "text": "![Unscoped relative chart](./chart.png)\n\nTAIL",
        "output_name": "inline-relative.pdf",
    })

    assert result["data"]["warnings"]
    with fitz.open(result["data"]["path"]) as document:
        assert not any(page.get_images() for page in document)
        assert "Unscoped relative chart" in document[0].get_text()


def test_composed_markdown_sources_keep_distinct_relative_images_with_same_filename(
    pdf_create, markdown_stash,
):
    from stash_helper import StashFile

    source_space, media_space = markdown_stash
    sources = []
    colors = {(220, 30, 20), (20, 30, 220)}
    for space, color in zip((source_space, media_space), sorted(colors), strict=True):
        Image.new("RGB", (70, 35), color).save(Path(space.space_path) / "chart.png")
        source = StashFile(space).save_text("![Chart](./chart.png)", "report.md")
        sources.append(source["ref"])

    result = pdf_create.action_create({
        "space_id": source_space.space_id, "files": sources, "output_name": "two-sources.pdf",
    })

    assert result["data"]["warnings"] == []
    with fitz.open(result["data"]["path"]) as document:
        references = {image[0] for page in document for image in page.get_images(full=True)}
        assert len(references) == 2
        embedded_colors = set()
        for reference in references:
            with Image.open(io.BytesIO(document.extract_image(reference)["image"])) as image:
                embedded_colors.add(image.convert("RGB").getpixel((35, 17)))
        assert embedded_colors == colors


def test_inline_markdown_action_embeds_data_raster(pdf_create, markdown_stash):
    source_space, _ = markdown_stash
    payload = io.BytesIO()
    Image.new("RGBA", (60, 30), (20, 80, 160, 255)).save(payload, format="PNG")
    data_url = "data:image/png;base64," + base64.b64encode(payload.getvalue()).decode("ascii")

    result = pdf_create.action_from_markdown({
        "space_id": source_space.space_id, "text": f"![Inline chart]({data_url})\n\nDATA TAIL",
        "output_name": "data-raster.pdf",
    })

    assert result["data"]["warnings"] == []
    with fitz.open(result["data"]["path"]) as document:
        assert any((image[2], image[3]) == (60, 30)
                   for page in document for image in page.get_images(full=True))
        assert "DATA TAIL" in "".join(page.get_text() for page in document)


def test_explicit_gif_file_uses_shared_validation_and_static_frame_warning(
    pdf_create, markdown_stash,
):
    source_space, _ = markdown_stash
    animation = _saved_raster(source_space, animated=True)
    original = Path(animation["path"]).read_bytes()

    result = pdf_create.action_create({
        "space_id": source_space.space_id, "files": [animation["ref"]],
        "output_name": "explicit-animation.pdf",
    })

    assert any("first frame" in warning.lower() for warning in result["data"]["warnings"])
    with fitz.open(result["data"]["path"]) as document:
        references = {image[0] for page in document for image in page.get_images(full=True)}
        assert references
        for reference in references:
            with Image.open(io.BytesIO(document.extract_image(reference)["image"])) as image:
                assert image.convert("RGB").getpixel((40, 20)) == (220, 30, 20)
    assert Path(animation["path"]).read_bytes() == original
