"""FastAPI generated-audio share and deletion contract tests."""

from __future__ import annotations

import json

import pytest

from api.routes import generated_music


class FakeShareService:
    def __init__(self, active=None):
        self.active = list(active or [])
        self.revoked = []

    def active_for_audio(self, _filename):
        return list(self.active)

    def revoke_all_for_audio(self, filename):
        self.revoked.append(filename)
        self.active = []
        return []


def _setup_audio(tmp_path, monkeypatch, service):
    audio = tmp_path / "shared.mp3"
    audio.write_bytes(b"audio")
    catalog_file = tmp_path / "audio_catalog.json"
    catalog_file.write_text(
        json.dumps({audio.name: {"title": "Shared"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(generated_music, "GENERATED_MUSIC_DIR", tmp_path)
    monkeypatch.setattr(generated_music, "AUDIO_CATALOG_FILE", catalog_file)
    monkeypatch.setattr(generated_music, "audio_share_service", service)
    return audio, catalog_file


def test_local_delete_blocks_when_public_audio_share_is_active(
    tmp_path,
    monkeypatch,
):
    service = FakeShareService(
        active=[
            {
                "share_id": "a" * 32,
                "public_url": "https://files-cdn.x.ai/public/shared.mp4",
                "expires_at": "2026-08-15T00:00:00Z",
            }
        ]
    )
    audio, _catalog = _setup_audio(tmp_path, monkeypatch, service)

    with pytest.raises(generated_music.HTTPException) as caught:
        generated_music.delete_generated_music(audio.name)

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "active_public_audio_shares"
    assert audio.exists()


def test_confirmed_delete_revokes_remote_before_local_audio(
    tmp_path,
    monkeypatch,
):
    service = FakeShareService(active=[{"share_id": "b" * 32}])
    audio, catalog_file = _setup_audio(tmp_path, monkeypatch, service)

    response = generated_music.delete_generated_music(
        audio.name,
        revoke_public_shares=True,
    )

    assert response == {"ok": True, "deleted": audio.name}
    assert service.revoked == [audio.name]
    assert not audio.exists()
    assert audio.name not in json.loads(catalog_file.read_text(encoding="utf-8"))
