"""xAI public retained-video lifecycle regression coverage."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from api.services import xai_video_share
from api.services.xai_video_share import (
    XaiVideoShareConflict,
    XaiVideoShareError,
    XaiVideoShareRegistry,
    XaiVideoShareService,
    get_xai_video_share_status,
)


SHARE_NOW = datetime(2026, 8, 8, tzinfo=timezone.utc)
SHARE_EXPIRES_AT = SHARE_NOW + timedelta(days=7)


@pytest.fixture(autouse=True)
def _freeze_share_clock(monkeypatch):
    monkeypatch.setattr(xai_video_share, "_utc_now", lambda: SHARE_NOW)


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
        return SimpleNamespace(id="file_retained_video")

    def create_public_url(self, file_id):
        self.created.append(file_id)
        return SimpleNamespace(
            public_url="https://files-cdn.x.ai/public/test-video.mp4",
            expires_at=FakeTimestamp(SHARE_EXPIRES_AT),
        )

    def revoke_public_url(self, file_id):
        self.revoked.append(file_id)

    def delete(self, file_id):
        self.deleted.append(file_id)


def _enable_sharing(monkeypatch):
    monkeypatch.setenv("CANVAS_XAI_VIDEO_SHARE", "true")
    monkeypatch.setenv("XAI_API_KEY", "test-key-not-sent")
    monkeypatch.delenv("JARVIS_OVERRIDE_CANVAS_XAI_VIDEO_SHARE", raising=False)
    monkeypatch.delenv("JARVIS_OVERRIDE_XAI_API_KEY", raising=False)


def _service(tmp_path, files):
    return XaiVideoShareService(
        tmp_path,
        client_factory=lambda: SimpleNamespace(files=files),
        registry=XaiVideoShareRegistry(tmp_path / ".shares" / "registry.json"),
        probe_func=lambda _path: {"duration": 8.0, "format": "mov,mp4"},
    )


def test_publish_retained_bytes_catalog_and_revoke(tmp_path, monkeypatch):
    _enable_sharing(monkeypatch)
    video = tmp_path / "gemini-result.mp4"
    video.write_bytes(b"reviewed-local-video")
    files = FakeFilesClient()
    service = _service(tmp_path, files)
    preview = service.inspect_video(video.name)

    record = service.publish(
        filename=video.name,
        ttl_days=7,
        expected_video_sha256=preview["video_sha256"],
        provider="Gemini",
    )

    assert record["status"] == "active"
    assert record["provider"] == "Gemini"
    assert record["expires_at"] == (
        SHARE_EXPIRES_AT.isoformat().replace("+00:00", "Z")
    )
    assert files.upload_calls[0][0] == b"reviewed-local-video"
    assert files.upload_calls[0][1] == "gemini-result.mp4"
    assert files.upload_calls[0][2].days == 7
    assert files.created == ["file_retained_video"]
    assert service.active_for_video(video.name)[0]["share_id"] == record["share_id"]

    revoked = service.revoke(record["share_id"])
    assert revoked["status"] == "revoked"
    assert files.revoked == ["file_retained_video"]
    assert files.deleted == ["file_retained_video"]


def test_publish_rejects_video_changed_after_preview(tmp_path, monkeypatch):
    _enable_sharing(monkeypatch)
    video = tmp_path / "changed.mp4"
    video.write_bytes(b"before")
    files = FakeFilesClient()
    service = _service(tmp_path, files)
    preview = service.inspect_video(video.name)
    video.write_bytes(b"after")

    with pytest.raises(XaiVideoShareConflict, match="changed after preview"):
        service.publish(
            filename=video.name,
            ttl_days=7,
            expected_video_sha256=preview["video_sha256"],
        )

    assert files.upload_calls == []


def test_failed_registry_write_revokes_and_deletes_uploaded_file(tmp_path, monkeypatch):
    _enable_sharing(monkeypatch)
    video = tmp_path / "cleanup.mp4"
    video.write_bytes(b"cleanup-after-registry-failure")
    files = FakeFilesClient()

    class BrokenRegistry(XaiVideoShareRegistry):
        def add(self, _record):
            raise XaiVideoShareError("catalog unavailable")

    service = XaiVideoShareService(
        tmp_path,
        client_factory=lambda: SimpleNamespace(files=files),
        registry=BrokenRegistry(tmp_path / "registry.json"),
        probe_func=lambda _path: {"duration": 5.0, "format": "mov,mp4"},
    )
    preview = service.inspect_video(video.name)

    with pytest.raises(XaiVideoShareError, match="catalog unavailable"):
        service.publish(
            filename=video.name,
            ttl_days=7,
            expected_video_sha256=preview["video_sha256"],
        )

    assert files.revoked == ["file_retained_video"]
    assert files.deleted == ["file_retained_video"]


def test_revoked_file_cleanup_can_be_retried(tmp_path, monkeypatch):
    _enable_sharing(monkeypatch)
    video = tmp_path / "retry.mp4"
    video.write_bytes(b"retry-delete")

    class DeleteFailsOnce(FakeFilesClient):
        def __init__(self):
            super().__init__()
            self.delete_attempts = 0

        def delete(self, file_id):
            self.delete_attempts += 1
            if self.delete_attempts == 1:
                raise RuntimeError("temporary delete failure")
            self.deleted.append(file_id)

    files = DeleteFailsOnce()
    service = _service(tmp_path, files)
    preview = service.inspect_video(video.name)
    record = service.publish(
        filename=video.name,
        ttl_days=7,
        expected_video_sha256=preview["video_sha256"],
    )

    pending = service.revoke(record["share_id"])
    cleaned = service.revoke(record["share_id"])

    assert pending["status"] == "revoked_cleanup_pending"
    assert cleaned["status"] == "revoked"
    assert files.revoked == ["file_retained_video"]
    assert files.delete_attempts == 2
    assert files.deleted == ["file_retained_video"]


def test_status_requires_opt_in_and_api_key(monkeypatch):
    monkeypatch.setenv("CANVAS_XAI_VIDEO_SHARE", "false")
    monkeypatch.setenv("XAI_API_KEY", "present")
    assert not get_xai_video_share_status()["available"]

    monkeypatch.setenv("CANVAS_XAI_VIDEO_SHARE", "true")
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    assert not get_xai_video_share_status()["available"]

    monkeypatch.setenv("XAI_API_KEY", "present")
    status = get_xai_video_share_status()
    assert status["available"]
    assert status["default_ttl_days"] == 7
    assert status["allowed_ttl_days"] == [1, 7, 30]
    assert status["supported_extensions"] == [".mp4"]
