"""Shared persistence and stash enrichment for generated-video catalogs."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


VIDEO_EXTENSIONS = {'.mp4', '.webm', '.mov', '.avi', '.mkv'}
_STASH_FIELDS = {
    'stash_ref',
    'space_id',
    'source_url',
    'source_url_created',
    'edit_url_status',
}


def load_video_catalog(catalog_file: Path) -> dict:
    """Load a catalog, treating a missing or unreadable file as empty."""
    if catalog_file.exists():
        try:
            with open(catalog_file) as handle:
                return json.load(handle)
        except Exception:
            pass
    return {}


def save_video_catalog(catalog_file: Path, catalog: dict) -> None:
    """Atomically persist a catalog without taking down the gallery."""
    catalog_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            dir=catalog_file.parent,
            prefix=f'.{catalog_file.name}.',
            suffix='.tmp',
            delete=False,
        ) as handle:
            json.dump(catalog, handle, indent=2)
            handle.write('\n')
            temporary_path = Path(handle.name)
        os.replace(temporary_path, catalog_file)
    except Exception as exc:
        print(f"⚠️  Failed to save video catalog: {exc}")
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def upsert_video_catalog_entry(
    catalog_file: Path,
    filename: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Merge durable generation metadata for a video."""
    catalog = load_video_catalog(catalog_file)
    updated = dict(catalog.get(filename) or {})
    updated.update({key: value for key, value in metadata.items() if value is not None})
    catalog[filename] = updated
    save_video_catalog(catalog_file, catalog)
    return updated


def _provider_from_tags(tags: list) -> Optional[str]:
    providers = {
        'gemini': 'Gemini',
        'xai': 'xAI',
        'runway': 'Runway',
        'pika': 'Pika',
        'kling': 'Kling',
    }
    for tag, display_name in providers.items():
        if tag in tags:
            return display_name
    return None


def _aspect_from_tags(tags: list) -> Optional[str]:
    for tag in tags:
        if ':' in tag and tag.replace(':', '').replace('.', '').isdigit():
            return tag
    return None


def _status_for_source_url(metadata: dict, now: Optional[datetime] = None) -> Optional[str]:
    source_url = metadata.get('source_url')
    if not source_url or not source_url.startswith(('http://', 'https://')):
        return None

    status = 'available'
    source_url_created = metadata.get('source_url_created')
    if not source_url_created:
        return status
    if not isinstance(source_url_created, str):
        return status

    try:
        created = datetime.fromisoformat(source_url_created.replace('Z', '+00:00'))
        current = now
        if current is None:
            current = datetime.now(tz=created.tzinfo) if created.tzinfo else datetime.now()
        elif created.tzinfo is None and current.tzinfo is not None:
            current = current.replace(tzinfo=None)
        elif created.tzinfo is not None and current.tzinfo is None:
            current = current.replace(tzinfo=created.tzinfo)
        if (current - created).total_seconds() > 4 * 3600:
            status = 'expired'
    except (TypeError, ValueError):
        pass
    return status


def lookup_stash_metadata(
    filename: str,
    stash_dir: Path,
    *,
    now: Optional[datetime] = None,
) -> Optional[dict]:
    """Return the canonical catalog metadata for a stashed video."""
    if not stash_dir.exists():
        return None

    for space_dir in stash_dir.iterdir():
        if not space_dir.is_dir():
            continue
        meta_file = space_dir / 'meta.json'
        if not meta_file.exists():
            continue

        try:
            with open(meta_file) as handle:
                space_meta = json.load(handle)
            if 'generated_videos' not in space_meta.get('labels', []):
                continue

            for file_info in space_meta.get('files', []):
                stored_name = file_info.get('stored_name') or file_info.get('name')
                if stored_name != filename:
                    continue

                tags = file_info.get('tags', [])
                space_id = space_meta.get('space_id')
                file_id = file_info.get('file_id')
                metadata = {
                    'provider': _provider_from_tags(tags),
                    'model': file_info.get('model'),
                    'aspect': _aspect_from_tags(tags),
                    'tags': tags,
                    'tool_origin': file_info.get('tool_origin'),
                    'created_at': file_info.get('created_at'),
                    'stash_ref': (
                        f"stash://{space_id}/{file_id}" if space_id and file_id else None
                    ),
                    'space_id': space_id,
                    'source_url': file_info.get('source_url'),
                    'source_url_created': file_info.get('source_url_created'),
                }
                metadata['edit_url_status'] = _status_for_source_url(metadata, now)
                return metadata
        except Exception:
            continue
    return None


def sync_video_catalog(
    generated_videos_dir: Path,
    stash_dir: Path,
    catalog_file: Path,
    *,
    now: Optional[datetime] = None,
) -> dict:
    """Reconcile files, canonical stash metadata, and time-sensitive fields."""
    catalog = load_video_catalog(catalog_file)
    changed = False
    actual_files = {
        path.name
        for path in generated_videos_dir.iterdir()
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    } if generated_videos_dir.exists() else set()

    for filename in [name for name in catalog if name not in actual_files]:
        del catalog[filename]
        changed = True

    for filename in actual_files:
        existing = catalog.get(filename)
        updated = dict(existing or {})

        # Retry absent or legacy partial entries so either service can repair the
        # shared catalog after the stash metadata becomes available.
        if existing is None or not _STASH_FIELDS.issubset(updated):
            stash_metadata = lookup_stash_metadata(filename, stash_dir, now=now)
            if stash_metadata:
                updated.update(stash_metadata)

        refreshed_status = _status_for_source_url(updated, now)
        if updated.get('edit_url_status') != refreshed_status:
            updated['edit_url_status'] = refreshed_status

        if existing != updated:
            catalog[filename] = updated
            changed = True

    if changed:
        save_video_catalog(catalog_file, catalog)
    return catalog
