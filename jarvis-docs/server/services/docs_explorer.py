"""
Reader-focused documentation explorer for the Jarvis docs UI.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path


ALLOWED_DOCUMENT_EXTENSIONS = {'.md'}
PREVIEW_LENGTH = 220
DATE_TOKEN_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$|^\d{8}_\d{6}$|^\d{8}$')


class DocsExplorerError(ValueError):
    """Raised when a docs request cannot be completed safely."""


class DocsExplorerService:
    """List, search, read, and optionally edit markdown files under docs/."""

    def __init__(self, docs_root: Path, edit_enabled: bool = False):
        self.docs_root = docs_root.resolve()
        self.edit_enabled = edit_enabled

    def list_folders(self) -> list[dict]:
        """Return root plus folders that contain markdown documents."""
        if not self.docs_root.exists():
            return []

        documents = list(self._iter_documents(self.docs_root))
        if not documents:
            return []

        folders: list[dict] = [self._build_folder_entry(self.docs_root, documents, is_root=True)]
        seen_dirs: set[Path] = set()
        for document in documents:
            current = document.parent
            while current != self.docs_root.parent and current != self.docs_root:
                if current in seen_dirs:
                    break
                seen_dirs.add(current)
                folder_docs = [path for path in documents if current == path.parent or current in path.parents]
                if folder_docs:
                    folders.append(self._build_folder_entry(current, folder_docs))
                current = current.parent

        folders.sort(key=lambda item: (item['depth'], item['label'].lower()))
        return folders

    def list_documents(
        self,
        folder: str = '',
        search: str = '',
        sort: str = 'recent',
        offset: int = 0,
        limit: int = 40,
    ) -> dict:
        """List markdown documents for the selected folder."""
        folder_path = self.resolve_directory(folder)
        documents = list(self._iter_documents(folder_path))
        query = search.strip().lower()
        items: list[dict] = []

        for path in documents:
            metadata = self._document_metadata(path)
            if query:
                body = self._read_text(path)
                match_count = body.lower().count(query)
                title_match = metadata['title'].lower().count(query)
                filename_match = metadata['filename'].lower().count(query)
                stem_match = metadata['stem'].lower().count(query)
                path_match = metadata['path'].lower().count(query)
                if match_count <= 0 and title_match <= 0 and filename_match <= 0 and stem_match <= 0 and path_match <= 0:
                    continue
                metadata['match_count'] = (
                    match_count
                    + title_match
                    + filename_match
                    + stem_match
                    + path_match
                )
                metadata['preview'] = self._build_match_preview(body, query)
            else:
                metadata['match_count'] = 0
                metadata['preview'] = self._build_document_preview(path)
            items.append(metadata)

        items = self._sort_documents(items, sort=sort, prioritize_hits=bool(query))
        total = len(items)
        page = items[offset:offset + limit]
        return {
            'folder': self._relative_dir(folder_path),
            'documents': page,
            'offset': offset,
            'limit': limit,
            'returned': len(page),
            'total': total,
            'has_more': offset + len(page) < total,
            'next_offset': offset + len(page),
            'search': search,
            'sort': sort,
        }

    def read_document(self, relative_path: str) -> dict:
        """Read a markdown document for display."""
        file_path = self.resolve_document(relative_path)
        content = self._read_text(file_path)
        metadata = self._document_metadata(file_path)
        metadata.update({
            'content': content,
            'edit_enabled': self.edit_enabled,
            'outline': self._extract_outline(content),
            'reading_time_minutes': max(1, round(metadata['word_count'] / 200)),
        })
        return metadata

    def save_document(self, relative_path: str, content: str) -> dict:
        """Persist markdown content when editing is enabled."""
        if not self.edit_enabled:
            raise DocsExplorerError('Editing is disabled for this docs UI')

        file_path = self.resolve_document(relative_path)
        file_path.write_text(content, encoding='utf-8')
        return self.read_document(relative_path)

    def resolve_document(self, relative_path: str) -> Path:
        if not relative_path:
            raise DocsExplorerError('Document path is required')
        resolved = (self.docs_root / relative_path).resolve()
        self._ensure_within_root(resolved)
        if (
            not resolved.exists()
            or not resolved.is_file()
            or resolved.suffix.lower() not in ALLOWED_DOCUMENT_EXTENSIONS
            or resolved.name.startswith('.')
        ):
            raise DocsExplorerError(f'Document not found: {relative_path}')
        return resolved

    def resolve_directory(self, relative_path: str = '') -> Path:
        resolved = (self.docs_root / relative_path).resolve() if relative_path else self.docs_root
        self._ensure_within_root(resolved)
        if not resolved.exists() or not resolved.is_dir():
            raise DocsExplorerError(f'Folder not found: {relative_path or "docs"}')
        return resolved

    def resolve_asset(self, relative_path: str) -> Path:
        if not relative_path:
            raise DocsExplorerError('Asset path is required')
        resolved = (self.docs_root / relative_path).resolve()
        self._ensure_within_root(resolved)
        if not resolved.exists() or not resolved.is_file() or resolved.name.startswith('.'):
            raise DocsExplorerError(f'Asset not found: {relative_path}')
        return resolved

    def _iter_documents(self, base_path: Path):
        for path in sorted(base_path.rglob('*.md')):
            if path.name.startswith('.'):
                continue
            if any(part.startswith('.') for part in path.relative_to(base_path).parts):
                continue
            yield path

    def _build_folder_entry(self, directory: Path, documents: list[Path], is_root: bool = False) -> dict:
        latest = max(documents, key=lambda path: path.stat().st_mtime)
        relative = self._relative_dir(directory)
        return {
            'path': relative,
            'name': 'All Docs' if is_root else directory.name,
            'label': 'All Docs' if is_root else relative,
            'depth': 0 if is_root else len(Path(relative).parts),
            'document_count': len(documents),
            'latest_document': latest.name,
            'latest_modified_at': self._iso_from_timestamp(latest.stat().st_mtime),
        }

    def _document_metadata(self, file_path: Path) -> dict:
        stat = file_path.stat()
        content = self._read_text(file_path)
        title = self._extract_title(file_path, content)
        relative_dir = self._relative_dir(file_path.parent)
        return {
            'path': self._relative_file(file_path),
            'folder': relative_dir,
            'filename': file_path.name,
            'title': title,
            'stem': file_path.stem,
            'size_bytes': stat.st_size,
            'size_label': self._format_size(stat.st_size),
            'modified_at': self._iso_from_timestamp(stat.st_mtime),
            'word_count': self._count_words(content),
            'tags': self._infer_tags(file_path),
        }

    def _sort_documents(self, items: list[dict], sort: str, prioritize_hits: bool = False) -> list[dict]:
        if prioritize_hits:
            if sort == 'name':
                return sorted(
                    items,
                    key=lambda item: (-item.get('match_count', 0), item['title'].lower(), item['modified_at']),
                )
            if sort == 'oldest':
                return sorted(
                    items,
                    key=lambda item: (-item.get('match_count', 0), item['modified_at'], item['title'].lower()),
                )
            return sorted(
                items,
                key=lambda item: (item.get('match_count', 0), item['modified_at'], item['title'].lower()),
                reverse=True,
            )

        if sort == 'name':
            return sorted(items, key=lambda item: item['title'].lower())
        if sort == 'oldest':
            return sorted(items, key=lambda item: (item['modified_at'], item['title'].lower()))
        return sorted(
            items,
            key=lambda item: (item['modified_at'], item['title'].lower()),
            reverse=True,
        )

    def _build_document_preview(self, file_path: Path) -> str:
        content = self._read_text(file_path)
        return self._preview_from_text(content)

    def _build_match_preview(self, text: str, query: str) -> str:
        lowered = text.lower()
        index = lowered.find(query)
        if index < 0:
            return self._preview_from_text(text)

        start = max(0, index - 90)
        end = min(len(text), index + max(len(query), 30) + 90)
        snippet = text[start:end].replace('\n', ' ').strip()
        if start > 0:
            snippet = f'...{snippet}'
        if end < len(text):
            snippet = f'{snippet}...'
        return re.sub(r'\s+', ' ', snippet)

    def _preview_from_text(self, text: str) -> str:
        cleaned_lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith('#'):
                continue
            cleaned_lines.append(stripped)
            if len(' '.join(cleaned_lines)) >= PREVIEW_LENGTH:
                break
        preview = re.sub(r'\s+', ' ', ' '.join(cleaned_lines)).strip()
        return preview[:PREVIEW_LENGTH].rstrip() if preview else 'No preview available yet.'

    def _extract_title(self, file_path: Path, content: str) -> str:
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith('# '):
                return stripped[2:].strip()
        return file_path.stem.replace('-', ' ').replace('_', ' ').strip() or file_path.name

    def _extract_outline(self, content: str) -> list[dict]:
        outline = []
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped.startswith('#'):
                continue
            level = len(stripped) - len(stripped.lstrip('#'))
            title = stripped[level:].strip()
            if title:
                outline.append({'level': level, 'title': title})
        return outline[:60]

    def _count_words(self, text: str) -> int:
        return len(re.findall(r'\b\w+\b', text))

    def _infer_tags(self, file_path: Path) -> list[str]:
        tags = set()
        relative_folder = self._relative_dir(file_path.parent)
        if relative_folder:
            tags.update(part for part in Path(relative_folder).parts if part)

        for token in re.split(r'[-_]+', file_path.stem):
            token = token.strip().lower()
            if not token or DATE_TOKEN_RE.match(token) or token.isdigit():
                continue
            tags.add(token)

        return sorted(tags)[:6]

    def _read_text(self, file_path: Path) -> str:
        return file_path.read_text(encoding='utf-8', errors='replace')

    def _relative_dir(self, directory: Path) -> str:
        relative = directory.resolve().relative_to(self.docs_root)
        return '' if str(relative) == '.' else relative.as_posix()

    def _relative_file(self, file_path: Path) -> str:
        return file_path.resolve().relative_to(self.docs_root).as_posix()

    def _ensure_within_root(self, path: Path) -> None:
        try:
            path.relative_to(self.docs_root)
        except ValueError as exc:
            raise DocsExplorerError('Path escapes docs directory') from exc

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


def _docs_edit_enabled_from_env() -> bool:
    return os.environ.get('DOCS_UI_EDIT_ENABLED', '').strip().lower() in {'1', 'true', 'yes', 'on'}


def get_docs_explorer(docs_root: Path) -> DocsExplorerService:
    return DocsExplorerService(docs_root=docs_root, edit_enabled=_docs_edit_enabled_from_env())
