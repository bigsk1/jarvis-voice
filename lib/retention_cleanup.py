"""Retention helpers shared by cleanup jobs and Web attachment recovery."""

import json
import os
import re
import stat
import time
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

_PROMPT_GUARD_INCIDENT_NAME = re.compile(r"(?:\d{4}-\d{2}-\d{2}-)?pg-[0-9a-f]{32}\.json\Z")


def _open_existing_incident_directory(path: Path) -> int:
    """Open an existing absolute path without following any directory symlink."""
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("invalid_directory")
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def cleanup_prompt_guard_incidents(
    *, retention_days: int | None = None, dry_run: bool = False,
) -> dict:
    """Expire private incident files for each configured mode, without reading evidence.

    Validate every mode before deleting anything. Directory handles pin the
    preflighted locations, and no cleanup step creates paths or changes modes.
    """
    try:
        from config_loader import config_scope, get_config_value, get_project_root
    except ModuleNotFoundError as exc:
        if exc.name != "config_loader":
            raise
        from lib.config_loader import config_scope, get_config_value, get_project_root

    result = {
        'deleted_files': 0, 'freed_bytes': 0, 'candidates': [], 'modes': {}, 'errors': [],
    }
    root = get_project_root()
    plans: list[tuple[str, Path, int]] = []
    for mode in ('cloud', 'local'):
        if not (root / 'config' / f'{mode}.env').is_file():
            continue
        with config_scope(mode):
            raw_days = (
                retention_days if retention_days is not None else
                get_config_value('PROMPT_GUARD_INCIDENT_RETENTION_DAYS', '90')
            )
            try:
                days = int(raw_days) if isinstance(raw_days, str) else raw_days
                if type(days) is not int or days < 1:
                    raise ValueError
            except (ValueError, TypeError):
                result['errors'].append({'mode': mode, 'error': 'invalid_retention_days'})
                continue
            configured = str(get_config_value('PROMPT_GUARD_INCIDENT_DIR', '') or '').strip()
            base = Path(configured).expanduser() if configured else (
                root / 'logs' / 'prompt-guard' / 'incidents'
            )
            if not base.is_absolute():
                base = root / base
            if '..' in base.parts:
                result['errors'].append({'mode': mode, 'error': 'invalid_directory'})
                continue
            plans.append((mode, base, days))
    if result['errors']:
        return result

    now = int(time.time())
    with ExitStack() as handles:
        opened: list[tuple[str, int, int]] = []
        for mode, base, days in plans:
            result['modes'][mode] = {'retention_days': days, 'candidates': 0, 'deleted_files': 0}
            try:
                base_fd = _open_existing_incident_directory(base)
                handles.callback(os.close, base_fd)
                if os.fstat(base_fd).st_uid != os.getuid():
                    raise PermissionError
                directory_fd = os.open(
                    mode, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=base_fd,
                )
                handles.callback(os.close, directory_fd)
                if os.fstat(directory_fd).st_uid != os.getuid():
                    raise PermissionError
            except FileNotFoundError:
                continue
            except (OSError, ValueError):
                result['errors'].append({'mode': mode, 'error': 'unsafe_or_unreadable_directory'})
                continue
            opened.append((mode, directory_fd, now - days * 86400))
        if result['errors']:
            return result

        for mode, directory_fd, cutoff in opened:
            try:
                names = os.listdir(directory_fd)
            except OSError:
                result['errors'].append({'mode': mode, 'error': 'directory_listing_failed'})
                continue
            for name in names:
                if not _PROMPT_GUARD_INCIDENT_NAME.fullmatch(name):
                    continue
                try:
                    before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if not stat.S_ISREG(before.st_mode) or before.st_mtime >= cutoff:
                        continue
                    current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if (
                        current.st_dev, current.st_ino, current.st_mtime_ns, current.st_ctime_ns,
                        current.st_size, current.st_mode,
                    ) != (
                        before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns,
                        before.st_size, before.st_mode,
                    ):
                        continue
                    result['candidates'].append(f'{mode}/{name}')
                    result['modes'][mode]['candidates'] += 1
                    if not dry_run:
                        os.unlink(name, dir_fd=directory_fd)
                        result['deleted_files'] += 1
                        result['modes'][mode]['deleted_files'] += 1
                    result['freed_bytes'] += current.st_size
                except FileNotFoundError:
                    continue
                except OSError:
                    result['errors'].append({'mode': mode, 'file': name, 'error': 'cleanup_failed'})
    return result


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
