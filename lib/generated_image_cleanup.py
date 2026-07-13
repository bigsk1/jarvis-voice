"""Favorite-aware retention cleanup for generated images."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def cleanup_generated_images(
    images_dir: Path,
    *,
    retention_days: int = 120,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Delete old generated images unless marked favorite in image_catalog.json."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cutoff = now - timedelta(days=retention_days)
    image_catalog_file = images_dir / "image_catalog.json"
    image_catalog = _load_json(image_catalog_file)

    result: dict[str, Any] = {
        "deleted_images": 0,
        "freed_bytes": 0,
        "preserved_favorites": 0,
        "preserved_recent": 0,
        "candidates": [],
        "errors": [],
    }

    if not images_dir.exists():
        return result

    image_catalog_changed = False
    for path in sorted(images_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue

        metadata = image_catalog.get(path.name) or {}
        if isinstance(metadata, dict) and metadata.get("favorite"):
            result["preserved_favorites"] += 1
            continue

        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if modified >= cutoff:
            result["preserved_recent"] += 1
            continue

        size = path.stat().st_size
        result["candidates"].append(
            {
                "name": path.name,
                "modified": modified.isoformat(),
                "size": size,
            }
        )
        result["freed_bytes"] += size
        if dry_run:
            continue

        try:
            path.unlink()
            result["deleted_images"] += 1
            if path.name in image_catalog:
                del image_catalog[path.name]
                image_catalog_changed = True
        except OSError as exc:
            result["errors"].append({"file": path.name, "error": str(exc)})

    if not dry_run:
        if image_catalog_changed:
            _save_json(image_catalog_file, image_catalog)
    return result
