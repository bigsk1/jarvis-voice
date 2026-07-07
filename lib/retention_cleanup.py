"""Retention helpers shared by cleanup jobs and Web attachment recovery."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse


@dataclass(frozen=True)
class ConversationAssetReferences:
    upload_filenames: frozenset[str]
    stash_space_ids: frozenset[str]


def _walk_values(value):
    if isinstance(value, dict):
        for nested in value.values():
            yield from _walk_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_values(nested)
    elif isinstance(value, str):
        yield value


def _upload_filename(value: str) -> str | None:
    path = urlparse(value).path
    marker = '/api/uploads/'
    if marker not in path:
        return None
    filename = unquote(path.split(marker, 1)[1]).split('/', 1)[0]
    return filename if filename and filename == Path(filename).name else None


def _stash_space_id(value: str) -> str | None:
    if not value.startswith('stash://'):
        return None
    space_id = value.removeprefix('stash://').split('/', 1)[0]
    return space_id if space_id.startswith('space_') else None


def collect_conversation_asset_references(
    conversations_dir: Path,
) -> ConversationAssetReferences:
    """Collect durable upload and stash references from saved conversations."""
    uploads: set[str] = set()
    spaces: set[str] = set()
    if not conversations_dir.exists():
        return ConversationAssetReferences(frozenset(), frozenset())

    for conversation_file in conversations_dir.glob('*.json'):
        if conversation_file.name == 'index.json':
            continue
        try:
            conversation = json.loads(conversation_file.read_text(encoding='utf-8'))
        except Exception:
            continue
        for value in _walk_values(conversation):
            filename = _upload_filename(value)
            if filename:
                uploads.add(filename)
            space_id = _stash_space_id(value)
            if space_id:
                spaces.add(space_id)
    return ConversationAssetReferences(frozenset(uploads), frozenset(spaces))


def cleanup_web_uploads(
    uploads_dir: Path,
    conversations_dir: Path,
    *,
    retention_days: int = 60,
    dry_run: bool = False,
) -> dict:
    """Delete only old uploads that no saved conversation still references."""
    references = collect_conversation_asset_references(conversations_dir)
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    result = {
        'deleted_files': 0,
        'freed_bytes': 0,
        'preserved_referenced': 0,
        'referenced_missing': 0,
        'candidates': [],
        'errors': [],
    }
    if not uploads_dir.exists():
        return result

    existing = {path.name for path in uploads_dir.iterdir() if path.is_file()}
    result['referenced_missing'] = len(references.upload_filenames - existing)
    for path in uploads_dir.iterdir():
        if not path.is_file() or path.name == '.gitkeep':
            continue
        if path.name in references.upload_filenames:
            result['preserved_referenced'] += 1
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if modified >= cutoff:
            continue
        result['candidates'].append(path.name)
        result['freed_bytes'] += path.stat().st_size
        if dry_run:
            continue
        try:
            path.unlink()
            result['deleted_files'] += 1
        except Exception as exc:
            result['errors'].append({'file': path.name, 'error': str(exc)})
    return result


def _stash_refs(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            if key == 'stash_ref' and isinstance(nested, str):
                yield nested
            yield from _stash_refs(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _stash_refs(nested)


def find_upload_stash_fallback(
    filename: str,
    conversations_dir: Path,
    stash_dir: Path,
) -> Path | None:
    """Find the stash copy associated with a missing saved-conversation upload."""
    if not filename or filename != Path(filename).name:
        return None
    for conversation_file in conversations_dir.glob('*.json'):
        if conversation_file.name == 'index.json':
            continue
        try:
            messages = json.loads(
                conversation_file.read_text(encoding='utf-8')
            ).get('messages', [])
        except Exception:
            continue
        for index, message in enumerate(messages):
            if not any(_upload_filename(value) == filename for value in _walk_values(message)):
                continue
            for following in messages[index + 1:]:
                if following.get('role') == 'user':
                    break
                for stash_ref in _stash_refs(following):
                    parts = stash_ref.removeprefix('stash://').split('/', 1)
                    if len(parts) != 2:
                        continue
                    meta_file = stash_dir / parts[0] / 'meta.json'
                    try:
                        meta = json.loads(meta_file.read_text(encoding='utf-8'))
                    except Exception:
                        continue
                    for file_info in meta.get('files', []):
                        if file_info.get('file_id') != parts[1]:
                            continue
                        if not str(file_info.get('mime_type', '')).startswith('image/'):
                            continue
                        candidate = stash_dir / parts[0] / file_info.get('stored_name', '')
                        if candidate.is_file():
                            return candidate
            break
    return None
