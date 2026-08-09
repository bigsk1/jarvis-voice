"""FastAPI generated-video share and deletion contract tests."""

from __future__ import annotations

import pytest

from api.routes import generated_videos


class FakeShareService:
    def __init__(self, active=None):
        self.active = list(active or [])
        self.revoked = []

    def active_for_video(self, _filename):
        return list(self.active)

    def revoke_all_for_video(self, filename):
        self.revoked.append(filename)
        self.active = []
        return []


def test_local_delete_blocks_when_public_share_is_active(tmp_path, monkeypatch):
    video = tmp_path / "shared.mp4"
    video.write_bytes(b"video")
    service = FakeShareService(
        active=[
            {
                "share_id": "a" * 32,
                "public_url": "https://files-cdn.x.ai/public/shared.mp4",
                "expires_at": "2026-08-15T00:00:00Z",
            }
        ]
    )
    monkeypatch.setattr(generated_videos, "GENERATED_VIDEOS_DIR", tmp_path)
    monkeypatch.setattr(generated_videos, "VIDEO_CATALOG_FILE", tmp_path / "video_catalog.json")
    monkeypatch.setattr(generated_videos, "video_share_service", service)

    with pytest.raises(generated_videos.HTTPException) as caught:
        generated_videos.delete_generated_video(video.name)

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "active_public_video_shares"
    assert video.exists()


def test_confirmed_delete_revokes_remote_before_local_file(tmp_path, monkeypatch):
    video = tmp_path / "shared.mp4"
    video.write_bytes(b"video")
    service = FakeShareService(active=[{"share_id": "b" * 32}])
    monkeypatch.setattr(generated_videos, "GENERATED_VIDEOS_DIR", tmp_path)
    monkeypatch.setattr(generated_videos, "VIDEO_CATALOG_FILE", tmp_path / "video_catalog.json")
    monkeypatch.setattr(generated_videos, "video_share_service", service)

    response = generated_videos.delete_generated_video(video.name, revoke_public_shares=True)

    assert response.ok is True
    assert service.revoked == [video.name]
    assert not video.exists()
