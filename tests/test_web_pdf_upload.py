"""Regression coverage for the Jarvis Web PDF-to-Stash boundary."""

from __future__ import annotations

import hashlib
import io
import json
import sys
import uuid
from pathlib import Path

import fitz
import pytest
from flask import Flask
from werkzeug.datastructures import FileStorage

from server_package_utils import load_server_package


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))
load_server_package("jarvis_web_pdf_test", PROJECT_ROOT / "jarvis-web" / "server")

from jarvis_web_pdf_test.routes import api  # noqa: E402
from jarvis_web_pdf_test.services import pdf_upload  # noqa: E402


def _pdf_bytes(text: str = "Jarvis PDF attachment test") -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    payload = document.tobytes()
    document.close()
    return payload


def _encrypted_pdf_bytes() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "encrypted")
    payload = document.tobytes(
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner-password",
        user_pw="user-password",
    )
    document.close()
    return payload


def _client():
    app = Flask(__name__)
    app.register_blueprint(api.api_bp)
    return app.test_client()


@pytest.fixture(autouse=True)
def _isolated_stash(tmp_path, monkeypatch):
    stash_dir = tmp_path / "stash"
    uploads_dir = tmp_path / "uploads"
    monkeypatch.delenv("JARVIS_OVERRIDE_STASH_DIR", raising=False)
    monkeypatch.setenv("STASH_DIR", str(stash_dir))
    monkeypatch.setenv("WEB_PDF_UPLOAD_RATE_LIMIT_PER_MINUTE", "0")
    monkeypatch.setattr(api, "UPLOADS_PATH", uploads_dir)
    pdf_upload.reset_pdf_upload_rate_limit_for_tests()
    yield stash_dir, uploads_dir
    pdf_upload.reset_pdf_upload_rate_limit_for_tests()


def _post_pdf(client, payload: bytes, upload_id: str, filename: str = "sample.pdf"):
    return client.post(
        "/api/upload-pdf",
        data={
            "file": (io.BytesIO(payload), filename, "application/pdf"),
            "upload_id": upload_id,
        },
        content_type="multipart/form-data",
    )


def test_upload_pdf_commits_complete_stash_metadata_only(_isolated_stash):
    stash_dir, uploads_dir = _isolated_stash
    payload = _pdf_bytes()
    upload_id = str(uuid.uuid4())

    response = _post_pdf(_client(), payload, upload_id, "docker-cheatsheet.pdf")
    body = response.get_json()

    assert response.status_code == 200
    assert body["ok"] is True
    assert body["idempotent_replay"] is False
    attachment = body["attachment"]
    assert attachment == {
        "kind": "pdf",
        "stash_ref": (
            f"stash://space_web_pdf_{uuid.UUID(upload_id).hex}/"
            f"f_{hashlib.sha256(payload).hexdigest()[:12]}"
        ),
        "space_id": f"space_web_pdf_{uuid.UUID(upload_id).hex}",
        "file_id": f"f_{hashlib.sha256(payload).hexdigest()[:12]}",
        "filename": "docker-cheatsheet.pdf",
        "size_bytes": len(payload),
        "mime_type": "application/pdf",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "page_count": 1,
        "upload_id": upload_id,
    }

    space_path = stash_dir / attachment["space_id"]
    meta = json.loads((space_path / "meta.json").read_text())
    assert meta["source"] == "web_pdf_upload"
    assert meta["labels"] == ["web_upload", "pdf"]
    assert meta["scope"] == "session"
    assert meta["retention_policy"] == "source_artifact"
    assert meta["ttl_days"] == 120
    assert meta["upload_id"] == upload_id
    assert meta["files"][0]["tool_origin"] == "web_pdf_upload"
    assert meta["files"][0]["mime_type"] == "application/pdf"
    assert meta["files"][0]["page_count"] == 1
    assert (space_path / "docker-cheatsheet.pdf").read_bytes() == payload
    assert not uploads_dir.exists()


def test_retry_with_same_upload_id_returns_same_artifact(_isolated_stash):
    stash_dir, _uploads_dir = _isolated_stash
    payload = _pdf_bytes("same upload")
    upload_id = str(uuid.uuid4())
    client = _client()

    first = _post_pdf(client, payload, upload_id).get_json()
    second_response = _post_pdf(client, payload, upload_id)
    second = second_response.get_json()

    assert second_response.status_code == 200
    assert second["idempotent_replay"] is True
    assert second["attachment"] == first["attachment"]
    assert len(list(stash_dir.glob("space_web_pdf_*"))) == 1
    assert not list((stash_dir / ".incoming").iterdir())


def test_reused_upload_id_with_different_pdf_is_rejected(_isolated_stash):
    upload_id = str(uuid.uuid4())
    client = _client()
    assert _post_pdf(client, _pdf_bytes("first"), upload_id).status_code == 200

    response = _post_pdf(client, _pdf_bytes("different"), upload_id)

    assert response.status_code == 409
    assert response.get_json()["error_code"] == "pdf_upload_id_conflict"


