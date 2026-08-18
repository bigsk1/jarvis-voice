"""xAI waveform-MP4 audio share lifecycle regression coverage."""

from __future__ import annotations

import json
import shutil
import subprocess
import wave
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from api.services import xai_audio_share
from api.services.xai_audio_share import (
    XaiAudioShareConflict,
    XaiAudioShareRegistry,
    XaiAudioShareService,
    XaiAudioShareValidationError,
    get_xai_audio_share_status,
)


SHARE_NOW = datetime(2026, 8, 8, tzinfo=timezone.utc)
SHARE_EXPIRES_AT = SHARE_NOW + timedelta(days=7)


@pytest.fixture(autouse=True)
def _freeze_share_clock(monkeypatch):
    monkeypatch.setattr(xai_audio_share, "_utc_now", lambda: SHARE_NOW)


class FakeTimestamp:
    def __init__(self, value: datetime):
        self.value = value

    def ToDatetime(self, tzinfo=None):
        return self.value.astimezone(tzinfo or timezone.utc)


class FakeFilesClient:
    def __init__(self):
        self.upload_calls = []
        self.created = []
        self.revoked = []
        self.deleted = []

    def upload(self, payload, *, filename, expires_after):
        self.upload_calls.append((payload, filename, expires_after))
        return SimpleNamespace(id="file_waveform_audio")

    def create_public_url(self, file_id):
        self.created.append(file_id)
        return SimpleNamespace(
            public_url="https://files-cdn.x.ai/public/test-audio-waveform.mp4",
            expires_at=FakeTimestamp(SHARE_EXPIRES_AT),
        )

    def revoke_public_url(self, file_id):
        self.revoked.append(file_id)

    def delete(self, file_id):
        self.deleted.append(file_id)


def _enable_sharing(monkeypatch):
    monkeypatch.setenv("CANVAS_XAI_AUDIO_SHARE", "true")
    monkeypatch.setenv("XAI_API_KEY", "test-key-not-sent")
    monkeypatch.delenv(
        "JARVIS_OVERRIDE_CANVAS_XAI_AUDIO_SHARE",
        raising=False,
    )
    monkeypatch.delenv("JARVIS_OVERRIDE_XAI_API_KEY", raising=False)


def _fake_convert(_source, target, duration):
    target.write_bytes(b"waveform-mp4-with-complete-audio")
    return {"duration": duration, "format": "mp4"}


def _service(tmp_path, files):
    return XaiAudioShareService(
        tmp_path,
        client_factory=lambda: SimpleNamespace(files=files),
        registry=XaiAudioShareRegistry(
            tmp_path / ".shares" / "registry.json"
        ),
        probe_func=lambda _path: {
            "duration": 30.0,
            "format": "mp3",
            "codec": "mp3",
        },
        convert_func=_fake_convert,
    )


def test_publish_converted_mp4_catalog_and_revoke(tmp_path, monkeypatch):
    _enable_sharing(monkeypatch)
    audio = tmp_path / "gemini-result.mp3"
    audio.write_bytes(b"reviewed-local-audio")
    files = FakeFilesClient()
    service = _service(tmp_path, files)
    preview = service.inspect_audio(audio.name)

    record = service.publish(
        filename=audio.name,
        ttl_days=7,
        expected_audio_sha256=preview["audio_sha256"],
        provider="Google Gemini",
    )

    assert record["status"] == "active"
    assert record["provider"] == "Google Gemini"
    assert record["public_format"] == "video/mp4"
    assert record["expires_at"] == (
        SHARE_EXPIRES_AT.isoformat().replace("+00:00", "Z")
    )
    assert files.upload_calls[0][0] == b"waveform-mp4-with-complete-audio"
    assert files.upload_calls[0][1] == "gemini-result-waveform.mp4"
    assert files.upload_calls[0][2].days == 7
    assert files.created == ["file_waveform_audio"]
    assert service.active_for_audio(audio.name)[0]["share_id"] == record["share_id"]
    assert audio.read_bytes() == b"reviewed-local-audio"

    revoked = service.revoke(record["share_id"])
    assert revoked["status"] == "revoked"
    assert files.revoked == ["file_waveform_audio"]
    assert files.deleted == ["file_waveform_audio"]


