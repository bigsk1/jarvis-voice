"""Every Stash ingestion path must validate GIF bytes before durable writes."""

import builtins
import hashlib
import io
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from lib import stash_helper


@pytest.fixture(scope="module")
def animation():
    palette = [0, 0, 0, 255, 0, 0, 0, 0, 255, 0, 255, 0] + [0] * 756
    frames = []
    for index in range(3):
        frame = Image.new("P", (10, 6), 0)
        frame.putpalette(palette)
        frame.paste(index + 1, (index + 1, 1, index + 5, 5))
        frames.append(frame)
    output = io.BytesIO()
    frames[0].save(
        output, "GIF", save_all=True, append_images=frames[1:],
        duration=[80, 160, 240], loop=2, transparency=0, disposal=2, optimize=False,
    )
    return output.getvalue()


@pytest.fixture
def space(tmp_path):
    result = stash_helper.StashSpace("gif_validation_test", tmp_path)
    result.create()
    return result


def _save(space, monkeypatch, source, data, *, name="animation.gif", mime="image/gif",
          on_conflict="error"):
    writer = stash_helper.StashFile(space)
    if source == "binary":
        return writer.save_binary(
            data, name, mime_type=mime, on_conflict=on_conflict, tool_origin="read_email",
        )
    download = Mock(return_value=(data, mime, "https://cdn.example.test/original.gif"))
    monkeypatch.setattr(stash_helper, "safe_download", download)
    saved = writer.save_from_url(
        "https://example.test/redirect", name=name, on_conflict=on_conflict, tool_origin="stash",
    )
    download.assert_called_once_with("https://example.test/redirect")
    return saved


def _persisted_file(space, file_id):
    metadata = json.loads(space.meta_path.read_text())
    return next(row for row in metadata["files"] if row["file_id"] == file_id)


def _malformed_animation(data, kind):
    if kind == "missing_trailer":
        assert data.endswith(b";")
        return data[:-1]
    if kind == "missing_later_frame":
        # Removing a complete later frame still leaves decodable earlier frames.
        # A decoder's seek EOF must not be mistaken for the GIF trailer.
        last_control = data.rfind(b"\x21\xf9\x04")
        assert last_control > 0
        return data[:last_control]
    with Image.open(io.BytesIO(data)) as image:
        image.seek(2)
        final_data_offset = image.tile[0].offset
    if kind == "partial_later_frame_header":
        return data[:final_data_offset - 2]
    if kind == "corrupt_later_frame_data":
        # Preserve the sub-block lengths and trailer; only full frame decoding
        # can reject this damaged LZW payload after the valid earlier frames.
        payload_offset = final_data_offset + 1
        return data[:payload_offset] + b"\xff\xff\xff" + data[payload_offset + 3:]
    raise AssertionError(f"Unknown malformed fixture: {kind}")


@pytest.mark.parametrize("source", ["binary", "url"])
def test_valid_gif_preserves_animation_transparency_timing_and_exact_hash(
    space, monkeypatch, animation, source,
):
    saved = _save(space, monkeypatch, source, animation)

    assert Path(saved["path"]).read_bytes() == animation
    assert saved["mime_type"] == "image/gif"
    assert saved["hash_sha256"] == hashlib.sha256(animation).hexdigest()
    assert saved["size_bytes"] == len(animation)
    persisted = _persisted_file(space, saved["file_id"])
    assert persisted["hash_sha256"] == saved["hash_sha256"]
    assert persisted["mime_type"] == "image/gif"
    for metadata in (saved, persisted):
        assert metadata["format"] == "gif"
        assert metadata["animated"] is True
        assert metadata["frame_count"] == 3
        assert metadata["duration_ms"] == 480
        assert metadata["frame_durations_ms"] == [80, 160, 240]
        assert metadata["has_transparency"] is True
        assert metadata["decoded_pixels"] == 180
        assert (metadata["width"], metadata["height"]) == (10, 6)
        assert metadata["gif_validation"] == {
            "policy_version": 1,
            "decoded_all_frames": True,
            "max_size_bytes": stash_helper.GIF_MAX_FILE_SIZE,
            "max_frames": stash_helper.STRICT_GIF_MAX_FRAMES,
            "max_decoded_pixels": stash_helper.STRICT_IMAGE_MAX_PIXELS,
            "declared_mime_type": "image/gif",
            "declared_filename": "animation.gif",
        }
    with Image.open(saved["path"]) as decoded:
        assert decoded.n_frames == 3
        assert decoded.info["loop"] == 2
        durations = []
        transparent = []
        for index in range(decoded.n_frames):
            decoded.seek(index)
            durations.append(decoded.info["duration"])
            transparent.append(decoded.convert("RGBA").getextrema()[3][0] == 0)
    assert durations == [80, 160, 240]
    assert all(transparent)
    if source == "url":
        assert persisted["source_url"] == "https://example.test/redirect"
        assert persisted["final_url"] == "https://cdn.example.test/original.gif"