@pytest.mark.parametrize(
    ("filename", "mime_type", "payload", "error_code"),
    [
        ("sample.txt", "application/pdf", b"%PDF-not-really", "pdf_upload_extension_invalid"),
        ("sample.pdf", "text/plain", b"%PDF-not-really", "pdf_upload_mime_invalid"),
        ("sample.pdf", "application/pdf", b"not a pdf", "pdf_upload_header_invalid"),
        ("sample.pdf", "application/pdf", b"%PDF-1.7\nbroken", "pdf_upload_invalid"),
    ],
)
def test_invalid_upload_never_exposes_partial_stash_space(
    _isolated_stash,
    filename,
    mime_type,
    payload,
    error_code,
):
    stash_dir, _uploads_dir = _isolated_stash
    response = _client().post(
        "/api/upload-pdf",
        data={
            "file": (io.BytesIO(payload), filename, mime_type),
            "upload_id": str(uuid.uuid4()),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code in {400, 422}
    assert response.get_json()["error_code"] == error_code
    assert not list(stash_dir.glob("space_web_pdf_*"))
    incoming = stash_dir / ".incoming"
    assert not incoming.exists() or not list(incoming.iterdir())


def test_stream_failure_is_retryable_and_cleans_staging(_isolated_stash):
    stash_dir, _uploads_dir = _isolated_stash

    class BrokenStream(io.BytesIO):
        def __init__(self):
            super().__init__(_pdf_bytes())
            self.calls = 0

        def read(self, size=-1):
            self.calls += 1
            if self.calls > 1:
                raise OSError("simulated disconnect")
            return super().read(64)

    upload = FileStorage(
        stream=BrokenStream(),
        filename="interrupted.pdf",
        content_type="application/pdf",
    )
    with pytest.raises(pdf_upload.PDFUploadError) as raised:
        pdf_upload.save_pdf_upload(upload, str(uuid.uuid4()))

    assert raised.value.error_code == "pdf_upload_interrupted"
    assert raised.value.retryable is True
    assert not list(stash_dir.glob("space_web_pdf_*"))
    assert not list((stash_dir / ".incoming").iterdir())


def test_password_protected_pdf_is_rejected_before_commit(_isolated_stash):
    stash_dir, _uploads_dir = _isolated_stash
    response = _post_pdf(
        _client(),
        _encrypted_pdf_bytes(),
        str(uuid.uuid4()),
        "encrypted.pdf",
    )

    assert response.status_code == 422
    assert response.get_json()["error_code"] == "pdf_upload_encrypted"
    assert not list(stash_dir.glob("space_web_pdf_*"))
    assert not list((stash_dir / ".incoming").iterdir())


def test_hard_stream_limit_cleans_staging(_isolated_stash):
    stash_dir, _uploads_dir = _isolated_stash
    upload = FileStorage(
        stream=io.BytesIO(_pdf_bytes()),
        filename="too-large.pdf",
        content_type="application/pdf",
    )
    with pytest.raises(pdf_upload.PDFUploadError) as raised:
        pdf_upload.save_pdf_upload(upload, str(uuid.uuid4()), max_bytes=64)

    assert raised.value.status_code == 413
    assert raised.value.error_code == "pdf_upload_too_large"
    assert not list(stash_dir.glob("space_web_pdf_*"))
    assert not list((stash_dir / ".incoming").iterdir())


def test_attachment_validation_rebuilds_metadata_and_rejects_tampering(_isolated_stash):
    payload = _pdf_bytes()
    upload_id = str(uuid.uuid4())
    attachment = _post_pdf(_client(), payload, upload_id).get_json()["attachment"]

    tampered_display_fields = {
        **attachment,
        "filename": "pretend.pdf",
        "size_bytes": 1,
        "mime_type": "text/plain",
        "sha256": "fake",
        "page_count": 99,
    }
    assert pdf_upload.validate_pdf_attachment(tampered_display_fields) == attachment

    bad_ref = {
        **attachment,
        "stash_ref": attachment["stash_ref"].replace("f_", "f_deadbeefdead", 1),
    }
    with pytest.raises(pdf_upload.PDFUploadError) as raised:
        pdf_upload.validate_pdf_attachment(bad_ref)
    assert raised.value.error_code == "pdf_attachment_invalid"


def test_pdf_upload_rate_limit_is_separate_and_typed(_isolated_stash, monkeypatch):
    monkeypatch.setenv("WEB_PDF_UPLOAD_RATE_LIMIT_PER_MINUTE", "1")
    pdf_upload.reset_pdf_upload_rate_limit_for_tests()
    client = _client()
    remote = {"REMOTE_ADDR": "203.0.113.9"}

    first = client.post(
        "/api/upload-pdf",
        data={
            "file": (io.BytesIO(_pdf_bytes()), "first.pdf", "application/pdf"),
            "upload_id": str(uuid.uuid4()),
        },
        content_type="multipart/form-data",
        environ_overrides=remote,
    )
    second = client.post(
        "/api/upload-pdf",
        data={
            "file": (io.BytesIO(_pdf_bytes()), "second.pdf", "application/pdf"),
            "upload_id": str(uuid.uuid4()),
        },
        content_type="multipart/form-data",
        environ_overrides=remote,
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.get_json()["error_code"] == "pdf_upload_rate_limited"
    assert int(second.headers["Retry-After"]) >= 1
