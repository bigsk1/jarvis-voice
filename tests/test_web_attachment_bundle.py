"""Mixed-source validation through real committed Web upload metadata."""

from __future__ import annotations

import io
import sys
import uuid
import wave
from pathlib import Path

import fitz
import pytest
from server_package_utils import load_server_package
from werkzeug.datastructures import FileStorage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "jarvis-web"))
load_server_package("jarvis_web_bundle_test", ROOT / "jarvis-web" / "server")

from jarvis_web_bundle_test.services import (  # noqa: E402
    attachment_bundle as bundle,
)
from jarvis_web_bundle_test.services import (  # noqa: E402
    audio_upload,
    pdf_upload,
    text_upload,
)


@pytest.fixture(autouse=True)
def stash(tmp_path, monkeypatch):
    path = tmp_path / "stash"
    for module in (bundle, audio_upload, pdf_upload, text_upload):
        monkeypatch.setattr(module, "get_stash_dir", lambda: path)
    return path


def _text(name="note.md", content="Reference notes"):
    return text_upload.ingest_text_context({"name": name, "content": content})


def _pdf():
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "Source PDF")
        payload = document.tobytes()
    upload = FileStorage(stream=io.BytesIO(payload), filename="source.pdf", content_type="application/pdf")
    return pdf_upload.save_pdf_upload(upload, str(uuid.uuid4()))[0]


def _audio():
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0\0" * 1600)
    upload = FileStorage(stream=io.BytesIO(output.getvalue()), filename="recording.wav", content_type="audio/wav")
    return audio_upload.save_audio_upload(upload, str(uuid.uuid4()))[0]


def test_real_pdf_audio_text_plus_image_bundle_preserves_order():
    attachments = [_pdf(), _audio(), _text()]
    assert bundle.validate_attachments(attachments, "cloud", image_count=1) == attachments
    assert bundle.stored_attachments({"attachments": attachments}) == attachments


def test_two_independent_pdfs_are_valid_in_local_mode():
    attachments = [_pdf(), _pdf()]
    assert bundle.validate_attachments(attachments, "local") == attachments


@pytest.mark.parametrize("mode,documents,images,valid", [
    ("cloud", 5, 1, True), ("cloud", 5, 2, False),
    ("local", 1, 1, True), ("local", 2, 1, False),
    ("cloud", 0, 6, True), ("local", 0, 3, False),
])
def test_total_count_includes_images(mode, documents, images, valid):
    attachments = [_text(f"note{index}.txt") for index in range(documents)]
    if valid:
        assert bundle.validate_attachments(attachments, mode, images) == attachments
    else:
        with pytest.raises(bundle.AttachmentBundleError) as error:
            bundle.validate_attachments(attachments, mode, images)
        assert error.value.error_code == "attachment_count_invalid"


@pytest.mark.parametrize("raw", [{}, "source", [None], [{"kind": []}],
                                  [{"kind": "image", "stash_ref": "https://example.com/a.png"}]])
def test_malformed_bundle_is_rejected_with_typed_error(raw):
    with pytest.raises(bundle.AttachmentBundleError):
        bundle.validate_attachments(raw, "cloud")


@pytest.mark.parametrize("mode,images", [("other", 0), ("cloud", -1), ("cloud", "2"), ("cloud", True)])
def test_invalid_mode_or_image_count_is_rejected(mode, images):
    with pytest.raises(bundle.AttachmentBundleError):
        bundle.validate_attachments([], mode, images)


def test_empty_bundle_is_valid():
    assert bundle.validate_attachments(None, "cloud") == []
    assert bundle.validate_attachments([], "local") == []


def test_same_source_cannot_consume_two_slots_with_altered_metadata():
    attachment = _text()
    with pytest.raises(bundle.AttachmentBundleError) as error:
        bundle.validate_attachments([attachment, {**attachment, "filename": "different.txt"}], "cloud")
    assert error.value.error_code == "attachment_duplicate"


def test_client_paths_and_contents_do_not_override_source_metadata():
    attachments = [_pdf(), _audio(), _text()]
    forged = [{**item, "filename": "pretend.txt", "path": "/etc/passwd", "content": "fake", "size_bytes": 1}
              for item in attachments]
    assert bundle.validate_attachments(forged, "cloud") == attachments


def test_aggregate_text_limit_counts_stored_utf8_bytes():
    half = "é" * (text_upload.MAX_TEXT_BYTES // 4)
    attachments = [_text("one.txt", half), _text("two.txt", half)]
    assert bundle.validate_attachments(attachments, "local") == attachments
    attachments.append(_text("extra.txt", "x"))
    with pytest.raises(bundle.AttachmentBundleError) as error:
        bundle.validate_attachments(attachments, "cloud")
    assert error.value.error_code == "attachment_text_too_large"


def test_missing_source_rejects_entire_bundle_before_use(stash):
    attachments = [_pdf(), _text()]
    (stash / attachments[1]["space_id"] / attachments[1]["filename"]).unlink()
    with pytest.raises(bundle.AttachmentBundleError) as error:
        bundle.validate_attachments(attachments, "cloud")
    assert error.value.error_code == "text_attachment_unavailable"


def test_pdf_symlink_cannot_bypass_single_upload_validation(stash, tmp_path):
    attachment = _pdf()
    path = stash / attachment["space_id"] / attachment["filename"]
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(bundle.AttachmentBundleError) as error:
        bundle.validate_attachments([attachment], "cloud")
    assert error.value.error_code == "attachment_unavailable"


def test_stored_history_keeps_expired_references_without_content_or_paths(stash):
    attachments = [_pdf(), _text()]
    (stash / attachments[0]["space_id"] / attachments[0]["filename"]).unlink()
    source = [{**item, "content": "untrusted imported content", "path": "/etc/passwd"} for item in attachments]
    assert bundle.stored_attachments({"attachments": source}) == attachments


def test_stored_history_filters_malformed_duplicate_and_untrusted_references():
    attachment = _text()
    malformed = {**attachment, "stash_ref": "stash://../../etc/passwd"}
    wrong_kind = {**attachment, "kind": "pdf"}
    wrong_name = {**attachment, "filename": "../../private.txt"}
    assert bundle.stored_attachments({"attachments": [malformed, attachment, wrong_kind, wrong_name, attachment]}) == [attachment]
    assert bundle.stored_attachments(None) == []


def test_stored_history_is_bounded_to_six_sources():
    attachments = [_text(f"note{index}.txt") for index in range(7)]
    assert bundle.stored_attachments({"attachments": attachments}) == attachments[:6]