@pytest.mark.parametrize("source", ["binary", "url"])
@pytest.mark.parametrize(
    "kind",
    ["missing_trailer", "missing_later_frame", "partial_later_frame_header", "corrupt_later_frame_data"],
)
def test_incomplete_or_corrupt_later_frames_are_rejected_before_any_write(
    space, monkeypatch, animation, source, kind,
):
    original_meta = space.meta_path.read_bytes()

    with pytest.raises(stash_helper.SecurityError):
        _save(space, monkeypatch, source, _malformed_animation(animation, kind))

    assert space.meta_path.read_bytes() == original_meta
    assert sorted(path.name for path in space.space_path.iterdir()) == ["meta.json"]


@pytest.mark.parametrize(
    "kind",
    ["missing_trailer", "missing_later_frame", "partial_later_frame_header", "corrupt_later_frame_data"],
)
def test_shared_inspector_requires_complete_structure_and_decodable_later_frames(animation, kind):
    with pytest.raises(stash_helper.SecurityError):
        stash_helper.inspect_gif_image(_malformed_animation(animation, kind))


@pytest.mark.parametrize("source", ["binary", "url"])
@pytest.mark.parametrize(
    "name,mime,payload",
    [
        ("attachment.gif", "application/octet-stream", b"not an image"),
        ("attachment.bin", "image/gif", b"<html>not an image</html>"),
        ("attachment.gif", "image/gif", b"GIF89a"),
        ("attachment.bin", "application/octet-stream", b"GIF89a malformed file"),
    ],
)
def test_gif_byte_signatures_and_filename_or_mime_claims_cannot_bypass_validation(
    space, monkeypatch, source, name, mime, payload,
):
    with pytest.raises(stash_helper.SecurityError):
        _save(space, monkeypatch, source, payload, name=name, mime=mime)

    assert json.loads(space.meta_path.read_text())["files"] == []
    assert not (space.space_path / name).exists()


@pytest.mark.parametrize("source", ["binary", "url"])
@pytest.mark.parametrize(
    "name,mime,normalized_declared",
    [
        ("attachment.gif", "image/gif", "image/gif"),
        ("attachment.GIF", "IMAGE/GIF; charset=binary", "image/gif"),
        ("attachment.gif", "image/x-gif", "image/x-gif"),
        ("attachment.bin", "application/octet-stream", "application/octet-stream"),
        ("attachment.dat", "binary/octet-stream", "binary/octet-stream"),
        ("attachment.tmp", "application/binary", "application/binary"),
        ("attachment", "", ""),
    ],
)
def test_valid_gif_allows_generic_or_gif_claims_and_records_the_original_claims(
    space, monkeypatch, animation, source, name, mime, normalized_declared,
):
    saved = _save(space, monkeypatch, source, animation, name=name, mime=mime)

    assert saved["name"] == name
    assert saved["mime_type"] == "image/gif"
    assert Path(saved["path"]).read_bytes() == animation
    persisted = _persisted_file(space, saved["file_id"])
    assert persisted["mime_type"] == "image/gif"
    assert persisted["gif_validation"]["declared_filename"] == name
    assert persisted["gif_validation"]["declared_mime_type"] == normalized_declared


@pytest.mark.parametrize("source", ["binary", "url"])
@pytest.mark.parametrize(
    "name,mime",
    [
        ("attachment.png", "image/gif"),
        ("attachment.txt", "application/octet-stream"),
        ("attachment.gif", "image/png"),
        ("attachment.bin", "text/plain"),
    ],
)
def test_real_gif_bytes_do_not_override_contradictory_specific_claims(
    space, monkeypatch, animation, source, name, mime,
):
    with pytest.raises(stash_helper.SecurityError):
        _save(space, monkeypatch, source, animation, name=name, mime=mime)

    assert json.loads(space.meta_path.read_text())["files"] == []
    assert not (space.space_path / name).exists()


