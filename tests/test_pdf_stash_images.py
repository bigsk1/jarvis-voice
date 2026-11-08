"""Stash report images stay bounded, confined, and self-contained in the PDF."""

import builtins
import importlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from PIL import Image

from lib import paths, pdf_rendering, stash_helper


@pytest.fixture
def image_space(tmp_path, monkeypatch):
    root = tmp_path / "configured-stash"
    root.mkdir()
    # Both supported import forms consult the same explicit process override.
    # No private mode configuration or operator Stash is used by these tests.
    monkeypatch.setenv("JARVIS_OVERRIDE_STASH_DIR", str(root))
    space = stash_helper.StashSpace("space_pdf_images", root)
    space.create()
    return SimpleNamespace(root=root, space=space)


def _raster(format="PNG", size=(96, 48), color=(18, 74, 132)):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format)
    return output.getvalue()


def _animation():
    output = io.BytesIO()
    first = Image.new("RGB", (12, 8), (30, 120, 240))
    second = Image.new("RGB", (12, 8), (240, 80, 30))
    first.save(output, "GIF", save_all=True, append_images=[second], duration=[80, 120], loop=0)
    return output.getvalue()


def _save(image_space, data=None, *, name="chart.png", mime="image/png"):
    return stash_helper.StashFile(image_space.space).save_binary(
        data if data is not None else _raster(), name, mime_type=mime,
    )


def _render(tmp_path, source, *, name="report.pdf"):
    output = tmp_path / name
    metadata = pdf_rendering.render_markdown_pdf(source, str(output), "Report images")
    assert output.read_bytes().startswith(b"%PDF-")
    with fitz.open(output) as document:
        text = " ".join(" ".join(page.get_text() for page in document).split())
        images = [
            document.extract_image(reference)
            for reference in {row[0] for page in document for row in page.get_images(full=True)}
        ]
    return output, metadata, text, images


def _assert_placeholder(tmp_path, source, *, alt="Blocked image"):
    output, metadata, text, images = _render(tmp_path, f"Before image.\n\n![{alt}]({source})\n\nAfter image.")
    assert images == []
    assert "[Image:" in text and alt in text
    assert "Before image." in text and "After image." in text
    assert metadata["warnings"], "Unembedded source must be reported to the PDF caller"
    return output, metadata, text


@pytest.mark.parametrize("format,extension,mime", [
    ("PNG", "png", "image/png"),
    ("JPEG", "jpg", "image/jpeg"),
    ("WEBP", "webp", "image/webp"),
])
def test_stash_rasters_embed_and_preserve_original_bytes_and_metadata(
    image_space, tmp_path, format, extension, mime,
):
    data = _raster(format)
    saved = _save(image_space, data, name=f"report-chart.{extension}", mime=mime)
    manifest_before = image_space.space.meta_path.read_bytes()

    _, metadata, text, images = _render(
        tmp_path, f"# Chart results\n\nBefore the chart.\n\n![Report chart]({saved['ref']})\n\nAfter the chart.",
    )

    assert len(images) == 1
    assert (images[0]["width"], images[0]["height"]) == (96, 48)
    assert "Chart results" in text and "Before the chart." in text and "After the chart." in text
    assert "[Image:" not in text
    assert metadata["warnings"] == []
    assert Path(saved["path"]).read_bytes() == data
    assert image_space.space.meta_path.read_bytes() == manifest_before


def test_stash_image_stays_between_surrounding_markdown_text(image_space, tmp_path):
    saved = _save(image_space)
    output, metadata, text, _ = _render(
        tmp_path, f"BEFORE IMAGE SENTINEL\n\n![Chart]({saved['ref']})\n\nAFTER IMAGE SENTINEL",
    )
    with fitz.open(output) as document:
        page = document[0]
        before = page.search_for("BEFORE IMAGE SENTINEL")[0]
        after = page.search_for("AFTER IMAGE SENTINEL")[0]
        chart = page.get_image_rects(page.get_images()[0][0])[0]
        assert before.y1 <= chart.y0
        assert chart.y1 <= after.y0
    assert text.index("BEFORE IMAGE SENTINEL") < text.index("AFTER IMAGE SENTINEL")
    assert metadata["warnings"] == []


