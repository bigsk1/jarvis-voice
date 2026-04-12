"""
Read-only log explorer helpers for the Jarvis Web UI.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Iterator

import yaml

from ..config import JARVIS_ROOT


ALLOWED_EXTENSIONS = {'.jsonl', '.log', '.md'}
SEARCHABLE_EXTENSIONS = {'.jsonl', '.log', '.md'}
DATE_TOKEN_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$|^\d{8}_\d{6}$|^\d{8}$')


class LogExplorerError(ValueError):
    """Raised when a log path or request is invalid."""


class _ReadableYamlDumper(yaml.SafeDumper):
    """YAML dumper with nicer multiline string formatting for log display."""


def _represent_readable_string(dumper, value: str):
    cleaned = value.rstrip('\r\n')
    style = '|' if '\n' in cleaned else None
    return dumper.represent_scalar('tag:yaml.org,2002:str', cleaned, style=style)


_ReadableYamlDumper.add_representer(str, _represent_readable_string)


class LogExplorerService:
    """Discover, filter, and page through log files."""

    def __init__(self, logs_root: Path | None = None):
        self.logs_root = (logs_root or (JARVIS_ROOT / 'logs')).resolve()

    def list_folders(self) -> list[dict]:
        """Return only folders that contain viewable log files."""
        if not self.logs_root.exists():
            return []

        folders = []
        for current_root, dirnames, filenames in os.walk(self.logs_root):
            dirnames[:] = sorted(
                directory for directory in dirnames if not directory.startswith('.')
            )
            current_path = Path(current_root)
            allowed_files = [
                current_path / filename
                for filename in filenames
                if self._is_allowed_file(current_path / filename)
            ]
            if not allowed_files:
                continue

            relative_path = self._relative_dir(current_path)
            latest_file = max(allowed_files, key=lambda path: path.stat().st_mtime)
            folders.append({
                'path': relative_path,
                'name': 'logs' if not relative_path else current_path.name,
                'label': 'logs' if not relative_path else relative_path,
                'depth': 0 if not relative_path else len(Path(relative_path).parts),
                'file_count': len(allowed_files),
                'extensions': self._folder_extensions(allowed_files),
                'latest_file': latest_file.name,
                'latest_modified_at': self._iso_from_timestamp(latest_file.stat().st_mtime),
            })

        folders.sort(key=lambda item: item['label'].lower())
        return folders

    def list_files(
        self,
        folder: str = '',
        search: str = '',
        extension: str = '',
        sort: str = 'newest',
        days: int | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict:
        """List log files within a folder with optional filtering."""
        folder_path = self.resolve_directory(folder)
        files = [path for path in folder_path.iterdir() if self._is_allowed_file(path)]

        normalized_extension = self._normalize_extension(extension)
        if normalized_extension:
            files = [path for path in files if path.suffix == normalized_extension]

        if days and days > 0:
            cutoff = datetime.now().timestamp() - (days * 86400)
            files = [path for path in files if path.stat().st_mtime >= cutoff]

        normalized_search = search.strip().lower()
        items = []
        for path in files:
            metadata = self._file_metadata(path)
            if normalized_search:
                hit_count = self._search_file(path, normalized_search)
                if hit_count <= 0 and normalized_search not in metadata['filename'].lower():
                    continue
                metadata['search_hit_count'] = hit_count or 1
            else:
                metadata['search_hit_count'] = 0
            items.append(metadata)

        items = self._sort_files(items, sort, prioritize_hits=bool(normalized_search))
        total = len(items)
        page = items[offset:offset + limit]
        return {
            'folder': self._relative_dir(folder_path),
            'files': page,
            'offset': offset,
            'limit': limit,
            'returned': len(page),
            'total': total,
            'has_more': offset + len(page) < total,
            'next_offset': offset + len(page),
        }

    def read_file(self, relative_path: str, offset: int = 0, limit: int = 50, search: str = '') -> dict:
        """Read a log file in a format suited for the viewer."""
        file_path = self.resolve_file(relative_path)
        if file_path.suffix == '.jsonl':
            return self._read_jsonl(file_path, offset=offset, limit=limit, search=search)
        if file_path.suffix == '.log':
            return self._read_log(file_path, offset=offset, limit=limit, search=search)
        if file_path.suffix == '.md':
            return self._read_markdown(file_path)
        raise LogExplorerError(f'Unsupported log file type: {file_path.suffix}')

    def resolve_directory(self, relative_path: str = '') -> Path:
        candidate = self.logs_root if not relative_path else (self.logs_root / relative_path)
        resolved = candidate.resolve()
        self._ensure_within_root(resolved)
        if not resolved.exists() or not resolved.is_dir():
            raise LogExplorerError(f'Folder not found: {relative_path or "logs"}')
        return resolved

    def resolve_file(self, relative_path: str) -> Path:
        if not relative_path:
            raise LogExplorerError('File path is required')
        resolved = (self.logs_root / relative_path).resolve()
        self._ensure_within_root(resolved)
        if not resolved.exists() or not resolved.is_file() or not self._is_allowed_file(resolved):
            raise LogExplorerError(f'File not found or not allowed: {relative_path}')
        return resolved

    def _read_jsonl(self, file_path: Path, offset: int, limit: int, search: str = '') -> dict:
        records = []
        consumed = 0
        normalized_search = search.strip().lower()
        iterator = self._iter_lines_reverse(file_path)
        for line in iterator:
            line = line.strip()
            if not line:
                continue
            if normalized_search and normalized_search not in line.lower():
                continue
            if consumed < offset:
                consumed += 1
                continue
            records.append(self._jsonl_record(line))
            consumed += 1
            if len(records) >= limit + 1:
                break

        has_more = len(records) > limit
        if has_more:
            records = records[:limit]

        metadata = self._file_metadata(file_path)
        metadata.update({
            'view_type': 'yaml-records',
            'records': records,
            'offset': offset,
            'limit': limit,
            'returned': len(records),
            'has_more': has_more,
            'next_offset': offset + len(records),
            'search': search,
        })
        return metadata

    def _read_log(self, file_path: Path, offset: int, limit: int, search: str = '') -> dict:
        lines = []
        consumed = 0
        normalized_search = search.strip().lower()
        iterator = self._iter_lines_reverse(file_path)
        for line in iterator:
            if not line.strip():
                continue
            if normalized_search and normalized_search not in line.lower():
                continue
            if consumed < offset:
                consumed += 1
                continue
            lines.append(line.rstrip('\n'))
            consumed += 1
            if len(lines) >= limit + 1:
                break

        has_more = len(lines) > limit
        if has_more:
            lines = lines[:limit]

        metadata = self._file_metadata(file_path)
        metadata.update({
            'view_type': 'text-lines',
            'lines': lines,
            'offset': offset,
            'limit': limit,
            'returned': len(lines),
            'has_more': has_more,
            'next_offset': offset + len(lines),
            'search': search,
        })
        return metadata

    def _read_markdown(self, file_path: Path) -> dict:
        metadata = self._file_metadata(file_path)
        metadata.update({
            'view_type': 'markdown',
            'content': file_path.read_text(encoding='utf-8', errors='replace'),
            'offset': 0,
            'limit': 1,
            'returned': 1,
            'has_more': False,
            'next_offset': 1,
            'search': '',
        })
        return metadata

    def _jsonl_record(self, line: str) -> dict:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            payload = {'raw_line': line}

        nested = self._normalize_for_yaml_display(self._nestify(payload))
        timestamp = self._extract_timestamp(nested)
        yaml_text = yaml.dump(
            nested,
            Dumper=_ReadableYamlDumper,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=False,
            width=1000,
        ).strip()

        return {
            'timestamp': timestamp,
            'yaml': yaml_text,
        }

    def _sort_files(self, items: list[dict], sort: str, prioritize_hits: bool = False) -> list[dict]:
        if prioritize_hits:
            if sort == 'oldest':
                return sorted(
                    items,
                    key=lambda item: (
                        -item.get('search_hit_count', 0),
                        item['modified_at'],
                        item['filename'].lower(),
                    ),
                )
            if sort == 'name':
                return sorted(
                    items,
                    key=lambda item: (
                        -item.get('search_hit_count', 0),
                        item['filename'].lower(),
                        item['modified_at'],
                    ),
                )
            return sorted(
                items,
                key=lambda item: (
                    item.get('search_hit_count', 0),
                    item['modified_at'],
                    item['filename'].lower(),
                ),
                reverse=True,
            )
        if sort == 'oldest':
            return sorted(items, key=lambda item: (item['modified_at'], item['filename']))
        if sort == 'name':
            return sorted(items, key=lambda item: item['filename'].lower())
        return sorted(
            items,
            key=lambda item: (item['modified_at'], item['filename'].lower()),
            reverse=True,
        )

    def _file_metadata(self, file_path: Path) -> dict:
        stat = file_path.stat()
        relative_path = self._relative_file(file_path)
        return {
            'path': relative_path,
            'folder': self._relative_dir(file_path.parent),
            'filename': file_path.name,
            'stem': file_path.stem,
            'extension': file_path.suffix,
            'size_bytes': stat.st_size,
            'size_label': self._format_size(stat.st_size),
            'modified_at': self._iso_from_timestamp(stat.st_mtime),
            'tags': self._infer_tags(file_path),
        }

    def _folder_extensions(self, files: list[Path]) -> list[str]:
        return sorted({path.suffix.lstrip('.') for path in files})

    def _infer_tags(self, file_path: Path) -> list[str]:
        tags = {file_path.suffix.lstrip('.')}
        relative_folder = self._relative_dir(file_path.parent)
        if relative_folder:
            tags.update(part for part in Path(relative_folder).parts if part)

        for token in re.split(r'[-_]+', file_path.stem):
            token = token.strip().lower()
            if not token or DATE_TOKEN_RE.match(token) or token.isdigit():
                continue
            tags.add(token)

        return sorted(tags)[:6]

    def _search_file(self, file_path: Path, query: str) -> int:
        if file_path.suffix not in SEARCHABLE_EXTENSIONS:
            return 0

        hits = 0
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as handle:
                for line in handle:
                    hits += line.lower().count(query)
        except OSError:
            return 0
        return hits

    def _normalize_for_yaml_display(self, value):
        if isinstance(value, dict):
            return {key: self._normalize_for_yaml_display(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._normalize_for_yaml_display(item) for item in value]
        if isinstance(value, str):
            return value.rstrip('\r\n')
        return value

    def _nestify(self, value):
        if isinstance(value, list):
            return [self._nestify(item) for item in value]

        if not isinstance(value, dict):
            return value

        nested = {}
        dotted_items = []

        for key, item in value.items():
            resolved_item = self._nestify(item)
            if isinstance(key, str) and '.' in key and key.strip('.'):
                dotted_items.append((key.split('.'), resolved_item))
            else:
                nested[key] = resolved_item

        for path_parts, resolved_item in dotted_items:
            self._assign_nested_value(nested, path_parts, resolved_item)

        return nested

    def _assign_nested_value(self, target: dict, path_parts: list[str], value) -> None:
        current = target
        for part in path_parts[:-1]:
            existing = current.get(part)
            if not isinstance(existing, dict):
                existing = {}
                current[part] = existing
            current = existing

        leaf = path_parts[-1]
        existing = current.get(leaf)
        if isinstance(existing, dict) and isinstance(value, dict):
            self._merge_dicts(existing, value)
        else:
            current[leaf] = value

    def _merge_dicts(self, target: dict, source: dict) -> None:
        for key, value in source.items():
            if isinstance(target.get(key), dict) and isinstance(value, dict):
                self._merge_dicts(target[key], value)
            else:
                target[key] = value

    def _extract_timestamp(self, payload) -> str:
        if not isinstance(payload, dict):
            return ''

        candidates = [
            payload.get('timestamp'),
            payload.get('time'),
            payload.get('created_at'),
            payload.get('updated_at'),
            payload.get('executed_at'),
            payload.get('date'),
        ]
        for value in candidates:
            if value:
                return str(value)
        return ''

    def _iter_lines_reverse(self, file_path: Path, block_size: int = 8192) -> Iterator[str]:
        with open(file_path, 'rb') as handle:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
            buffer = b''

            while position > 0:
                read_size = min(block_size, position)
                position -= read_size
                handle.seek(position)
                chunk = handle.read(read_size)
                lines = (chunk + buffer).split(b'\n')
                buffer = lines[0]
                for line in reversed(lines[1:]):
                    yield line.decode('utf-8', errors='replace')

            if buffer:
                yield buffer.decode('utf-8', errors='replace')

    def _is_allowed_file(self, file_path: Path) -> bool:
        return (
            file_path.is_file()
            and not file_path.name.startswith('.')
            and file_path.suffix in ALLOWED_EXTENSIONS
        )

    def _relative_dir(self, directory: Path) -> str:
        relative = directory.resolve().relative_to(self.logs_root)
        return '' if str(relative) == '.' else relative.as_posix()

    def _relative_file(self, file_path: Path) -> str:
        return file_path.resolve().relative_to(self.logs_root).as_posix()

    def _ensure_within_root(self, path: Path) -> None:
        try:
            path.relative_to(self.logs_root)
        except ValueError as exc:
            raise LogExplorerError('Path escapes logs directory') from exc

    def _normalize_extension(self, extension: str) -> str:
        if not extension:
            return ''
        normalized = extension if extension.startswith('.') else f'.{extension}'
        if normalized not in ALLOWED_EXTENSIONS:
            raise LogExplorerError(f'Unsupported extension filter: {extension}')
        return normalized

    def _iso_from_timestamp(self, timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp).astimezone().isoformat()

    def _format_size(self, size_bytes: int) -> str:
        units = ['B', 'KB', 'MB', 'GB']
        size = float(size_bytes)
        for unit in units:
            if size < 1024 or unit == units[-1]:
                if unit == 'B':
                    return f'{int(size)} {unit}'
                return f'{size:.1f} {unit}'
            size /= 1024
        return f'{size_bytes} B'


_log_explorer: LogExplorerService | None = None


def get_log_explorer() -> LogExplorerService:
    global _log_explorer
    if _log_explorer is None:
        _log_explorer = LogExplorerService()
    return _log_explorer
