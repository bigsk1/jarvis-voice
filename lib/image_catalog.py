"""Shared persistence for generated-image catalog metadata."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def load_image_catalog(catalog_file: Path) -> dict[str, dict[str, Any]]:
    """Load an image catalog, treating missing or invalid JSON as empty."""
    if not catalog_file.exists():
        return {}
    try:
        data = json.loads(catalog_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_image_catalog(
    catalog_file: Path,
    catalog: dict[str, dict[str, Any]],
) -> None:
    """Atomically persist an image catalog."""
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


def upsert_image_catalog_entry(
    catalog_file: Path,
    filename: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Merge generated metadata while preserving user-managed favorite state."""
    catalog = load_image_catalog(catalog_file)
    existing = catalog.get(filename, {})
    favorite = bool(existing.get("favorite", False))
    favorited_at = existing.get("favorited_at")

    updated = dict(existing)
    updated.update({key: value for key, value in metadata.items() if value is not None})
    updated["favorite"] = favorite
    updated["favorited_at"] = favorited_at
    catalog[filename] = updated
    save_image_catalog(catalog_file, catalog)
    return updated
