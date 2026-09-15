"""Durable text source boundary: validation, retries, retention, and legacy input."""

from __future__ import annotations

import hashlib
import io
import json
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from flask import Flask
from server_package_utils import load_server_package
from werkzeug.datastructures import FileStorage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "jarvis-web"))
load_server_package("jarvis_web_text_test", ROOT / "jarvis-web" / "server")

from jarvis_web_text_test.routes import api  # noqa: E402
from jarvis_web_text_test.services import text_upload  # noqa: E402


@pytest.fixture(autouse=True)
def stash(tmp_path, monkeypatch):
    path = tmp_path / "stash"
    monkeypatch.setattr(text_upload, "get_stash_dir", lambda: path)
    monkeypatch.setattr(text_upload, "get_int", lambda name, default: 0 if "RATE_LIMIT" in name else default)
    text_upload.reset_text_upload_rate_limit_for_tests()
    yield path
    text_upload.reset_text_upload_rate_limit_for_tests()


def _file(payload=b"A durable note", name="notes.md", mime="text/markdown"):
    return FileStorage(stream=io.BytesIO(payload), filename=name, content_type=mime)


def _save(payload=b"A durable note", name="notes.md", upload_id=None):
    return text_upload.save_text_upload(_file(payload, name), upload_id or str(uuid.uuid4()))[0]


def _client():
    app = Flask(__name__)
    app.register_blueprint(api.api_bp)
    return app.test_client()


def _post(payload=b"A durable note", name="notes.md", upload_id=None, mode="cloud", mime="text/markdown"):
    return _client().post("/api/upload-text", data={
        "file": (io.BytesIO(payload), name, mime),
        "upload_id": upload_id or str(uuid.uuid4()), "mode": mode,
    }, content_type="multipart/form-data")


def test_text_upload_commits_original_bytes_and_source_retention(stash):
    payload = "\ufeff# Notes\r\nA café budget\r\n".encode("utf-8")
    response = _post(payload)
    assert response.status_code == 200
    attachment = response.get_json()["attachment"]
    assert attachment["kind"] == "text"
    assert attachment["sha256"] == hashlib.sha256(payload).hexdigest()
    assert attachment["size_bytes"] == len(payload)
    assert attachment["mime_type"] == "text/markdown"
    assert "content" not in attachment
    space = stash / attachment["space_id"]
    assert (space / attachment["filename"]).read_bytes() == payload
    meta = json.loads((space / "meta.json").read_text())
    assert meta["source"] == "web_text_upload"
    assert meta["labels"] == ["web_upload", "text"]
    assert meta["retention_policy"] == "source_artifact"
    assert meta["ttl_days"] > 0
    assert meta["files"][0]["tool_origin"] == "web_text_upload"
    assert text_upload.read_text_attachment(attachment) == "# Notes\r\nA café budget\r\n"
    assert not list((stash / ".incoming").iterdir())


def test_retry_preserves_first_filename_metadata_and_bytes(stash):
    upload_id = str(uuid.uuid4())
    first = _post(name="first.md", upload_id=upload_id).get_json()
    second = _post(name="renamed.txt", upload_id=upload_id).get_json()
    assert second["idempotent_replay"] is True
    assert first["attachment"] == second["attachment"]
    assert len(list(stash.glob("space_web_text_*"))) == 1
    assert not list((stash / ".incoming").iterdir())


def test_upload_identity_cannot_be_reused_with_changed_content(stash):
    upload_id = str(uuid.uuid4())
    first = _post(b"original", upload_id=upload_id).get_json()["attachment"]
    conflict = _post(b"changed", upload_id=upload_id)
    assert conflict.status_code == 409
    assert conflict.get_json()["error_code"] == "text_upload_id_conflict"
    assert text_upload.read_text_attachment(first) == "original"


def test_concurrent_retries_commit_one_source(stash):
    upload_id = str(uuid.uuid4())
    def save():
        return text_upload.save_text_upload(_file(), upload_id)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(save) for _ in range(2)]
        results = [future.result(timeout=5) for future in futures]
    assert results[0][0] == results[1][0]
    assert sorted(replay for _, replay in results) == [False, True]
    assert len(list(stash.glob("space_web_text_*"))) == 1
    assert not list((stash / ".incoming").iterdir())


@pytest.mark.parametrize("payload,name,mime,code", [
    (b"", "note.txt", "text/plain", "text_upload_empty"),
    (b"\xff\xfehi", "note.txt", "text/plain", "text_upload_encoding_invalid"),
    (b"a\x00b", "note.md", "text/markdown", "text_upload_encoding_invalid"),
    (b"x" * (text_upload.MAX_TEXT_BYTES + 1), "note.txt", "text/plain", "text_upload_too_large"),
    (b"valid", "note.exe", "text/plain", "text_upload_extension_invalid"),
    (b"valid", "note.txt", "application/pdf", "text_upload_mime_invalid"),
])
def test_invalid_input_never_commits_a_source(stash, payload, name, mime, code):
    response = _post(payload, name, mime=mime)
    assert response.status_code in (400, 413)
    assert response.get_json()["error_code"] == code
    assert not list(stash.glob("space_web_text_*"))


