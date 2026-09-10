"""Document HTTP uploads and socket validation share the requested Stash scope."""

from __future__ import annotations

import io
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fitz
import pytest
from flask import Flask
from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def scoped_uploads(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "lib"))
    import config_loader

    roots = {mode: tmp_path / mode for mode in ("cloud", "local")}
    startup_root = tmp_path / "startup-stash"
    monkeypatch.delenv("JARVIS_OVERRIDE_STASH_DIR", raising=False)
    monkeypatch.setenv("STASH_DIR", str(startup_root))
    monkeypatch.setattr(
        config_loader,
        "_load_mode_config",
        lambda mode: {
            "STASH_DIR": str(roots[mode]),
            "WEB_PDF_UPLOAD_RATE_LIMIT_PER_MINUTE": "0",
            "WEB_AUDIO_UPLOAD_RATE_LIMIT_PER_MINUTE": "0",
            "WEB_TEXT_UPLOAD_RATE_LIMIT_PER_MINUTE": "0",
        },
    )
    load_server_package("jarvis_attachment_modes_test", ROOT / "jarvis-web/server")
    from jarvis_attachment_modes_test import config as web_config
    from jarvis_attachment_modes_test.routes import api
    from jarvis_attachment_modes_test.services import attachment_bundle

    monkeypatch.setattr(web_config, "load_web_config", lambda: {})
    app = Flask(__name__)
    app.register_blueprint(api.api_bp)

    def post(kind, mode, payload, upload_id):
        extension, mime = {
            "pdf": ("pdf", "application/pdf"),
            "audio": ("wav", "audio/wav"),
            "text": ("txt", "text/plain"),
        }[kind]
        with app.test_client() as client:
            return client.post(
                f"/api/upload-{kind}",
                data={
                    "mode": mode,
                    "upload_id": upload_id,
                    "file": (io.BytesIO(payload), f"source.{extension}", mime),
                },
                content_type="multipart/form-data",
            )

    return roots, startup_root, post, config_loader, attachment_bundle


def _payload(kind):
    if kind == "text":
        return b"Reference note for the requested mode."
    if kind == "pdf":
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((72, 72), "Reference PDF for the requested mode.")
            return document.tobytes()
    output = io.BytesIO()
    with wave.open(output, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(16000)
        recording.writeframes(b"\0\0" * 1600)
    return output.getvalue()


@pytest.mark.parametrize("kind", ["pdf", "audio", "text"])
@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_requested_mode_owns_upload_validation_and_retry(scoped_uploads, kind, mode):
    roots, startup_root, post, config_loader, bundle = scoped_uploads
    other_mode = "cloud" if mode == "local" else "local"
    payload = _payload(kind)
    upload_id = str(uuid.uuid4())
    response = post(kind, mode, payload, upload_id)
    assert response.status_code == 200, response.get_json()
    attachment = response.get_json()["attachment"]
    committed = roots[mode] / attachment["space_id"] / attachment["filename"]
    assert committed.read_bytes() == payload
    assert not startup_root.exists()
    assert not (roots[other_mode] / attachment["space_id"]).exists()

    with config_loader.config_scope(mode):
        assert bundle.validate_attachments([attachment], mode) == [attachment]
    with config_loader.config_scope(other_mode):
        with pytest.raises(bundle.AttachmentBundleError):
            bundle.validate_attachments([attachment], other_mode)
    replay = post(kind, mode, payload, upload_id)
    assert replay.status_code == 200
    assert replay.get_json()["idempotent_replay"] is True
    assert replay.get_json()["attachment"] == attachment


@pytest.mark.parametrize("kind", ["pdf", "audio", "text"])
def test_invalid_mode_never_creates_an_upload(scoped_uploads, kind):
    roots, startup_root, post, _config_loader, _bundle = scoped_uploads
    response = post(kind, "unsupported", _payload(kind), str(uuid.uuid4()))
    assert response.status_code == 400
    assert not startup_root.exists()
    assert not any(root.exists() for root in roots.values())


def test_concurrent_mode_uploads_do_not_share_idempotency_state(scoped_uploads):
    roots, startup_root, post, _config_loader, _bundle = scoped_uploads
    upload_id = str(uuid.uuid4())
    payloads = {mode: f"This note belongs to {mode}.".encode() for mode in roots}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {
            mode: pool.submit(post, "text", mode, payload, upload_id)
            for mode, payload in payloads.items()
        }
        responses = {mode: future.result(timeout=10) for mode, future in futures.items()}
    for mode, response in responses.items():
        assert response.status_code == 200, response.get_json()
        assert response.get_json()["idempotent_replay"] is False
        attachment = response.get_json()["attachment"]
        assert (
            roots[mode] / attachment["space_id"] / attachment["filename"]
        ).read_bytes() == payloads[mode]
    assert not startup_root.exists()


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_source_download_and_audio_range_use_explicit_original_mode(scoped_uploads, mode):
    roots, _startup_root, post, _config_loader, _bundle = scoped_uploads
    from jarvis_attachment_modes_test.routes import api

    payload = _payload('audio')
    attachment = post('audio', mode, payload, str(uuid.uuid4())).get_json()['attachment']
    app = Flask(__name__)
    app.register_blueprint(api.api_bp)
    url = f"/api/stash/{attachment['space_id']}/{attachment['file_id']}"
    with app.test_client() as client:
        response = client.get(f'{url}?mode={mode}')
        assert response.status_code == 200
        assert response.data == payload
        partial = client.get(f'{url}?mode={mode}', headers={'Range': 'bytes=0-15'})
        assert partial.status_code == 206
        assert partial.data == payload[:16]
        other = 'cloud' if mode == 'local' else 'local'
        assert client.get(f'{url}?mode={other}').status_code == 404
        assert client.get(f'{url}?mode=unsupported').status_code == 400
        # The no-mode URL still uses the old process-default root.
        assert client.get(url).status_code == 404
    assert (roots[mode] / attachment['space_id']).exists()