@pytest.mark.parametrize("source", ["binary", "url"])
@pytest.mark.parametrize("name,mime", [("attachment.gif", "image/png"), ("attachment.bin", "image/gif")])
def test_real_png_cannot_be_admitted_under_a_gif_filename_or_mime_claim(
    space, monkeypatch, source, name, mime,
):
    output = io.BytesIO()
    Image.new("RGB", (2, 2), "blue").save(output, "PNG")

    with pytest.raises(stash_helper.SecurityError):
        _save(space, monkeypatch, source, output.getvalue(), name=name, mime=mime)

    assert json.loads(space.meta_path.read_text())["files"] == []


def test_trailing_padding_is_preserved_while_only_the_complete_animation_is_decoded(
    space, animation,
):
    payload = animation + b"\x00" * 32 + b"original trailing bytes"

    saved = stash_helper.StashFile(space).save_binary(payload, "animation.gif", mime_type="image/gif")

    assert Path(saved["path"]).read_bytes() == payload
    assert saved["hash_sha256"] == hashlib.sha256(payload).hexdigest()
    assert saved["size_bytes"] == len(payload)
    assert saved["frame_count"] == 3
    assert saved["gif_validation"]["decoded_all_frames"] is True


@pytest.mark.parametrize("source", ["binary", "url"])
@pytest.mark.parametrize(
    "limit_name,value,error_fragment",
    [
        ("GIF_MAX_FILE_SIZE", None, "byte"),
        ("STRICT_GIF_MAX_FRAMES", 2, "frame"),
        ("STRICT_IMAGE_MAX_PIXELS", 179, "pixel"),
    ],
)
def test_gif_byte_frame_and_cumulative_pixel_limits_apply_to_every_ingestion_path(
    space, monkeypatch, animation, source, limit_name, value, error_fragment,
):
    monkeypatch.setattr(stash_helper, limit_name, len(animation) - 1 if value is None else value)

    with pytest.raises(stash_helper.SecurityError, match=error_fragment):
        _save(space, monkeypatch, source, animation)

    assert json.loads(space.meta_path.read_text())["files"] == []
    assert not (space.space_path / "animation.gif").exists()


@pytest.mark.parametrize("source", ["binary", "url"])
def test_exact_byte_frame_and_cumulative_pixel_limits_are_inclusive(
    space, monkeypatch, animation, source,
):
    monkeypatch.setattr(stash_helper, "GIF_MAX_FILE_SIZE", len(animation))
    monkeypatch.setattr(stash_helper, "STRICT_GIF_MAX_FRAMES", 3)
    monkeypatch.setattr(stash_helper, "STRICT_IMAGE_MAX_PIXELS", 180)

    saved = _save(space, monkeypatch, source, animation)

    assert Path(saved["path"]).read_bytes() == animation
    assert saved["gif_validation"]["max_size_bytes"] == len(animation)
    assert saved["gif_validation"]["max_frames"] == 3
    assert saved["gif_validation"]["max_decoded_pixels"] == 180


@pytest.mark.parametrize("source", ["binary", "url"])
def test_rejected_gif_overwrite_preserves_original_bytes_and_metadata(
    space, monkeypatch, animation, source,
):
    original = _save(space, monkeypatch, source, animation)
    original_meta = space.meta_path.read_bytes()
    persisted = deepcopy(_persisted_file(space, original["file_id"]))

    with pytest.raises(stash_helper.SecurityError):
        _save(space, monkeypatch, source, animation[:-1], on_conflict="overwrite")

    assert Path(original["path"]).read_bytes() == animation
    assert space.meta_path.read_bytes() == original_meta
    assert _persisted_file(space, original["file_id"]) == persisted


@pytest.mark.parametrize("source", ["binary", "url"])
def test_gif_validation_failure_has_no_generic_storage_fallback(
    space, monkeypatch, animation, source,
):
    inspect = Mock(side_effect=stash_helper.SecurityError("GIF validation failed"))
    monkeypatch.setattr(stash_helper, "inspect_gif_image", inspect)

    with pytest.raises(stash_helper.SecurityError, match="GIF validation failed"):
        _save(space, monkeypatch, source, animation)

    inspect.assert_called_once()
    assert json.loads(space.meta_path.read_text())["files"] == []
    assert not (space.space_path / "animation.gif").exists()


