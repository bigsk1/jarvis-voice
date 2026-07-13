"""Regression tests for favorite-aware generated image cleanup."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from generated_image_cleanup import cleanup_generated_images  # noqa: E402


def _write_image(path: Path, *, modified: datetime) -> None:
    path.write_bytes(b"fake-image")
    timestamp = modified.timestamp()
    os.utime(path, (timestamp, timestamp))


def test_cleanup_generated_images_preserves_favorites_and_recent_files(tmp_path):
    now = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
    old_plain = tmp_path / "old_plain.png"
    old_favorite = tmp_path / "old_favorite.png"
    recent_plain = tmp_path / "recent_plain.png"

    _write_image(old_plain, modified=now - timedelta(days=150))
    _write_image(old_favorite, modified=now - timedelta(days=150))
    _write_image(recent_plain, modified=now - timedelta(days=10))

    (tmp_path / "image_catalog.json").write_text(
        json.dumps(
            {
                old_plain.name: {"favorite": False},
                old_favorite.name: {
                    "favorite": True,
                    "favorited_at": "2026-07-01T12:00:00",
                },
                recent_plain.name: {},
            }
        )
    )
    (tmp_path / "cdn_catalog.json").write_text(
        json.dumps(
            {
                old_plain.name: {"url": "https://cdn.example/old"},
                old_favorite.name: {"url": "https://cdn.example/favorite"},
            }
        )
    )

    dry_run = cleanup_generated_images(
        tmp_path,
        retention_days=120,
        dry_run=True,
        now=now,
    )

    assert [item["name"] for item in dry_run["candidates"]] == [old_plain.name]
    assert dry_run["deleted_images"] == 0
    assert old_plain.exists()

    result = cleanup_generated_images(
        tmp_path,
        retention_days=120,
        dry_run=False,
        now=now,
    )

    assert result["deleted_images"] == 1
    assert result["preserved_favorites"] == 1
    assert result["preserved_recent"] == 1
    assert not old_plain.exists()
    assert old_favorite.exists()
    assert recent_plain.exists()

    image_catalog = json.loads((tmp_path / "image_catalog.json").read_text())
    cdn_catalog = json.loads((tmp_path / "cdn_catalog.json").read_text())
    assert old_plain.name not in image_catalog
    assert cdn_catalog[old_plain.name]["url"] == "https://cdn.example/old"
    assert image_catalog[old_favorite.name]["favorite"] is True
    assert cdn_catalog[old_favorite.name]["url"] == "https://cdn.example/favorite"