def test_full_100kb_content_survives_legacy_ingestion_without_clipping(stash):
    content = "é" * (text_upload.MAX_TEXT_BYTES // 2)
    attachment = text_upload.ingest_text_context({"name": "legacy.txt", "content": content, "size": 1})
    assert attachment["size_bytes"] == text_upload.MAX_TEXT_BYTES
    assert text_upload.read_text_attachment(attachment) == content
    assert (stash / attachment["space_id"] / "legacy.txt").stat().st_size == text_upload.MAX_TEXT_BYTES


@pytest.mark.parametrize("raw", [None, [], {}, {"content": 123}, {"content": "x", "name": ["bad"]}])
def test_malformed_legacy_inputs_have_typed_errors(raw):
    with pytest.raises(text_upload.TextUploadError):
        text_upload.ingest_text_context(raw)


def test_reference_ignores_client_content_paths_and_display_fields():
    attachment = _save()
    forged = {**attachment, "filename": "../../private.txt", "path": "/etc/passwd",
              "content": "Fake source", "sha256": "fake", "size_bytes": 9999999}
    assert text_upload.validate_text_attachment(forged) == attachment
    assert text_upload.read_text_attachment(forged) == "A durable note"


@pytest.mark.parametrize("reference", ["/etc/passwd", "stash://../private/f_0123456789ab",
                                        "stash://space_web_text_" + "a" * 32 + "/../../file",
                                        "https://example.com/note.txt"])
def test_untrusted_reference_is_rejected(reference):
    with pytest.raises(text_upload.TextUploadError) as error:
        text_upload.read_text_attachment({"kind": "text", "stash_ref": reference})
    assert error.value.error_code == "text_attachment_invalid"


@pytest.mark.parametrize("mutation", ["delete", "same_size_change", "symlink", "metadata_link"])
def test_missing_changed_or_linked_stored_source_is_unavailable(stash, tmp_path, mutation):
    attachment = _save(b"original")
    path = stash / attachment["space_id"] / attachment["filename"]
    if mutation == "delete":
        path.unlink()
    elif mutation == "same_size_change":
        path.write_bytes(b"tampered")
    elif mutation == "symlink":
        external = tmp_path / "external.txt"
        external.write_bytes(b"original")
        path.unlink()
        path.symlink_to(external)
    else:
        meta = path.parent / "meta.json"
        external = tmp_path / "external.json"
        external.write_bytes(meta.read_bytes())
        meta.unlink()
        meta.symlink_to(external)
    with pytest.raises(text_upload.TextUploadError) as error:
        text_upload.read_text_attachment(attachment)
    assert error.value.error_code == "text_attachment_unavailable"


def test_interrupted_stream_can_retry_same_identity(stash):
    class BrokenStream(io.BytesIO):
        def read(self, size=-1):
            raise OSError("disconnected")
    upload_id = str(uuid.uuid4())
    with pytest.raises(text_upload.TextUploadError) as error:
        text_upload.save_text_upload(FileStorage(stream=BrokenStream(), filename="note.txt"), upload_id)
    assert error.value.retryable is True
    assert _post(upload_id=upload_id).status_code == 200


def test_browser_page_markdown_filename_is_accepted(stash):
    response = _post(b"# GPU error\nThe worker hit a thermal limit.\n", name="browser-page.md")
    assert response.status_code == 200
    attachment = response.get_json()["attachment"]
    assert attachment["filename"] == "browser-page.md"
    assert attachment["kind"] == "text"
    assert attachment["mime_type"] == "text/markdown"


def test_endpoint_validates_upload_id_and_requested_mode():
    assert _post(upload_id="not-an-id").get_json()["error_code"] == "text_upload_id_invalid"
    assert _post(mode="invalid").status_code == 400


def test_endpoint_uses_requested_config_scope(monkeypatch):
    from config_loader import get_active_config_mode
    modes = []
    save = api.save_text_upload
    def record_mode(*args, **kwargs):
        modes.append(get_active_config_mode())
        return save(*args, **kwargs)
    monkeypatch.setattr(api, "save_text_upload", record_mode)
    assert _post(mode="local").status_code == 200
    assert modes == ["local"]


def test_rate_limit_returns_retry_contract(monkeypatch):
    monkeypatch.setenv("API_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setattr(text_upload, "get_int", lambda name, default: 1)
    assert _post().status_code == 200
    response = _post()
    assert response.status_code == 429
    assert response.get_json()["error_code"] == "text_upload_rate_limited"
    assert response.get_json()["retryable"] is True
    assert int(response.headers["Retry-After"]) >= 1