def test_gif_ingestion_requires_decoder_instead_of_accepting_unchecked_bytes(
    space, monkeypatch, animation,
):
    original_import = builtins.__import__

    def no_pillow(name, *args, **kwargs):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("Decoder deliberately unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_pillow)

    with pytest.raises(stash_helper.SecurityError, match="Pillow"):
        stash_helper.StashFile(space).save_binary(animation, "animation.gif", mime_type="image/gif")

    assert json.loads(space.meta_path.read_text())["files"] == []


@pytest.mark.parametrize("source", ["binary", "url"])
def test_non_gif_generic_saves_keep_existing_behavior(space, monkeypatch, source):
    payload = b"Existing generic storage does not normalize JPEG bytes."
    inspect = Mock(side_effect=AssertionError("Non-GIF bytes reached the GIF decoder"))
    monkeypatch.setattr(stash_helper, "inspect_gif_image", inspect)

    saved = _save(space, monkeypatch, source, payload, name="reference.jpg", mime="image/jpeg")

    assert Path(saved["path"]).read_bytes() == payload
    assert saved["mime_type"] == "image/jpeg"
    assert saved["hash_sha256"] == hashlib.sha256(payload).hexdigest()
    inspect.assert_not_called()


@pytest.mark.parametrize("signature", ["GIF87a", "GIF89a"])
def test_authored_text_with_gif_signature_remains_plain_text(space, monkeypatch, signature):
    content = f"{signature} this is a note, not an animation."
    inspect = Mock(side_effect=AssertionError("Authored text reached the GIF decoder"))
    monkeypatch.setattr(stash_helper, "inspect_gif_image", inspect)

    saved = stash_helper.StashFile(space).save_text(content, "notes.txt")

    assert Path(saved["path"]).read_bytes() == content.encode("utf-8")
    assert saved["mime_type"] == "text/plain"
    assert "gif_validation" not in _persisted_file(space, saved["file_id"])
    inspect.assert_not_called()


@pytest.mark.parametrize("writer", ["save_text", "save_json"])
@pytest.mark.parametrize("name", ["notes.gif", "a" * 196 + ".gif.txt"])
def test_authored_text_and_json_cannot_bypass_explicit_gif_filename_claims(space, writer, name):
    content = "GIF89a this is a note"

    with pytest.raises(stash_helper.SecurityError):
        getattr(stash_helper.StashFile(space), writer)(content, name)

    assert json.loads(space.meta_path.read_text())["files"] == []
    assert not (space.space_path / stash_helper.sanitize_filename(name)).exists()


@pytest.mark.parametrize("source", ["binary", "url"])
def test_untrusted_text_with_gif_signature_still_requires_validation(space, monkeypatch, source):
    with pytest.raises(stash_helper.SecurityError):
        _save(space, monkeypatch, source, b"GIF89a this is a note", name="notes.txt", mime="text/plain")

    assert json.loads(space.meta_path.read_text())["files"] == []


@pytest.mark.parametrize("source", ["binary", "url"])
def test_filename_truncation_cannot_create_an_unvalidated_gif_claim(space, monkeypatch, source):
    name = "a" * 196 + ".gif.txt"
    assert stash_helper.sanitize_filename(name).endswith(".gif")

    with pytest.raises(stash_helper.SecurityError):
        _save(space, monkeypatch, source, b"not a GIF", name=name, mime="application/octet-stream")

    assert json.loads(space.meta_path.read_text())["files"] == []
    assert not (space.space_path / stash_helper.sanitize_filename(name)).exists()


@pytest.mark.parametrize("source", ["binary", "url"])
def test_filename_truncation_cannot_hide_a_specific_mismatch_for_real_gif_bytes(
    space, monkeypatch, animation, source,
):
    name = "a" * 196 + ".png.gif"
    assert stash_helper.sanitize_filename(name).endswith(".png")

    with pytest.raises(stash_helper.SecurityError):
        _save(space, monkeypatch, source, animation, name=name, mime="image/gif")

    assert json.loads(space.meta_path.read_text())["files"] == []
