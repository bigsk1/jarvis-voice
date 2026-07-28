"""Regression coverage for the Canvas Audio Gallery."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from flask import Flask


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANVAS_ROOT = PROJECT_ROOT / "jarvis-canvas"
LIB_ROOT = PROJECT_ROOT / "lib"
AUDIO_HTML = (CANVAS_ROOT / "client" / "templates" / "audio-gallery.html").read_text()
AUDIO_JS = (CANVAS_ROOT / "client" / "static" / "js" / "audio-gallery.js").read_text()
AUDIO_CSS = (CANVAS_ROOT / "client" / "static" / "css" / "audio-gallery.css").read_text()
BASE_CSS = (CANVAS_ROOT / "client" / "static" / "css" / "base.css").read_text()


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _load_audio_catalog():
    return _load_module("canvas_audio_catalog_test", LIB_ROOT / "audio_catalog.py")


def _load_audio_gallery():
    sys.path.insert(0, str(LIB_ROOT))
    sys.path.insert(0, str(CANVAS_ROOT))
    return _load_module(
        "canvas_audio_gallery_test",
        CANVAS_ROOT / "server" / "routes" / "audio_gallery.py",
    )


def _client(audio_gallery):
    app = Flask(
        __name__,
        template_folder=str(CANVAS_ROOT / "client" / "templates"),
    )
    app.register_blueprint(audio_gallery.audio_gallery_bp)
    return app.test_client()


def test_audio_catalog_backfills_files_and_preserves_favorites(tmp_path):
    catalog_module = _load_audio_catalog()
    audio_file = tmp_path / "music_deep_orbit_20260726_214737.mp3"
    audio_file.write_bytes(b"audio")
    catalog_file = tmp_path / "audio_catalog.json"

    catalog = catalog_module.sync_audio_catalog(tmp_path, catalog_file)

    assert catalog[audio_file.name]["title"] == "Deep Orbit"
    assert catalog[audio_file.name]["provider"] == "ElevenLabs"
    assert catalog[audio_file.name]["format"] == "mp3"
    assert catalog[audio_file.name]["favorite"] is False

    catalog[audio_file.name]["favorite"] = True
    catalog[audio_file.name]["favorited_at"] = "2026-07-26T22:00:00"
    catalog_module.save_audio_catalog(catalog_file, catalog)
    updated = catalog_module.upsert_audio_catalog_entry(
        catalog_file,
        audio_file.name,
        {"genre": "ambient", "provider": "Future Provider"},
    )

    assert updated["provider"] == "Future Provider"
    assert updated["genre"] == "ambient"
    assert updated["favorite"] is True
    assert updated["favorited_at"] == "2026-07-26T22:00:00"


def test_audio_gallery_lists_favorites_downloads_and_deletes(tmp_path, monkeypatch):
    audio_gallery = _load_audio_gallery()
    monkeypatch.setattr(audio_gallery, "GENERATED_AUDIO_DIR", tmp_path)
    monkeypatch.setattr(audio_gallery, "AUDIO_CATALOG_FILE", tmp_path / "audio_catalog.json")
    monkeypatch.setattr(
        audio_gallery,
        "probe_audio",
        lambda _path: {
            "duration_seconds": 29.99,
            "codec": "mp3",
            "sample_rate": 44100,
        },
    )
    audio_file = tmp_path / "music_deep_orbit_20260726_214737.mp3"
    audio_file.write_bytes(b"fake-mp3")
    (tmp_path / "audio_catalog.json").write_text(json.dumps({
        audio_file.name: {
            "title": "Deep Orbit",
            "provider": "Google Gemini",
            "model": "lyria-3-pro-preview",
        }
    }))
    client = _client(audio_gallery)

    listed_response = client.get("/api/gallery/audio")
    favorite_response = client.patch(
        f"/api/gallery/audio/{audio_file.name}/favorite",
        json={"favorite": True},
    )
    download_response = client.get(
        f"/api/gallery/audio/{audio_file.name}/download"
    )

    assert listed_response.status_code == 200
    listed = listed_response.get_json()["audio"][0]
    assert listed["name"] == audio_file.name
    assert listed["title"] == "Deep Orbit"
    assert listed["provider"] == "Google Gemini"
    assert listed["model"] == "lyria-3-pro-preview"
    assert listed["duration_seconds"] == 29.99
    assert listed["codec"] == "mp3"
    assert favorite_response.status_code == 200
    assert favorite_response.get_json()["favorite"] is True
    assert download_response.status_code == 200
    assert "attachment" in download_response.headers["Content-Disposition"]

    catalog = json.loads((tmp_path / "audio_catalog.json").read_text())
    assert catalog[audio_file.name]["favorite"] is True
    assert catalog[audio_file.name]["favorited_at"]

    delete_response = client.delete(f"/api/gallery/audio/{audio_file.name}")
    assert delete_response.status_code == 200
    assert delete_response.get_json()["deleted"] == audio_file.name
    assert not audio_file.exists()
    assert audio_file.name not in json.loads(
        (tmp_path / "audio_catalog.json").read_text()
    )


def test_audio_gallery_rejects_unsafe_unsupported_or_linked_files(
    tmp_path,
    monkeypatch,
):
    audio_gallery = _load_audio_gallery()
    monkeypatch.setattr(audio_gallery, "GENERATED_AUDIO_DIR", tmp_path)
    monkeypatch.setattr(audio_gallery, "AUDIO_CATALOG_FILE", tmp_path / "audio_catalog.json")

    assert audio_gallery.is_safe_audio_filename("track.mp3") is True
    assert audio_gallery.is_safe_audio_filename("track.opus") is True
    assert audio_gallery.is_safe_audio_filename("../track.mp3") is False
    assert audio_gallery.is_safe_audio_filename("track.exe") is False
    assert audio_gallery.is_safe_audio_filename("folder/track.mp3") is False

    outside_audio = tmp_path.parent / "outside-track.mp3"
    outside_audio.write_bytes(b"outside")
    linked_audio = tmp_path / "linked-track.mp3"
    linked_audio.symlink_to(outside_audio)

    response = _client(audio_gallery).get(
        f"/api/gallery/audio/{linked_audio.name}"
    )

    assert response.status_code == 404


def test_generate_music_persists_provider_neutral_catalog_on_stash_failure(
    tmp_path,
    monkeypatch,
):
    sys.path.insert(0, str(LIB_ROOT))
    generate_music = _load_module(
        "generate_music_audio_catalog_test",
        PROJECT_ROOT / "skills" / "generate_music.py",
    )
    monkeypatch.setattr(generate_music, "GENERATED_MUSIC_DIR", tmp_path)
    monkeypatch.setattr(
        generate_music,
        "AUDIO_CATALOG_FILE",
        tmp_path / "audio_catalog.json",
    )

    import stash_helper

    def fail_open_space(**_kwargs):
        raise RuntimeError("stash unavailable")

    monkeypatch.setattr(stash_helper, "open_space", fail_open_space)
    result = generate_music.save_to_stash(
        {
            "audio_bytes": b"generated-audio",
            "extension": "mp3",
            "mime_type": "audio/mpeg",
            "prompt": "Deep orbital ambient score",
            "genre": "ambient",
            "mood": "cinematic",
            "tempo": "slow",
            "instrumental": True,
            "duration_ms": 30000,
            "output_format": "mp3",
            "requested_output_format": "mp3_high",
            "requested_duration_ms": 75000,
            "provider": "Google Gemini",
            "model": "lyria-3-clip-preview",
            "generation_text": "Original instrumental",
            "synthid_watermarked": True,
        },
        "Deep Orbit",
    )

    assert result["saved"] is True
    assert result["stash"] is False
    assert Path(result["path"]).read_bytes() == b"generated-audio"
    catalog = json.loads((tmp_path / "audio_catalog.json").read_text())
    entry = catalog[result["filename"]]
    assert entry["title"] == "Deep Orbit"
    assert entry["provider"] == "Google Gemini"
    assert entry["model"] == "lyria-3-clip-preview"
    assert entry["genre"] == "ambient"
    assert entry["instrumental"] is True
    assert entry["duration_seconds"] == 30
    assert entry["requested_duration_seconds"] == 75
    assert entry["requested_output_format"] == "mp3_high"
    assert entry["generation_text"] == "Original instrumental"
    assert entry["synthid_watermarked"] is True
    assert "google_gemini" in entry["tags"]


def test_audio_gallery_ui_keeps_actions_and_adds_live_visualizer():
    assert "<span>Audio</span>" in AUDIO_HTML
    assert 'id="providerFilter"' in AUDIO_HTML
    assert 'id="favoriteFilter"' in AUDIO_HTML
    assert 'id="sortSelect"' in AUDIO_HTML
    assert "class=\"audio-player\"" in AUDIO_JS
    assert "class=\"audio-model\"" in AUDIO_JS
    assert "const model = String(item.model || '').trim();" in AUDIO_JS
    assert "${model ?" in AUDIO_JS
    assert "setupExclusivePlayback" in AUDIO_JS
    assert "class AudioGalleryVisualizer" in AUDIO_JS
    assert "createMediaElementSource" in AUDIO_JS
    assert "getByteFrequencyData" in AUDIO_JS
    assert "requestAnimationFrame" in AUDIO_JS
    assert "role=\"slider\"" in AUDIO_JS
    assert "audio-seek-time" in AUDIO_JS
    assert "prefers-reduced-motion: reduce" in AUDIO_JS
    assert "/api/gallery/audio/" in AUDIO_JS
    assert "toggleFavoriteByIndex" in AUDIO_JS
    assert "downloadByIndex" in AUDIO_JS
    assert "deleteByIndex" in AUDIO_JS
    assert "'&quot;'" in AUDIO_JS
    assert "@media (max-width: 768px)" in AUDIO_CSS
    assert ".audio-model" in AUDIO_CSS
    assert ".audio-card.is-playing" in AUDIO_CSS
    assert ".audio-visualizer:focus-visible" in AUDIO_CSS
    assert ".audio-play-status" in AUDIO_CSS
    assert "@media (prefers-reduced-motion: reduce)" in AUDIO_CSS
    assert ".audio-gallery-header .logo span" in AUDIO_CSS
    assert ".header-link span" in BASE_CSS
    assert ".audio-mobile-label" not in BASE_CSS

    for template_name in ("canvas.html", "gallery.html", "video-gallery.html"):
        template = (CANVAS_ROOT / "client" / "templates" / template_name).read_text()
        assert 'href="/audio-gallery"' in template
        assert "🎵 <span>Audio</span>" in template
        assert "audio-mobile-label" not in template
