"""Exercise video intake with real ffmpeg media and disposable Stash storage."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from flask import Flask
from server_package_utils import load_server_package
from werkzeug.datastructures import FileStorage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
load_server_package("jarvis_web_video_test", ROOT / "jarvis-web/server")
from jarvis_web_video_test.routes import api  # noqa: E402
from jarvis_web_video_test.services import audio_upload, video_upload  # noqa: E402


@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    root = tmp_path_factory.mktemp("video-source-clips")
    results = {}
    for name, video, audio, extension in (
        ("silent", True, False, "mp4"),
        ("sound", True, True, "mp4"),
        ("audio_mp4", False, True, "mp4"),
        ("audio_webm", False, True, "webm"),
        ("audio_mpeg", False, True, "mpeg"),
    ):
        path = root / f"{name}.{extension}"
        command = ["ffmpeg", "-nostdin", "-v", "error"]
        if video:
            command += ["-f", "lavfi", "-i", "color=c=red:s=160x90:r=5:d=1"]
        if audio:
            command += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1"]
        if video:
            command += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-threads", "1"]
        if audio:
            codec = {"webm": "libopus", "mpeg": "libmp3lame"}.get(extension, "aac")
            command += ["-c:a", codec]
        if extension == "mpeg":
            command += ["-f", "mp3"]
        subprocess.run(command + ["-t", "1", str(path)], check=True, timeout=30, capture_output=True)
        results[name] = path.read_bytes()
    return results


@pytest.fixture(autouse=True)
def stash(tmp_path, monkeypatch):
    root = tmp_path / "stash"
    monkeypatch.delenv("JARVIS_OVERRIDE_STASH_DIR", raising=False)
    monkeypatch.setenv("STASH_DIR", str(root))
    monkeypatch.setenv("WEB_VIDEO_UPLOAD_RATE_LIMIT_PER_MINUTE", "0")
    video_upload.reset_video_upload_rate_limit_for_tests()
    yield root
    video_upload.reset_video_upload_rate_limit_for_tests()


def client():
    app = Flask(__name__)
    app.register_blueprint(api.api_bp)
    return app.test_client()


def post(payload, *, upload_id=None, filename="screen recording.mp4", mime="video/mp4", mode="cloud"):
    return client().post("/api/upload-video", data={
        "file": (io.BytesIO(payload), filename, mime),
        "upload_id": upload_id or str(uuid.uuid4()), "mode": mode,
    }, content_type="multipart/form-data")


@pytest.mark.parametrize("name", ["silent", "sound"])
def test_real_video_commits_source_metadata_and_range_playback(clips, stash, name):
    payload = clips[name]
    result = post(payload)
    assert result.status_code == 200, result.get_json()
    body = result.get_json()
    attachment = body["attachment"]
    assert body["idempotent_replay"] is False
    assert attachment["kind"] == "video"
    assert attachment["has_audio"] is (name == "sound")
    assert (attachment["width"], attachment["height"]) == (160, 90)
    assert attachment["duration_seconds"] == pytest.approx(1, abs=0.1)
    assert attachment["sha256"] == hashlib.sha256(payload).hexdigest()
    assert attachment["mime_type"] == "video/mp4"
    space = stash / attachment["space_id"]
    metadata = json.loads((space / "meta.json").read_text())
    assert metadata["source"] == "web_video_upload"
    assert metadata["labels"] == ["web_upload", "video"]
    assert (space / attachment["filename"]).read_bytes() == payload
    playback = client().get(attachment["stash_ref"].replace("stash://", "/api/stash/"),
                            headers={"Range": "bytes=0-31"})
    assert playback.status_code == 206
    assert playback.data == payload[:32]


@pytest.mark.parametrize("extension", ["mp4", "webm"])
def test_audio_only_video_containers_preserve_audio_contract(clips, extension):
    result = post(clips[f"audio_{extension}"], filename=f"recording.{extension}",
                  mime=f"video/{extension}")
    assert result.status_code == 200, result.get_json()
    attachment = result.get_json()["attachment"]
    assert attachment["kind"] == "audio"
    assert attachment["space_id"].startswith("space_web_audio_")
    assert attachment["mime_type"] == f"audio/{extension}"
    assert audio_upload.validate_audio_attachment(attachment) == attachment


@pytest.mark.parametrize("mime", ["", "video/mpeg"])
def test_mp3_bitstream_with_legacy_mpeg_extension_remains_audio(clips, stash, mime):
    from video_analysis import NoVideoStreamError, analyze_video_file

    boundary = uuid.uuid4().hex
    header = f"Content-Type: {mime}\r\n" if mime else ""
    payload = clips["audio_mpeg"]
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="voice.mpeg"\r\n'
        f'{header}\r\n'
    ).encode() + payload + (
        f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="upload_id"\r\n\r\n'
        f'{uuid.uuid4()}\r\n--{boundary}--\r\n'
    ).encode()
    response = client().post(
        "/api/upload-video", data=body, content_type=f"multipart/form-data; boundary={boundary}"
    )
    assert response.status_code == 200, response.get_json()
    attachment = response.get_json()["attachment"]
    assert attachment["kind"] == "audio"
    assert attachment["mime_type"] == "audio/mpeg"
    assert audio_upload.validate_audio_attachment(attachment) == attachment
    space = stash / attachment["space_id"]
    assert json.loads((space / "meta.json").read_text())["source"] == "web_audio_upload"
    source = space / attachment["filename"]
    assert source.read_bytes() == payload
    with pytest.raises(NoVideoStreamError, match="does not contain a video stream"):
        analyze_video_file(source, question="Describe this clip.")


def test_idempotency_rejects_different_bytes_or_different_media_kind(clips):
    upload_id = str(uuid.uuid4())
    first = post(clips["silent"], upload_id=upload_id).get_json()
    second = post(clips["silent"], upload_id=upload_id).get_json()
    assert second["idempotent_replay"] is True
    assert first["attachment"] == second["attachment"]
    for payload in (clips["sound"], clips["audio_mp4"]):
        conflict = post(payload, upload_id=upload_id)
        assert conflict.status_code == 409
        assert conflict.get_json()["error_code"].endswith("upload_id_conflict")


def test_attachment_validation_uses_server_metadata_and_detects_equal_size_corruption(clips, stash):
    attachment = post(clips["silent"]).get_json()["attachment"]
    forged = {**attachment, "filename": "forged.mp4", "has_audio": True, "width": 9999}
    assert video_upload.validate_video_attachment(forged) == attachment
    source = stash / attachment["space_id"] / attachment["filename"]
    original = source.read_bytes()
    source.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    with pytest.raises(video_upload.VideoUploadError, match="unavailable"):
        video_upload.validate_video_attachment(attachment)


def test_malformed_stored_upload_id_returns_video_attachment_error(clips, stash):
    attachment = post(clips["silent"]).get_json()["attachment"]
    metadata_path = stash / attachment["space_id"] / "meta.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["upload_id"] = "corrupted"
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises(video_upload.VideoUploadError) as error:
        video_upload.validate_video_attachment(attachment)
    assert error.value.status_code == 409
    assert error.value.error_code == "video_attachment_unavailable"


@pytest.mark.parametrize("target", ["source", "metadata", "space"])
def test_attachment_rejects_symlink_substitution(clips, stash, tmp_path, target):
    attachment = post(clips["silent"]).get_json()["attachment"]
    space = stash / attachment["space_id"]
    path = space if target == "space" else space / ("meta.json" if target == "metadata" else attachment["filename"])
    moved = tmp_path / f"outside-{target}"
    path.rename(moved)
    path.symlink_to(moved, target_is_directory=target == "space")
    with pytest.raises(video_upload.VideoUploadError, match="unavailable"):
        video_upload.validate_video_attachment(attachment)


@pytest.mark.parametrize("filename,mime,payload,code", [
    ("bad.txt", "video/mp4", b"bad", "extension_invalid"),
    ("bad.mp4", "text/plain", b"bad", "mime_invalid"),
    ("bad.mp4", "video/mp4", b"bad", "invalid"),
    ("empty.mp4", "video/mp4", b"", "empty"),
])
def test_rejected_upload_never_commits_or_leaves_staged_media(stash, filename, mime, payload, code):
    result = post(payload, filename=filename, mime=mime)
    assert result.status_code in (400, 422)
    assert result.get_json()["error_code"] == f"video_upload_{code}"
    assert not list(stash.glob("space_*"))
    assert not list((stash / ".incoming").glob("space_*"))


def test_stream_limit_and_interruption_leave_no_committed_media(clips, stash):
    with pytest.raises(video_upload.VideoUploadError) as too_large:
        video_upload.save_video_upload(
            FileStorage(io.BytesIO(clips["silent"]), filename="clip.mp4", content_type="video/mp4"),
            str(uuid.uuid4()), max_bytes=16,
        )
    assert too_large.value.status_code == 413

    class Interrupted:
        def read(self, size):
            raise OSError("connection lost")

    with pytest.raises(video_upload.VideoUploadError) as interrupted:
        video_upload.save_video_upload(
            FileStorage(Interrupted(), filename="clip.mp4", content_type="video/mp4"), str(uuid.uuid4())
        )
    assert interrupted.value.retryable
    assert not list(stash.glob("space_*"))
    assert not list((stash / ".incoming").glob("space_*"))


def test_concurrent_retries_commit_once(clips):
    upload_id = str(uuid.uuid4())
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: post(clips["silent"], upload_id=upload_id).get_json(), range(2)))
    assert sorted(result["idempotent_replay"] for result in results) == [False, True]
    assert results[0]["attachment"] == results[1]["attachment"]


def test_processes_cannot_reuse_one_upload_id_for_audio_and_video(clips, stash, tmp_path):
    paths = [tmp_path / "video.mp4", tmp_path / "audio.mp4"]
    for path, payload in zip(paths, (clips["silent"], clips["audio_mp4"])):
        path.write_bytes(payload)
    script = r'''
import json
import sys
from pathlib import Path
from werkzeug.datastructures import FileStorage
root, source, upload_id, stash = sys.argv[1:]
sys.path[:0] = [str(Path(root) / 'lib'), str(Path(root) / 'tests')]
import os
os.environ['STASH_DIR'] = stash
os.environ.pop('JARVIS_OVERRIDE_STASH_DIR', None)
from server_package_utils import load_server_package
load_server_package('video_race_child', Path(root) / 'jarvis-web/server')
from video_race_child.services.video_upload import VideoUploadError, save_video_upload
try:
    with open(source, 'rb') as stream:
        attachment, replay = save_video_upload(
            FileStorage(stream, filename=Path(source).name, content_type='video/mp4'), upload_id)
    print(json.dumps({'status': 200, 'kind': attachment['kind'], 'replay': replay}))
except VideoUploadError as error:
    print(json.dumps({'status': error.status_code, 'code': error.error_code}))
'''
    upload_id = str(uuid.uuid4())

    def invoke(path):
        completed = subprocess.run(
            [sys.executable, "-c", script, str(ROOT), str(path), upload_id, str(stash)],
            capture_output=True, text=True, check=True, timeout=30,
        )
        return json.loads(completed.stdout)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(invoke, paths))
    assert sorted(result["status"] for result in results) == [200, 409]
    assert len(list(stash.glob("space_*"))) == 1
    assert not list((stash / ".incoming").glob("space_*"))


def test_duration_limit_and_missing_or_invalid_upload_id_do_not_commit(clips, stash):
    with pytest.raises(video_upload.VideoUploadError, match="duration"):
        video_upload.save_video_upload(
            FileStorage(io.BytesIO(clips["silent"]), filename="clip.mp4", content_type="video/mp4"),
            str(uuid.uuid4()), max_duration_seconds=0,
        )
    missing = client().post("/api/upload-video", data={"upload_id": str(uuid.uuid4())})
    assert missing.status_code == 400
    assert missing.get_json()["error_code"] == "video_upload_missing"
    invalid = post(clips["silent"], upload_id="invalid")
    assert invalid.status_code == 400
    assert invalid.get_json()["error_code"] == "video_upload_id_invalid"
    assert not list(stash.glob("space_*"))


def test_invalid_mode_and_limits_are_reported_without_artifacts(clips, stash, monkeypatch):
    assert post(clips["silent"], mode="invalid").status_code == 400
    monkeypatch.setattr(api, "get_video_upload_limits", lambda: (_ for _ in ()).throw(ValueError()))
    invalid = post(clips["silent"])
    assert invalid.status_code == 500
    assert invalid.get_json()["error_code"] == "video_upload_configuration_invalid"
    assert not list(stash.glob("space_*"))


def test_rate_limit_sets_retry_after(clips, monkeypatch):
    monkeypatch.setattr(api, "check_video_upload_rate", lambda ip: (False, 12))
    response = post(clips["silent"])
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "12"


def test_upload_uses_selected_mode_limits(clips, monkeypatch):
    from config_loader import get_active_config_mode
    real_loader = video_upload.load_video_analysis_limits
    observed = []

    def limits():
        observed.append(get_active_config_mode())
        return replace(real_loader(), max_duration_seconds=1)

    monkeypatch.setattr(video_upload, "load_video_analysis_limits", limits)
    assert post(clips["silent"], mode="local").status_code == 200
    assert observed and set(observed) == {"local"}


def test_real_app_auth_guards_upload_before_storage(clips, monkeypatch, stash):
    from jarvis_web_video_test import app as app_module
    monkeypatch.setattr(app_module, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(app_module, "verify_token", lambda token: False)
    with app_module.app.test_client() as browser:
        response = browser.post("/api/upload-video", data={
            "file": (io.BytesIO(clips["silent"]), "clip.mp4", "video/mp4"),
            "upload_id": str(uuid.uuid4()),
        })
    assert response.status_code == 401
    assert not list(stash.glob("space_*"))
