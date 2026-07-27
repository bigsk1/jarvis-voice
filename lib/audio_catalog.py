"""Shared persistence for generated-audio catalog metadata."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


AUDIO_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
}

_TIMESTAMP_SUFFIX = re.compile(r"_\d{8}_\d{6}$")


def load_audio_catalog(catalog_file: Path) -> dict[str, dict[str, Any]]:
    """Load an audio catalog, treating missing or invalid JSON as empty."""
    if not catalog_file.exists():
        return {}
    try:
        data = json.loads(catalog_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_audio_catalog(
    catalog_file: Path,
    catalog: dict[str, dict[str, Any]],
) -> None:
    """Atomically persist an audio catalog."""
    catalog_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=catalog_file.parent,
            prefix=f".{catalog_file.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(catalog, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temporary_path = Path(handle.name)
        os.replace(temporary_path, catalog_file)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def display_title_from_filename(filename: str) -> str:
    """Build a readable fallback title from a generated-audio filename."""
    stem = Path(filename).stem
    if stem.startswith("music_"):
        stem = stem[len("music_"):]
    stem = _TIMESTAMP_SUFFIX.sub("", stem)
    title = " ".join(stem.replace("_", " ").split())
    return title.title() if title else Path(filename).stem


def upsert_audio_catalog_entry(
    catalog_file: Path,
    filename: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Merge durable metadata while preserving user-managed favorite state."""
    catalog = load_audio_catalog(catalog_file)
    existing = catalog.get(filename, {})
    favorite = bool(existing.get("favorite", False))
    favorited_at = existing.get("favorited_at")

    updated = dict(existing)
    updated.update({key: value for key, value in metadata.items() if value is not None})
    updated["favorite"] = favorite
    updated["favorited_at"] = favorited_at
    catalog[filename] = updated
    save_audio_catalog(catalog_file, catalog)
    return updated


def sync_audio_catalog(
    generated_audio_dir: Path,
    catalog_file: Path,
) -> dict[str, dict[str, Any]]:
    """Reconcile durable audio files with catalog entries."""
    catalog = load_audio_catalog(catalog_file)
    changed = False
    actual_files = {
        path.name: path
        for path in generated_audio_dir.iterdir()
        if (
            path.is_file()
            and not path.is_symlink()
            and path.suffix.lower() in AUDIO_EXTENSIONS
        )
    } if generated_audio_dir.exists() else {}

    for filename in [name for name in catalog if name not in actual_files]:
        del catalog[filename]
        changed = True

    for filename, path in actual_files.items():
        if filename in catalog:
            continue
        stat = path.stat()
        catalog[filename] = {
            "title": display_title_from_filename(filename),
            "provider": "ElevenLabs" if filename.startswith("music_") else None,
            "format": path.suffix.lower().lstrip("."),
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "favorite": False,
            "favorited_at": None,
            "tool_origin": "generate_music" if filename.startswith("music_") else None,
        }
        changed = True

    if changed:
        save_audio_catalog(catalog_file, catalog)
    return catalog