def test_inline_list_and_quote_images_preserve_text_and_list_numbering(image_space, tmp_path):
    saved = _save(image_space)
    _, metadata, text, images = _render(tmp_path, (
        f"An **inline lead** ![Inline chart]({saved['ref']}) and *inline tail*.\n\n"
        f"3. List lead ![List chart]({saved['ref']}) list tail.\n"
        "4. Following item.\n\n"
        f"> Quote lead ![Quote chart]({saved['ref']}) quote tail."
    ))
    assert images
    for phrase in ("inline lead", "inline tail", "List lead", "list tail", "Following item", "Quote lead", "quote tail"):
        assert phrase in text
    assert text.index("inline lead") < text.index("inline tail") < text.index("List lead")
    assert text.index("list tail") < text.index("Following item") < text.index("Quote lead")
    assert "3." in text and "4." in text
    assert "[Image:" not in text
    assert metadata["warnings"] == []


def test_markdown_table_embeds_stash_image_and_preserves_cell_content(image_space, tmp_path):
    saved = _save(image_space)
    _, metadata, text, images = _render(tmp_path, (
        "Before table.\n\n| Region | Findings |\n| --- | --- |\n"
        f"| West | Cell lead ![Revenue chart]({saved['ref']}) cell tail. |\n"
        "| East | Other complete finding. |\n\nAfter table."
    ))
    assert images
    for phrase in ("Before table.", "Region", "Findings", "West", "Cell lead", "cell tail.", "East", "Other complete finding.", "After table."):
        assert phrase in text
    assert "[Image:" not in text
    assert metadata["warnings"] == []


@pytest.mark.parametrize("source", [
    "http://127.0.0.1/private.png",
    "data:image/png;base64,iVBORw0KGgo=",
    "/tmp/private-report-image.png",
    "./private-report-image.png",
    "../private-report-image.png",
])
def test_invalid_or_unconfined_markdown_images_do_not_reach_image_loader(
    tmp_path, monkeypatch, source,
):
    def forbidden(*_args, **_kwargs):
        pytest.fail("An invalid or unconfined image must not reach FPDF's image loader")
    monkeypatch.setattr(pdf_rendering.DocumentPDF, "image", forbidden)
    _assert_placeholder(tmp_path, source)