def test_publish_rejects_audio_changed_after_preview(tmp_path, monkeypatch):
    _enable_sharing(monkeypatch)
    audio = tmp_path / "changed.mp3"
    audio.write_bytes(b"before")
    files = FakeFilesClient()
    service = _service(tmp_path, files)
    preview = service.inspect_audio(audio.name)
    audio.write_bytes(b"after")

    with pytest.raises(XaiAudioShareConflict, match="changed after preview"):
        service.publish(
            filename=audio.name,
            ttl_days=7,
            expected_audio_sha256=preview["audio_sha256"],
        )

    assert files.upload_calls == []


def test_publish_enforces_converted_mp4_limit(tmp_path, monkeypatch):
    _enable_sharing(monkeypatch)
    monkeypatch.setenv("CANVAS_XAI_AUDIO_SHARE_MAX_BYTES", "8")
    audio = tmp_path / "too-large-after-conversion.mp3"
    audio.write_bytes(b"small-source")
    files = FakeFilesClient()
    service = _service(tmp_path, files)
    preview = service.inspect_audio(audio.name)

    with pytest.raises(
        XaiAudioShareValidationError,
        match="waveform MP4 exceeds",
    ):
        service.publish(
            filename=audio.name,
            ttl_days=7,
            expected_audio_sha256=preview["audio_sha256"],
        )

    assert files.upload_calls == []


def test_status_requires_opt_in_and_api_key(monkeypatch):
    monkeypatch.setenv("CANVAS_XAI_AUDIO_SHARE", "false")
    monkeypatch.setenv("XAI_API_KEY", "present")
    assert not get_xai_audio_share_status()["available"]

    monkeypatch.setenv("CANVAS_XAI_AUDIO_SHARE", "true")
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    assert not get_xai_audio_share_status()["available"]

    monkeypatch.setenv("XAI_API_KEY", "present")
    status = get_xai_audio_share_status()
    assert status["available"]
    assert status["default_ttl_days"] == 7
    assert status["allowed_ttl_days"] == [1, 7, 30]
    assert status["public_format"] == "video/mp4"
    assert ".mp3" in status["supported_extensions"]


def test_video_bitrate_uses_duration_and_size_budget(monkeypatch):
    monkeypatch.setenv("CANVAS_XAI_AUDIO_SHARE_MAX_BYTES", "48000000")

    short_track = XaiAudioShareService._video_bitrate_kbps(30)
    current_long_track = XaiAudioShareService._video_bitrate_kbps(180)
    maximum_generated_track = XaiAudioShareService._video_bitrate_kbps(600)

    assert short_track == 1_800
    assert 1_600 <= current_long_track < short_track
    assert 400 <= maximum_generated_track <= 450

    projected_bytes = (
        (maximum_generated_track + 128) * 1_000 * 600 / 8
    )
    assert projected_bytes < 48_000_000


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg and ffprobe are required",
)
def test_real_conversion_embeds_complete_audio_and_video(tmp_path):
    source = tmp_path / "tone.wav"
    target = tmp_path / "tone-waveform.mp4"
    sample_rate = 8_000
    duration = 0.5
    with wave.open(str(source), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(b"\x00\x00" * int(sample_rate * duration))

    XaiAudioShareService._convert_to_public_mp4(source, target, duration)
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height",
            "-of",
            "json",
            str(target),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    stream_types = {stream["codec_type"] for stream in payload["streams"]}
    video_stream = next(
        stream
        for stream in payload["streams"]
        if stream["codec_type"] == "video"
    )

    assert stream_types == {"audio", "video"}
    assert (video_stream["width"], video_stream["height"]) == (854, 480)
    assert float(payload["format"]["duration"]) >= 0.49
    assert target.stat().st_size > 0
