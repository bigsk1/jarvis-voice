"""Jarvis Canvas audio-gallery routes."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

from audio_catalog import AUDIO_EXTENSIONS, save_audio_catalog, sync_audio_catalog
from flask import Blueprint, abort, jsonify, render_template, request, send_file

from config import GENERATED_AUDIO_DIR

audio_gallery_bp = Blueprint("audio_gallery", __name__)
AUDIO_CATALOG_FILE = GENERATED_AUDIO_DIR / "audio_catalog.json"

_CATALOG_FIELDS = {
    "created_at",
    "duration_seconds",
    "favorite",
    "favorited_at",
    "format",
    "genre",
    "instrumental",
    "mime_type",
    "model",
    "mood",
    "output_format",
    "prompt",
    "provider",
    "song_id",
    "space_id",
    "stash_ref",
    "tags",
    "tempo",
    "title",
    "tool_origin",
}


def is_safe_audio_filename(filename: str) -> bool:
    """Return true when a gallery filename cannot escape generated_music."""
    return (
        isinstance(filename, str)
        and bool(filename)
        and filename == Path(filename).name
        and ".." not in filename
        and "/" not in filename
        and "\\" not in filename
        and Path(filename).suffix.lower() in AUDIO_EXTENSIONS
    )


def _audio_path(filename: str) -> Path:
    if not is_safe_audio_filename(filename):
        abort(400, "Invalid audio filename")
    filepath = GENERATED_AUDIO_DIR / filename
    try:
        filepath.resolve(strict=True).relative_to(
            GENERATED_AUDIO_DIR.resolve(strict=True)
        )
    except (FileNotFoundError, ValueError):
        abort(404, "Audio not found")
    if filepath.is_symlink() or not filepath.is_file():
        abort(404, "Audio not found")
    return filepath


def probe_audio(filepath: Path) -> dict:
    """Return lightweight stream metadata using ffprobe when available."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-show_entries",
                "format=duration:stream=codec_name,bit_rate,sample_rate",
                "-of",
                "json",
                str(filepath),
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return {}
        payload = json.loads(result.stdout)
        stream = next(
            (
                item
                for item in payload.get("streams", [])
                if item.get("codec_name")
            ),
            {},
        )
        details = {
            "codec": stream.get("codec_name"),
            "bit_rate": int(stream["bit_rate"]) if stream.get("bit_rate") else None,
            "sample_rate": int(stream["sample_rate"]) if stream.get("sample_rate") else None,
        }
        duration = payload.get("format", {}).get("duration")
        if duration is not None:
            details["duration_seconds"] = float(duration)
        return {key: value for key, value in details.items() if value is not None}
    except (OSError, TypeError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return {}


@audio_gallery_bp.route("/audio-gallery")
def audio_gallery():
    """Serve the audio gallery UI."""
    return render_template("audio-gallery.html")


@audio_gallery_bp.route("/api/gallery/audio")
def list_gallery_audio():
    """List durable generated-audio files and catalog metadata."""
    audio_items = []
    total_size = 0
    catalog = sync_audio_catalog(GENERATED_AUDIO_DIR, AUDIO_CATALOG_FILE)

    if GENERATED_AUDIO_DIR.exists():
        for filepath in GENERATED_AUDIO_DIR.iterdir():
            if (
                not filepath.is_file()
                or filepath.is_symlink()
                or filepath.suffix.lower() not in AUDIO_EXTENSIONS
            ):
                continue

            stat = filepath.stat()
            metadata = catalog.get(filepath.name, {})
            audio_info = {
                "name": filepath.name,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "format": filepath.suffix.lower().lstrip("."),
                "favorite": bool(metadata.get("favorite", False)),
            }
            audio_info.update({
                key: metadata[key]
                for key in _CATALOG_FIELDS
                if key in metadata
            })
            audio_info.update(probe_audio(filepath))
            audio_items.append(audio_info)
            total_size += stat.st_size

    audio_items.sort(key=lambda item: item["modified"], reverse=True)
    return jsonify({
        "audio": audio_items,
        "count": len(audio_items),
        "total_size": total_size,
    })


@audio_gallery_bp.route("/api/gallery/audio/<filename>")
def serve_gallery_audio(filename):
    """Serve an audio file inline with conditional/range support."""
    return send_file(_audio_path(filename), conditional=True)


@audio_gallery_bp.route("/api/gallery/audio/<filename>/download")
def download_gallery_audio(filename):
    """Download an audio file with its original filename."""
    filepath = _audio_path(filename)
    return send_file(
        filepath,
        as_attachment=True,
        download_name=filename,
        conditional=True,
    )


@audio_gallery_bp.route(
    "/api/gallery/audio/<filename>/favorite",
    methods=["PATCH"],
)
def set_gallery_audio_favorite(filename):
    """Set or clear the favorite flag for an audio item."""
    _audio_path(filename)
    payload = request.get_json(silent=True) or {}
    favorite = payload.get("favorite")
    if not isinstance(favorite, bool):
        return jsonify({"error": "favorite must be true or false"}), 400

    catalog = sync_audio_catalog(GENERATED_AUDIO_DIR, AUDIO_CATALOG_FILE)
    entry = catalog.setdefault(filename, {})
    entry["favorite"] = favorite
    entry["favorited_at"] = datetime.now().isoformat() if favorite else None
    save_audio_catalog(AUDIO_CATALOG_FILE, catalog)
    return jsonify({
        "ok": True,
        "name": filename,
        "favorite": favorite,
        "favorited_at": entry["favorited_at"],
    })