def test_file_scheme_keeps_markdown_parser_refusal_and_never_loads_resource(tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("A file URL must not reach FPDF's image loader")
    monkeypatch.setattr(pdf_rendering.DocumentPDF, "image", forbidden)
    _, _, text, images = _render(tmp_path, "![File image](file:///etc/passwd)\n\nComplete tail.")
    assert "![File image](file:///etc/passwd)" in text
    assert "Complete tail." in text and images == []


def test_local_absolute_markdown_image_is_not_read_even_when_it_exists(tmp_path, monkeypatch):
    source = tmp_path / "available-but-not-stash.png"
    source.write_bytes(_raster())
    original_open = builtins.open
    original_io_open = io.open

    def guard(opener):
        def checked(file, *args, **kwargs):
            if isinstance(file, (str, Path)) and Path(file).resolve() == source.resolve():
                pytest.fail("Absolute Markdown images must not be read from disk")
            return opener(file, *args, **kwargs)
        return checked

    monkeypatch.setattr(builtins, "open", guard(original_open))
    monkeypatch.setattr(io, "open", guard(original_io_open))
    _assert_placeholder(tmp_path, str(source))


@pytest.mark.parametrize("source", [
    "stash://missing-space/missing-image",
    "stash://space_pdf_images/missing-image",
])
def test_missing_stash_images_have_placeholder_and_actionable_warning(image_space, tmp_path, source):
    _, metadata, _ = _assert_placeholder(tmp_path, source, alt="Missing chart")
    assert any(
        any(term in warning.lower() for term in ("missing", "not found", "unavailable", "does not exist"))
        for warning in metadata["warnings"]
    )


@pytest.mark.parametrize("payload", [
    b"not actually a raster image",
    b"\x89PNG\r\n\x1a\ntruncated",
    b'<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10"><rect width="20" height="10"/></svg>',
    b"%PDF-1.7\nnot a raster\n%%EOF",
    _raster("BMP", size=(4, 3)),
], ids=["text", "truncated-png", "svg", "pdf", "bmp"])
def test_actual_raster_content_is_checked_despite_png_name_and_mime(image_space, tmp_path, payload):
    saved = _save(image_space, payload)
    _, metadata, _ = _assert_placeholder(tmp_path, saved["ref"], alt="Invalid chart")
    assert any(
        any(term in warning.lower() for term in ("invalid", "unsupported", "decode", "raster", "cannot identify", "malformed"))
        for warning in metadata["warnings"]
    )


@pytest.mark.parametrize("format,mime,extension", [("PNG", "image/png", "png"), ("WEBP", "image/webp", "webp")])
def test_animated_png_and_webp_are_not_silently_reduced_to_frame_zero(
    image_space, tmp_path, format, mime, extension,
):
    output = io.BytesIO()
    first = Image.new("RGB", (12, 8), (20, 140, 230))
    second = Image.new("RGB", (12, 8), (230, 140, 20))
    first.save(output, format, save_all=True, append_images=[second], duration=100, loop=0)
    saved = _save(image_space, output.getvalue(), name=f"animated.{extension}", mime=mime)
    _, metadata, _ = _assert_placeholder(tmp_path, saved["ref"], alt="Unsupported animation")
    assert any("animat" in warning.lower() for warning in metadata["warnings"])


@pytest.mark.parametrize("source", [
    "stash://../outside.png",
    "stash://space_pdf_images/../outside.png",
    "stash://space_pdf_images/%2e%2e%2foutside.png",
    "stash://space_pdf_images/chart.png?file=/tmp/outside.png",
    "stash://space_pdf_images/chart.png#fragment",
])
def test_malformed_or_traversing_stash_refs_remain_placeholders(image_space, tmp_path, source):
    (tmp_path / "outside.png").write_bytes(_raster())
    _assert_placeholder(tmp_path, source, alt="Unsafe reference")


@pytest.mark.parametrize("escape", ["relative-metadata", "absolute-metadata", "file-symlink", "metadata-symlink", "space-symlink"])
def test_stash_resolution_never_reads_outside_the_selected_space(
    image_space, tmp_path, monkeypatch, escape,
):
    saved = _save(image_space)
    outside = tmp_path / "outside-stash"
    outside.mkdir()
    outside_image = outside / "outside.png"
    outside_image.write_bytes(_raster(size=(25, 15)))
    manifest = json.loads(image_space.space.meta_path.read_text())
    if escape in {"relative-metadata", "absolute-metadata"}:
        manifest["files"][0]["stored_name"] = (
            "../../outside-stash/outside.png" if escape == "relative-metadata" else str(outside_image)
        )
        image_space.space.meta_path.write_text(json.dumps(manifest))
    elif escape == "file-symlink":
        Path(saved["path"]).unlink()
        Path(saved["path"]).symlink_to(outside_image)
    elif escape == "metadata-symlink":
        outside_manifest = outside / "meta.json"
        outside_manifest.write_text(json.dumps(manifest))
        image_space.space.meta_path.unlink()
        image_space.space.meta_path.symlink_to(outside_manifest)
    else:
        outside_manifest = outside / "meta.json"
        outside_manifest.write_text(json.dumps(manifest))
        (outside / "chart.png").write_bytes(_raster())
        link = image_space.root / "space_symlink"
        link.symlink_to(outside, target_is_directory=True)
        saved["ref"] = f"stash://space_symlink/{saved['file_id']}"

    original_open = builtins.open
    original_io_open = io.open

    def guard(opener):
        def checked(file, *args, **kwargs):
            if isinstance(file, (str, Path)) and Path(file).resolve().is_relative_to(outside):
                pytest.fail("Rejected Stash escapes must not read outside image or metadata bytes")
            return opener(file, *args, **kwargs)
        return checked

    monkeypatch.setattr(builtins, "open", guard(original_open))
    monkeypatch.setattr(io, "open", guard(original_io_open))
    _assert_placeholder(tmp_path, saved["ref"], alt="Escaping chart")


def test_stash_image_still_obeys_shared_restricted_read_policy(image_space, tmp_path, monkeypatch):
    saved = _save(image_space)
    blocked = Path(saved["path"]).resolve()
    policy_modules = {paths, importlib.import_module(stash_helper.assert_not_restricted_read_path.__module__)}
    for policy in policy_modules:
        monkeypatch.setattr(policy, "get_restricted_read_paths", lambda: [str(blocked)])
    original_open = builtins.open
    original_io_open = io.open

    def guard(opener):
        def checked(file, *args, **kwargs):
            if isinstance(file, (str, Path)) and Path(file).resolve() == blocked:
                pytest.fail("A Stash reference must not bypass shared restricted reads")
            return opener(file, *args, **kwargs)
        return checked

    monkeypatch.setattr(builtins, "open", guard(original_open))
    monkeypatch.setattr(io, "open", guard(original_io_open))
    _, metadata, _ = _assert_placeholder(tmp_path, saved["ref"], alt="Restricted chart")
    assert any("restricted" in warning.lower() for warning in metadata["warnings"])


@pytest.mark.parametrize("limit,value", [("MAX_IMAGE_BYTES", 32), ("MAX_STILL_IMAGE_BYTES", 32), ("MAX_IMAGE_PIXELS", 32)])
def test_individual_image_limits_report_visible_omission(image_space, tmp_path, monkeypatch, limit, value):
    saved = _save(image_space)
    monkeypatch.setattr(pdf_rendering, limit, value)
    _, metadata, _ = _assert_placeholder(tmp_path, saved["ref"], alt="Over limit chart")
    assert any(
        any(term in warning.lower() for term in ("limit", "exceed", "too large", "budget"))
        for warning in metadata["warnings"]
    )


@pytest.mark.parametrize("limit", ["MAX_EMBEDDED_IMAGES", "MAX_TOTAL_IMAGE_BYTES", "MAX_TOTAL_IMAGE_PIXELS"])
def test_per_document_image_budget_keeps_earlier_chart_and_later_text(
    image_space, tmp_path, monkeypatch, limit,
):
    first_data = _raster(size=(32, 16))
    second_data = _raster(size=(40, 20), color=(132, 74, 18))
    first = _save(image_space, first_data, name="first.png")
    second = _save(image_space, second_data, name="second.png")
    limits = {
        "MAX_EMBEDDED_IMAGES": 1,
        "MAX_TOTAL_IMAGE_BYTES": len(first_data) + len(second_data) - 1,
        "MAX_TOTAL_IMAGE_PIXELS": 32 * 16 + 40 * 20 - 1,
    }
    monkeypatch.setattr(pdf_rendering, limit, limits[limit])
    _, metadata, text, images = _render(tmp_path, (
        f"![First chart]({first['ref']})\n\n![Second chart]({second['ref']})\n\n"
        "FINAL COMPLETE TEXT SENTINEL"
    ))
    assert len(images) == 1 and images[0]["width"] == 32
    assert "[Image: Second chart" in text
    assert "FINAL COMPLETE TEXT SENTINEL" in text
    assert any(
        any(term in warning.lower() for term in ("limit", "exceed", "budget", "maximum"))
        for warning in metadata["warnings"]
    )


def test_large_stash_raster_is_downsampled_for_pdf_without_mutating_source(image_space, tmp_path):
    data = _raster(size=(3000, 1500))
    saved = _save(image_space, data)
    _, metadata, _, images = _render(tmp_path, f"![Large chart]({saved['ref']})")
    assert len(images) == 1
    assert max(images[0]["width"], images[0]["height"]) <= 2048
    assert images[0]["width"] / images[0]["height"] == pytest.approx(2, abs=0.01)
    assert Path(saved["path"]).read_bytes() == data
    assert metadata["page_count"] == 1


def test_tall_chart_fits_printable_page_without_losing_following_text(image_space, tmp_path):
    saved = _save(image_space, _raster(size=(16, 1600)))
    output, _, text, images = _render(tmp_path, (
        "A report paragraph before the tall chart.\n\n" * 25
        + f"![Tall chart]({saved['ref']})\n\nFINAL CHART TAIL SENTINEL"
    ))
    assert len(images) == 1 and "FINAL CHART TAIL SENTINEL" in text
    with fitz.open(output) as document:
        placements = [
            (page, rectangle)
            for page in document for row in page.get_images(full=True)
            for rectangle in page.get_image_rects(row[0])
        ]
        assert len(placements) == 1
        page, chart = placements[0]
        assert chart.x0 >= 0 and chart.y0 >= 0
        assert chart.x1 <= page.rect.width and chart.y1 < page.rect.height - 25
        assert chart.width / chart.height == pytest.approx(0.01, abs=0.001)


def test_valid_gif_embeds_frame_zero_with_explicit_static_scope_and_no_mutation(image_space, tmp_path):
    animation = _animation()
    saved = _save(image_space, animation, name="animation.gif", mime="image/gif")
    manifest_before = image_space.space.meta_path.read_bytes()
    _, metadata, text, images = _render(tmp_path, f"![Animated chart]({saved['ref']})\n\nGIF tail text.")
    assert len(images) == 1
    with Image.open(io.BytesIO(images[0]["image"])) as embedded:
        assert embedded.convert("RGB").getpixel((0, 0)) == (30, 120, 240)
    assert "GIF tail text." in text
    assert any("gif" in warning.lower() and "first frame" in warning.lower() for warning in metadata["warnings"])
    assert Path(saved["path"]).read_bytes() == animation
    assert image_space.space.meta_path.read_bytes() == manifest_before


def test_single_frame_gif_does_not_claim_uninspected_animation(image_space, tmp_path):
    saved = _save(image_space, _raster("GIF", size=(12, 8)), name="still.gif", mime="image/gif")
    _, metadata, _, images = _render(tmp_path, f"![Still GIF]({saved['ref']})")
    assert len(images) == 1
    assert metadata["warnings"] == []


def test_gif_with_invalid_later_data_is_not_embedded_even_when_first_frame_decodes(image_space, tmp_path):
    animation = _animation()
    saved = _save(image_space, animation, name="broken-animation.gif", mime="image/gif")
    # Seed a legacy/corrupted stored file rather than passing through today's
    # ingestion gate. Pillow can still decode its first frame without a trailer.
    damaged = animation[:-1]
    with Image.open(io.BytesIO(damaged)) as frame_zero:
        frame_zero.load()
        assert frame_zero.size == (12, 8)
    Path(saved["path"]).write_bytes(damaged)
    _, metadata, _ = _assert_placeholder(tmp_path, saved["ref"], alt="Corrupt animation")
    assert any(
        any(term in warning.lower() for term in ("gif", "truncat", "malformed", "invalid"))
        for warning in metadata["warnings"]
    )


def test_shared_renderer_embeds_stash_image_in_fresh_package_import(image_space, tmp_path):
    saved = _save(image_space)
    output = tmp_path / "fresh-process.pdf"
    # Pytest's application import setup also adds lib/ to sys.path. A clean
    # interpreter must support the documented package import without that setup.
    completed = subprocess.run(
        [
            sys.executable, "-c",
            "import json, sys; from lib.pdf_rendering import render_markdown_pdf; "
            "print(json.dumps(render_markdown_pdf(sys.argv[1], sys.argv[2])))",
            f"![Fresh process chart]({saved['ref']})\n\nFresh process tail.", str(output),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            "HOME": str(tmp_path), "PATH": os.defpath, "JARVIS_MODE": "cloud",
            "JARVIS_OVERRIDE_STASH_DIR": str(image_space.root), "JARVIS_RESTRICTED_TOOL_ENV": "1",
        },
        capture_output=True, text=True, timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["warnings"] == []
    with fitz.open(output) as document:
        assert any(page.get_images() for page in document)
        assert "Fresh process tail." in "".join(page.get_text() for page in document)


@pytest.mark.parametrize("kind", ["space", "metadata", "file"])
def test_cyclic_stash_symlink_keeps_placeholder_without_aborting_pdf(image_space, tmp_path, kind):
    saved = _save(image_space)
    if kind == "space":
        loop = image_space.root / "space_loop"
        loop.symlink_to(loop, target_is_directory=True)
        target = f"stash://space_loop/{saved['file_id']}"
    else:
        loop = image_space.space.meta_path if kind == "metadata" else Path(saved["path"])
        loop.unlink()
        loop.symlink_to(loop)
        target = saved["ref"]
    _assert_placeholder(tmp_path, target, alt="Cyclic source")


@pytest.mark.parametrize("manifest", [[], {"files": ["not-a-row"]}, {"files": None}])
def test_malformed_stash_metadata_shape_keeps_placeholder_and_complete_text(
    image_space, tmp_path, manifest,
):
    saved = _save(image_space)
    image_space.space.meta_path.write_text(json.dumps(manifest))
    _assert_placeholder(tmp_path, saved["ref"], alt="Malformed metadata chart")


def test_png_that_opens_but_fails_crc_verification_keeps_placeholder(image_space, tmp_path):
    data = bytearray(_raster(size=(4, 3)))
    chunk = data.index(b"IDAT")
    payload_size = int.from_bytes(data[chunk - 4:chunk], "big")
    data[chunk + 4 + payload_size] ^= 1
    with Image.open(io.BytesIO(data)) as image:
        assert image.size == (4, 3)
        with pytest.raises(SyntaxError, match="checksum"):
            image.verify()
    saved = _save(image_space, bytes(data))
    _assert_placeholder(tmp_path, saved["ref"], alt="Invalid checksum chart")
