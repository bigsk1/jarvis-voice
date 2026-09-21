"""Durable, mode-scoped originals and verifiable passage retrieval.

Reads never create a database. Original bytes, extracted passages and FTS rows
commit together; embedding batches commit separately and can be resumed.
"""

from __future__ import annotations

import errno
import hashlib
import html
import json
import math
import os
import re
import shutil
import sqlite3
import stat
import sys
from contextlib import ExitStack, contextmanager
from pathlib import Path

from config_loader import get_active_config_mode, get_config_value, get_project_root
from embeddings import (
    EMBEDDING_DIMENSIONS,
    EmbeddingError,
    get_embedding,
    get_embedding_fingerprint,
    get_embeddings_batch,
)
from filelock import Timeout
from hybrid_retrieval import fts5_query, reciprocal_rank_score

MAX_SOURCE_BYTES = 25 * 1024 * 1024
MAX_TEXT_CHARS = 1_000_000
MAX_PAGES = 1000
PASSAGE_CHARS = 1800
PASSAGE_OVERLAP_CHARS = 240
INDEX_BATCH_SIZE = 16
TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json", ".srt", ".vtt", ".log"}
_ID = re.compile(r"^[0-9a-f]{64}$")
_STOP_WORDS = set(
    "a an and are as at be by can did do does for from how i in is it me my of on or that the this to was what when where which who with you".split()
)


class LibraryError(ValueError):
    """An actionable input or source availability error."""


class LibraryUnavailableError(LibraryError):
    """The configured library store is unsafe or unavailable, not bad input."""


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise LibraryError(f"{name} must be an integer from {low} to {high}.")
    return value


def _fingerprint():
    return json.dumps(
        {
            **get_embedding_fingerprint("document"),
            "input_format": "source-library-title-passage-v1",
        },
        sort_keys=True,
    )


def _vector(value):
    if (
        not isinstance(value, list)
        or len(value) != EMBEDDING_DIMENSIONS
        or any(type(x) not in (int, float) or not math.isfinite(x) for x in value)
        or not any(value)
    ):
        raise EmbeddingError("Invalid source embedding.")
    return value


@contextmanager
def index_lock(path):
    """Lock without truncating; POSIX also atomically refuses final symlinks."""
    if os.name == "nt":
        import msvcrt

        if Path(path).is_symlink():
            raise LibraryUnavailableError("Library index lock is not a usable regular file.")
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_BINARY, 0o600)
        try:
            opened = os.fstat(descriptor)
            if Path(path).is_symlink() or not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                raise LibraryUnavailableError("Library index lock must be a regular, singly linked file.")
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                if exc.errno == errno.EACCES:
                    raise Timeout(path) from exc
                raise
            try:
                yield
            finally:
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(descriptor)
        return

    import fcntl

    flags = os.O_CREAT | os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise LibraryUnavailableError("Library index lock is not a usable regular file.") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise LibraryUnavailableError("Library index lock must be a regular, singly linked file.")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Timeout(path) from exc
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _inbox_root_parts(root: Path):
    if root.name not in {"cloud", "local"} or root.parent.name != "inbox":
        raise LibraryError("Inbox path is unavailable or points outside the inbox.")
    return ("inbox", root.name)


def _open_under_library(root: Path, relative_parts, *, directory=False):
    """Open inbox/mode/relative without following any replaced component."""
    if os.name == "nt":
        candidate = root.joinpath(*relative_parts) if relative_parts else root
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        if directory:
            flags |= getattr(os, "O_DIRECTORY", 0)
        if candidate.is_symlink() or not candidate.resolve(strict=True).is_relative_to(root.resolve()):
            raise LibraryError("Inbox path is unavailable or points outside the inbox.")
        return os.open(candidate, flags)

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    flags = directory_flags if directory else file_flags
    library_path = root.parent.parent
    try:
        parent = os.open(os.path.realpath(library_path.parent), os.O_RDONLY | os.O_DIRECTORY)
    except OSError as exc:
        raise LibraryError("Inbox path is unavailable or points outside the inbox.") from exc
    try:
        descriptor = os.open(library_path.name, directory_flags, dir_fd=parent)
    except OSError as exc:
        raise LibraryError("Inbox path is unavailable or points outside the inbox.") from exc
    finally:
        os.close(parent)
    try:
        parts = (*_inbox_root_parts(root), *relative_parts)
        for part in parts[:-1]:
            child = os.open(part, directory_flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        opened = os.open(parts[-1], flags, dir_fd=descriptor)
        os.close(descriptor)
        descriptor = None
        return opened
    except OSError as exc:
        raise LibraryError("Inbox path is unavailable or points outside the inbox.") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _open_inbox_file(root: Path, relative: str) -> int:
    """Open a queued file without following inbox, mode, or nested symlinks."""
    path = Path(relative)
    parts = path.parts
    if path.is_absolute() or not parts or any(part in (".", "..") for part in parts):
        raise LibraryError("Inbox path is unavailable or points outside the inbox.")
    return _open_under_library(root, parts)


def _iter_inbox_files(root: Path):
    """List inbox files from a no-follow directory descriptor, not os.walk."""
    _inbox_root_parts(root)
    if os.name == "nt":
        if root.is_symlink() or root.parent.is_symlink():
            raise LibraryError("Inbox path is unavailable or points outside the inbox.")
        if not root.is_dir():
            return
        for current, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = [name for name in dirs if not (Path(current) / name).is_symlink()]
            for name in names:
                path = Path(current) / name
                relative = path.relative_to(root).as_posix()
                if path.is_symlink() or not path.is_file():
                    yield {
                        "relative_path": relative,
                        "size_bytes": 0,
                        "mtime_ns": 0,
                        "eligible": False,
                    }
                    continue
                try:
                    info = path.stat()
                except OSError:
                    continue
                yield {
                    "relative_path": relative,
                    "size_bytes": info.st_size,
                    "mtime_ns": info.st_mtime_ns,
                    "eligible": path.suffix.lower() in TEXT_SUFFIXES | {".pdf"}
                    and 0 < info.st_size <= MAX_SOURCE_BYTES
                    and info.st_nlink == 1,
                }
        return

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        mode_fd = _open_under_library(root, (), directory=True)
    except LibraryError:
        if not root.exists() and not root.is_symlink() and not root.parent.is_symlink():
            return
        raise
    stack = [(mode_fd, "")]
    try:
        while stack:
            current_fd, prefix = stack.pop()
            try:
                scan_fd = os.dup(current_fd)
                closer = scan_fd
                try:
                    iterator = os.scandir(scan_fd)
                    closer = None
                    with iterator as entries:
                        children = list(entries)
                finally:
                    if closer is not None:
                        os.close(closer)
                for entry in children:
                    relative = f"{prefix}/{entry.name}" if prefix else entry.name
                    if entry.is_symlink():
                        yield {
                            "relative_path": relative,
                            "size_bytes": 0,
                            "mtime_ns": 0,
                            "eligible": False,
                        }
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        try:
                            stack.append((
                                os.open(entry.name, directory_flags, dir_fd=current_fd),
                                relative,
                            ))
                        except OSError:
                            continue
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    yield {
                        "relative_path": relative,
                        "size_bytes": info.st_size,
                        "mtime_ns": info.st_mtime_ns,
                        "eligible": Path(entry.name).suffix.lower() in TEXT_SUFFIXES | {".pdf"}
                        and 0 < info.st_size <= MAX_SOURCE_BYTES
                        and info.st_nlink == 1,
                    }
            finally:
                os.close(current_fd)
    finally:
        while stack:
            leftover, _prefix = stack.pop()
            os.close(leftover)


def extract_passages(payload: bytes, filename: str) -> tuple[str, list[dict], list[int]]:
    """Extract complete text, retaining offsets in each original text/page unit."""
    if not payload or len(payload) > MAX_SOURCE_BYTES:
        raise LibraryError("Choose a non-empty source no larger than 25 MB.")
    suffix = Path(filename).suffix.lower()
    units = []
    empty_pages = []
    if suffix == ".pdf":
        import fitz

        try:
            with fitz.open(stream=payload, filetype="pdf") as doc:
                if doc.needs_pass:
                    raise LibraryError("Unlock this PDF before saving it to the library.")
                if doc.page_count > MAX_PAGES:
                    raise LibraryError("PDFs must have at most 1,000 pages.")
                total = 0
                for number, page in enumerate(doc, 1):
                    text = page.get_text("text", sort=True)
                    total += len(text)
                    if total > MAX_TEXT_CHARS:
                        raise LibraryError("Extracted text must have at most 1,000,000 characters.")
                    if not text.strip():
                        empty_pages.append(number)
                    units.append((number, text))
        except (fitz.FileDataError, RuntimeError) as exc:
            raise LibraryError("This PDF could not be read.") from exc
        mime = "application/pdf"
    elif suffix in TEXT_SUFFIXES:
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise LibraryError("Text sources must use UTF-8 encoding.") from exc
        if "\x00" in text:
            raise LibraryError("This source contains binary data, not readable text.")
        if len(text) > MAX_TEXT_CHARS:
            raise LibraryError("Text sources must have at most 1,000,000 characters.")
        units = [(None, text)]
        mime = "text/plain"
    else:
        raise LibraryError("Save a PDF, UTF-8 note, Markdown, CSV, JSON, subtitle, or text log.")
    passages = []
    for page, text in units:
        start = 0
        while start < len(text):
            end = min(start + PASSAGE_CHARS, len(text))
            if end < len(text):
                newline = text.rfind("\n", start + PASSAGE_CHARS // 2, end)
                if newline < 0:
                    newline = text.rfind(" ", start + PASSAGE_CHARS // 2, end)
                if newline >= 0:
                    end = newline + 1
            excerpt = text[start:end]
            if excerpt.strip():
                passages.append(
                    {
                        "page": page,
                        "text": excerpt,
                        "char_start": start,
                        "char_end": end,
                        "line_start": text.count("\n", 0, start) + 1,
                        "line_end": text.count("\n", 0, end - 1) + 1,
                    }
                )
            if end == len(text):
                break
            # Keep boundary facts together without changing page-relative offsets.
            start = max(start + 1, end - PASSAGE_OVERLAP_CHARS)
    if not passages:
        raise LibraryError(
            "No searchable text was found. For scanned PDFs, run document_ocr and save its text output."
        )
    return mime, passages, empty_pages


class SourceLibrary:
    def __init__(self, mode=None):
        self.mode = get_active_config_mode(mode)
        root = (
            get_config_value("SOURCE_LIBRARY_DIR", "")
            or get_project_root() / "data" / "source_library"
        )
        self.path = Path(root).expanduser() / f"{self.mode}.db"

    @contextmanager
    def _store_directory(self, *, create=False):
        """Pin a private library directory before SQLite opens its pathname."""
        root = self.path.parent
        if os.name == "nt":
            # Python's Windows sqlite3 and os.open do not accept a directory
            # handle. Refuse a configured root alias and retain the path API.
            if root.is_symlink() or root.is_junction():
                raise LibraryUnavailableError("The source library directory cannot be a symlink.")
            if create:
                root.mkdir(parents=True, exist_ok=True)
            if not root.exists():
                yield None
                return
            if not root.is_dir():
                raise LibraryUnavailableError("The source library directory is unavailable.")
            yield str(root), None
            return

        if create:
            root.parent.mkdir(parents=True, exist_ok=True)
        try:
            parent_fd = os.open(os.path.realpath(root.parent), os.O_RDONLY | os.O_DIRECTORY)
        except FileNotFoundError:
            if not create:
                yield None
                return
            raise LibraryUnavailableError("The source library parent directory is unavailable.")
        try:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            try:
                root_fd = os.open(root.name, flags, dir_fd=parent_fd)
            except FileNotFoundError:
                if not create:
                    yield None
                    return
                try:
                    os.mkdir(root.name, 0o700, dir_fd=parent_fd)
                except FileExistsError:
                    pass  # Another writer created it; the no-follow open verifies it.
                root_fd = os.open(root.name, flags, dir_fd=parent_fd)
            except OSError as exc:
                raise LibraryUnavailableError("The source library directory is unsafe or unavailable.") from exc
        finally:
            os.close(parent_fd)
        try:
            info = os.fstat(root_fd)
            if info.st_uid != os.geteuid():
                raise LibraryUnavailableError("The source library directory must be owned by Jarvis.")
            if stat.S_IMODE(info.st_mode) != 0o700:
                try:
                    os.fchmod(root_fd, 0o700)
                except OSError as exc:
                    raise LibraryUnavailableError("The source library directory must be private (0700).") from exc
            # Linux SQLite can create its journal next to this pinned directory
            # even if an untrusted parent renames the directory while in use.
            location = f"/proc/self/fd/{root_fd}" if sys.platform.startswith("linux") and os.path.isdir("/proc/self/fd") else str(root)
            yield location, root_fd
        finally:
            os.close(root_fd)

    def _store_entry(self, root_fd):
        try:
            info = (os.stat(self.path.name, dir_fd=root_fd, follow_symlinks=False)
                    if root_fd is not None else os.lstat(self.path))
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise LibraryUnavailableError("The library store must be a regular, singly linked file.")
        return info

    def store_exists(self):
        """Check for a safe mode store without following a replaced root."""
        with self._store_directory() as store:
            return store is not None and self._store_entry(store[1]) is not None

    @contextmanager
    def worker_lease(self):
        """Mark one mode as owned by a live standalone worker process."""
        with self._store_directory(create=True) as store:
            location, _root_fd = store
            with index_lock(str(Path(location) / f".worker-{self.mode}.lock")):
                yield

    def worker_running(self):
        """A stale lease file is not healthy: only an active OS lock counts."""
        if os.name == "nt":
            return False  # External workers are a Docker/Linux deployment path.
        import fcntl

        with self._store_directory() as store:
            if store is None:
                return False
            _location, root_fd = store
            try:
                descriptor = os.open(
                    f".worker-{self.mode}.lock",
                    os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW,
                    dir_fd=root_fd,
                )
            except FileNotFoundError:
                return False
            except OSError as exc:
                raise LibraryUnavailableError("The library worker status is unavailable.") from exc
            try:
                info = os.fstat(descriptor)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise LibraryUnavailableError("The library worker status is unsafe.")
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError:
                    return True
                else:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                    return False
            finally:
                os.close(descriptor)

    @contextmanager
    def locked_index(self):
        """Use the same pinned store root for every index entry point."""
        with self._store_directory() as store:
            if store is None or self._store_entry(store[1]) is None:
                raise LibraryUnavailableError("This mode has no source-library database.")
            location, _root_fd = store
            with index_lock(str(Path(location) / (self.path.name + ".index.lock"))):
                yield

    @contextmanager
    def _connect(self, *, write=False):
        with ExitStack() as stack:
            store = stack.enter_context(self._store_directory(create=write))
            if store is None:
                yield None
                return
            location, root_fd = store
            info = self._store_entry(root_fd)
            if not write and info is None:
                yield None
                return
            db_path = str(Path(location) / self.path.name)
            conn = sqlite3.connect(
                db_path if write else Path(db_path).as_uri() + "?mode=ro",
                uri=not write,
                timeout=5,
            )
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA foreign_keys=ON")
                if write:
                    conn.execute("PRAGMA secure_delete=ON")
                    if root_fd is None:
                        self.path.chmod(0o600)
                    else:
                        os.chmod(self.path.name, 0o600, dir_fd=root_fd, follow_symlinks=False)
                    conn.executescript("""
                    CREATE TABLE IF NOT EXISTS sources (
                        id TEXT PRIMARY KEY, filename TEXT NOT NULL, title TEXT NOT NULL,
                        mime TEXT NOT NULL, original BLOB NOT NULL, origin TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                        empty_pages TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS passages (
                        id INTEGER PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                        number INTEGER NOT NULL, page INTEGER, text TEXT NOT NULL,
                        char_start INTEGER NOT NULL, char_end INTEGER NOT NULL,
                        line_start INTEGER NOT NULL, line_end INTEGER NOT NULL,
                        embedding TEXT, fingerprint TEXT,
                        UNIQUE(source_id, number)
                    );
                    CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(title, text);
                    CREATE TABLE IF NOT EXISTS index_jobs (
                        source_id TEXT PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
                        state TEXT NOT NULL CHECK(state IN ('pending','ready','error')),
                        error TEXT,
                        attempts INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                    );
                    CREATE TABLE IF NOT EXISTS import_jobs (
                        relative_path TEXT PRIMARY KEY, size_bytes INTEGER NOT NULL,
                        mtime_ns INTEGER NOT NULL,
                        state TEXT NOT NULL CHECK(state IN ('pending','done','error')),
                        source_id TEXT, error TEXT,
                        attempts INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                    );
                    """)
                yield conn
                if write:
                    conn.commit()
            except BaseException:
                if write:
                    conn.rollback()
                raise
            finally:
                conn.close()

    def _id(self, source_id):
        if not isinstance(source_id, str) or not _ID.fullmatch(source_id):
            raise LibraryError("Use an exact source_id returned by the library.")
        return source_id

    def _source(self, conn, source_id):
        self._id(source_id)
        row = (
            conn.execute(
                "SELECT id,filename,title,mime,origin,created_at,empty_pages,length(original) AS size_bytes FROM sources WHERE id=?",
                (source_id,),
            ).fetchone()
            if conn
            else None
        )
        if row is None:
            raise LibraryError(
                "This source is not in the selected mode's library. It may have been removed."
            )
        return row

    def _metadata(self, conn, row):
        result = dict(row)
        result["empty_pages"] = json.loads(result["empty_pages"])
        result["source_id"] = result.pop("id")
        result["mode"] = self.mode
        result["source_ref"] = f"library://{self.mode}/{result['source_id']}"
        result["url"] = f"/library?mode={self.mode}&source={result['source_id']}"
        result["download_url"] = f"/api/library/{result['source_id']}/download?mode={self.mode}"
        try:
            fingerprint = _fingerprint()
        except EmbeddingError:
            fingerprint = ""
        counts = conn.execute(
            "SELECT count(*),sum(CASE WHEN fingerprint=? AND embedding IS NOT NULL THEN 1 ELSE 0 END) FROM passages WHERE source_id=?",
            (fingerprint, result["source_id"]),
        ).fetchone()
        result["passage_count"], result["indexed_passages"] = counts[0], counts[1] or 0
        if result["mime"] == "application/pdf":
            last_text_page = conn.execute(
                "SELECT max(page) FROM passages WHERE source_id=?", (result["source_id"],)
            ).fetchone()[0] or 0
            result["page_count"] = max([last_text_page, *result["empty_pages"]])
        result["index_status"] = (
            "ready" if counts[0] == counts[1] else "partial" if counts[1] else "keyword_only"
        )
        try:
            job = conn.execute(
                "SELECT state,error FROM index_jobs WHERE source_id=?", (result["source_id"],)
            ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            job = None
        result["index_job_status"] = job["state"] if job else "unqueued"
        result["index_error"] = job["error"] if job else None
        return result

    def save(self, payload, filename, *, title=None, origin="", cancel_check=None):
        if (
            not isinstance(filename, str)
            or not filename
            or len(filename) > 200
            or Path(filename).name != filename
            or "\\" in filename
            or any(ord(c) < 32 for c in filename)
        ):
            raise LibraryError("Use a filename without directories (at most 200 characters).")
        title = title or filename
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise LibraryError("Source titles must contain 1 to 200 characters.")
        if not isinstance(origin, str) or len(origin) > 1000:
            raise LibraryError("Source origin must be at most 1,000 characters.")
        mime, passages, empty_pages = extract_passages(payload, filename)
        source_id = hashlib.sha256(payload).hexdigest()
        if cancel_check and cancel_check():
            raise LibraryError("Save cancelled before the source was stored.")
        with self._connect(write=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            exists = conn.execute("SELECT 1 FROM sources WHERE id=?", (source_id,)).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO sources(id,filename,title,mime,original,origin,empty_pages) VALUES(?,?,?,?,?,?,?)",
                    (
                        source_id,
                        filename,
                        title.strip(),
                        mime,
                        payload,
                        origin,
                        json.dumps(empty_pages),
                    ),
                )
                for number, passage in enumerate(passages, 1):
                    cursor = conn.execute(
                        "INSERT INTO passages(source_id,number,page,text,char_start,char_end,line_start,line_end) VALUES(?,?,?,?,?,?,?,?)",
                        (
                            source_id,
                            number,
                            passage["page"],
                            passage["text"],
                            passage["char_start"],
                            passage["char_end"],
                            passage["line_start"],
                            passage["line_end"],
                        ),
                    )
                    conn.execute(
                        "INSERT INTO passages_fts(rowid,title,text) VALUES(?,?,?)",
                        (cursor.lastrowid, title.strip(), passage["text"]),
                    )
                if cancel_check and cancel_check():
                    raise LibraryError("Save cancelled before the source was stored.")
            result = self._metadata(conn, self._source(conn, source_id))
            if result["index_status"] != "ready":
                conn.execute(
                    "INSERT INTO index_jobs(source_id,state,error) VALUES(?,'pending',NULL) "
                    "ON CONFLICT(source_id) DO UPDATE SET state='pending',error=NULL,"
                    "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                    (source_id,),
                )
                result["index_job_status"] = "pending"
                result["index_error"] = None
        return {**result, "duplicate": bool(exists)}

    def list(self, *, offset=0, limit=30):
        _integer(offset, "offset", 0, 1_000_000)
        _integer(limit, "limit", 1, 100)
        with self._connect() as conn:
            total = conn.execute("SELECT count(*) FROM sources").fetchone()[0] if conn else 0
            rows = (
                conn.execute(
                    "SELECT id,filename,title,mime,origin,created_at,empty_pages,length(original) AS size_bytes FROM sources ORDER BY created_at DESC,id LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
                if conn
                else []
            )
            return {
                "sources": [self._metadata(conn, row) for row in rows],
                "total": total,
                "offset": offset,
                "next_offset": offset + len(rows) if offset + len(rows) < total else None,
                "mode": self.mode,
            }

    def statuses(self, source_ids):
        """Read current metadata for a bounded set of visible source cards."""
        if not isinstance(source_ids, list) or len(source_ids) > 100:
            raise LibraryError("Request status for at most 100 exact source IDs.")
        ids = list(dict.fromkeys(self._id(source_id) for source_id in source_ids))
        if not ids:
            return {"sources": [], "mode": self.mode}
        with self._connect() as conn:
            if conn is None:
                return {"sources": [], "mode": self.mode}
            placeholders = ",".join("?" for _ in ids)
            rows = conn.execute(
                "SELECT id,filename,title,mime,origin,created_at,empty_pages,"
                f"length(original) AS size_bytes FROM sources WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
            found = {row["id"]: self._metadata(conn, row) for row in rows}
            return {"sources": [found[source_id] for source_id in ids if source_id in found], "mode": self.mode}

    @property
    def inbox_path(self):
        return self.path.parent / "inbox" / self.mode

    def ensure_inbox(self):
        """Create the mode inbox privately without following replaced directories."""
        with self._store_directory(create=True) as store:
            location, root_fd = store
            if os.name == "nt":
                current = Path(location)
                for name in ("inbox", self.mode):
                    current = current / name
                    if current.is_symlink() or current.is_junction():
                        raise LibraryUnavailableError("The source library inbox is unsafe.")
                    current.mkdir(exist_ok=True)
                    if not current.is_dir():
                        raise LibraryUnavailableError("The source library inbox is unavailable.")
                return self.inbox_path

            descriptor = os.dup(root_fd)
            try:
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                for name in ("inbox", self.mode):
                    try:
                        os.mkdir(name, 0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                    child = os.open(name, flags, dir_fd=descriptor)
                    os.close(descriptor)
                    descriptor = child
                    info = os.fstat(descriptor)
                    if info.st_uid != os.geteuid():
                        raise LibraryUnavailableError("The source library inbox must be owned by Jarvis.")
                    if stat.S_IMODE(info.st_mode) != 0o700:
                        os.fchmod(descriptor, 0o700)
            except OSError as exc:
                raise LibraryUnavailableError("The source library inbox is unsafe or unavailable.") from exc
            finally:
                os.close(descriptor)
        return self.inbox_path

    def inbox_status(self):
        """Read-only disk estimate and recent import receipts for the mode inbox."""
        root = self.inbox_path
        files = list(_iter_inbox_files(root))
        files.sort(key=lambda file: file["relative_path"])
        eligible = [file for file in files if file["eligible"]]
        disk_root = self.path.parent
        while not disk_root.exists():
            disk_root = disk_root.parent
        free = shutil.disk_usage(disk_root).free
        with self._connect() as conn:
            try:
                jobs = [dict(row) for row in conn.execute(
                    "SELECT relative_path,size_bytes,state,source_id,error,updated_at "
                    "FROM import_jobs ORDER BY updated_at DESC,relative_path LIMIT 100"
                )] if conn else []
                recorded = {
                    row["relative_path"]: (
                        row["size_bytes"], row["mtime_ns"], row["state"],
                        bool(row["present_id"]),
                    )
                    for row in conn.execute(
                        "SELECT j.relative_path,j.size_bytes,j.mtime_ns,j.state,s.id AS present_id "
                        "FROM import_jobs j LEFT JOIN sources s ON s.id=j.source_id"
                    )
                } if conn else {}
                counts = {
                    row["state"]: row["total"] for row in conn.execute(
                        "SELECT state,count(*) AS total FROM import_jobs GROUP BY state"
                    )
                } if conn else {}
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc):
                    raise
                jobs, recorded, counts = [], {}, {}
        to_queue = [file for file in eligible if recorded.get(file["relative_path"])
                    != (file["size_bytes"], file["mtime_ns"], "done", True)]
        # SQLite originals, extracted text, FTS and journals need additional
        # room; this conservative estimate is displayed before enqueueing.
        estimate = sum(file["size_bytes"] * 4 + 2 * 1024 * 1024 for file in to_queue)
        return {
            "mode": self.mode, "inbox_path": str(root),
            "file_count": len(files), "eligible_count": len(eligible),
            "queueable_count": len(to_queue),
            "skipped_count": len(files) - len(eligible),
            "estimated_disk_bytes": estimate, "free_disk_bytes": free,
            "enough_disk": free >= estimate, "job_counts": counts, "jobs": jobs,
        }

    def queue_inbox_import(self):
        """Persist a snapshot of eligible inbox files, then return immediately."""
        status = self.inbox_status()
        if not status["enough_disk"]:
            raise LibraryError("Not enough free disk space for the estimated inbox import.")
        if not status["eligible_count"]:
            return {**status, "queued": 0}
        queued = 0
        with self._connect(write=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            for file in _iter_inbox_files(self.inbox_path):
                if not file["eligible"]:
                    continue
                relative = file["relative_path"]
                existing = conn.execute(
                    "SELECT size_bytes,mtime_ns,state,source_id FROM import_jobs WHERE relative_path=?", (relative,)
                ).fetchone()
                if existing and existing["state"] == "done" and (existing["size_bytes"], existing["mtime_ns"]) == (file["size_bytes"], file["mtime_ns"]) and conn.execute(
                    "SELECT 1 FROM sources WHERE id=?", (existing["source_id"],)
                ).fetchone():
                    continue
                conn.execute(
                    "INSERT INTO import_jobs(relative_path,size_bytes,mtime_ns,state,source_id,error) "
                    "VALUES(?,?,?,'pending',NULL,NULL) ON CONFLICT(relative_path) DO UPDATE SET "
                    "size_bytes=excluded.size_bytes,mtime_ns=excluded.mtime_ns,state='pending',"
                    "source_id=NULL,error=NULL,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                    (relative, file["size_bytes"], file["mtime_ns"]),
                )
                queued += 1
        return {**self.inbox_status(), "queued": queued}

    def next_import_job(self):
        with self._connect() as conn:
            if conn is None:
                return None
            try:
                row = conn.execute(
                    "SELECT relative_path,size_bytes,mtime_ns FROM import_jobs "
                    "WHERE state='pending' ORDER BY updated_at,relative_path LIMIT 1"
                ).fetchone()
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc):
                    raise
                return None
            return dict(row) if row else None

    def import_queued_file(self, job):
        """Import one queued file; changed paths fail visibly rather than racing."""
        relative = job["relative_path"]
        root = self.inbox_path
        path = root / relative
        try:
            descriptor = _open_inbox_file(root, relative)
            with os.fdopen(descriptor, "rb") as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                    raise LibraryError("Inbox entry is not a regular file.")
                if (before.st_size, before.st_mtime_ns) != (job["size_bytes"], job["mtime_ns"]):
                    raise LibraryError("Inbox file changed after queueing; queue it again.")
                payload = stream.read(MAX_SOURCE_BYTES + 1)
                finished = os.fstat(stream.fileno())
            before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            finished_identity = (finished.st_dev, finished.st_ino, finished.st_size, finished.st_mtime_ns)
            with os.fdopen(_open_inbox_file(root, relative), "rb") as stream:
                after = os.fstat(stream.fileno())
            after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            if before_identity != finished_identity or before_identity != after_identity:
                raise LibraryError("Inbox file changed during import; queue it again.")
            saved = self.save(payload, path.name, origin=f"Inbox: {relative}")
            source_id, error = saved["source_id"], None
        except (LibraryError, OSError) as exc:
            source_id, error = None, str(exc)
        with self._connect(write=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE import_jobs SET state=?,source_id=?,error=?,attempts=attempts+1,"
                "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE relative_path=? "
                "AND size_bytes=? AND mtime_ns=? AND state='pending'",
                ("error" if error else "done", source_id, error, relative, job["size_bytes"], job["mtime_ns"]),
            )
        return {"relative_path": relative, "source_id": source_id, "error": error}

    def _passage(self, row, meta):
        return {
            **{
                key: row[key]
                for key in (
                    "number",
                    "page",
                    "text",
                    "char_start",
                    "char_end",
                    "line_start",
                    "line_end",
                )
            },
            "source_id": meta["source_id"],
            "source_ref": meta["source_ref"],
            "title": meta["title"],
            "mode": self.mode,
            "url": f"{meta['url']}&passage={row['number']}",
            "citation": f"{meta['title']} — "
            + (f"page {row['page']}, " if row["page"] else "")
            + f"lines {row['line_start']}–{row['line_end']} (passage {row['number']})",
        }

    def read(self, source_id, *, passage=1, limit=3):
        _integer(passage, "passage", 1, 1_000_000)
        _integer(limit, "limit", 1, 8)
        with self._connect() as conn:
            meta = self._metadata(conn, self._source(conn, source_id))
            if passage > meta["passage_count"]:
                raise LibraryError("That passage is outside this source.")
            rows = conn.execute(
                "SELECT * FROM passages WHERE source_id=? AND number>=? ORDER BY number LIMIT ?",
                (source_id, passage, limit),
            ).fetchall()
            end = passage + len(rows)
            return {
                "source": meta,
                "passages": [self._passage(row, meta) for row in rows],
                "next_passage": end if end <= meta["passage_count"] else None,
                "mode": self.mode,
            }

    def download(self, source_id):
        with self._connect() as conn:
            meta = dict(self._source(conn, source_id))
            payload = conn.execute(
                "SELECT original FROM sources WHERE id=?", (source_id,)
            ).fetchone()[0]
            if hashlib.sha256(payload).hexdigest() != source_id:
                raise LibraryError("The stored original failed its integrity check.")
            return payload, meta["filename"], meta["mime"]

    def original_text(self, source_id):
        """Read a retained UTF-8 original for raw and locally rendered views."""
        payload, filename, mime = self.download(source_id)
        if mime != "text/plain":
            raise LibraryError("This original is a PDF; use its page view or download it.")
        return payload.decode("utf-8-sig"), filename

    def save_edited_copy(self, source_id, text):
        """Save edited text with a new hash while retaining the cited original."""
        if not isinstance(text, str):
            raise LibraryError("Edited content must be UTF-8 text.")
        with self._connect() as conn:
            old = self._source(conn, source_id)
            if old["mime"] == "application/pdf":
                raise LibraryError("Edit an OCR or text copy instead of changing a PDF original.")
            filename, title = old["filename"], old["title"]
        return self.save(
            text.encode("utf-8"), filename, title=f"{title[:190]} (edited)",
            origin=f"Edited from library://{self.mode}/{source_id}",
        )

    def rendered_markdown(self, source_id):
        """Render Markdown without active HTML or automatically fetched assets."""
        text, filename = self.original_text(source_id)
        if Path(filename).suffix.lower() not in {".md", ".markdown"}:
            raise LibraryError("Rendered Markdown is available for Markdown sources only.")
        from markdown_it import MarkdownIt

        parser = MarkdownIt("commonmark", {"html": False, "linkify": False})
        parser.add_render_rule(
            "image",
            lambda _renderer, tokens, index, _options, _env: html.escape(
                f"[Image: {tokens[index].content}]"
            ),
        )

        def safe_link(renderer, tokens, index, options, env):
            tokens[index].attrSet("rel", "noopener noreferrer")
            tokens[index].attrSet("target", "_blank")
            return renderer.renderToken(tokens, index, options, env)

        parser.add_render_rule("link_open", safe_link)
        return parser.render(text)

    def rendered_pdf_page(self, source_id, page):
        """Render one bounded page from the verified original, never remote assets."""
        _integer(page, "page", 1, MAX_PAGES)
        payload, _filename, mime = self.download(source_id)
        if mime != "application/pdf":
            raise LibraryError("Page rendering is available for PDFs only.")
        import fitz

        try:
            with fitz.open(stream=payload, filetype="pdf") as doc:
                if page > doc.page_count:
                    raise LibraryError("That page is outside this source.")
                source_page = doc.load_page(page - 1)
                area = max(1.0, source_page.rect.width * source_page.rect.height)
                scale = min(1.6, (4_000_000 / area) ** 0.5)
                pix = source_page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                return pix.tobytes("png")
        except (fitz.FileDataError, RuntimeError) as exc:
            raise LibraryError("This PDF page could not be rendered.") from exc

    def remove(self, source_id):
        with self._connect() as conn:
            self._source(conn, source_id)
        with self._connect(write=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._source(conn, source_id)
            conn.execute(
                "DELETE FROM passages_fts WHERE rowid IN (SELECT id FROM passages WHERE source_id=?)",
                (source_id,),
            )
            conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
        return {"source_id": source_id, "removed": True, "mode": self.mode}

    def rename(self, source_id, title):
        """Rename one source without changing the identity of its original bytes.

        Document embeddings include the title, so an old vector must never be
        advertised as current after a rename. The original and passage numbers
        remain unchanged; semantic indexing can resume from the first passage.
        """
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise LibraryError("Source titles must contain 1 to 200 characters.")
        title = title.strip()
        with self._connect() as conn:
            self._source(conn, source_id)
        with self._connect(write=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self._source(conn, source_id)
            if current["title"] != title:
                conn.execute("UPDATE sources SET title=? WHERE id=?", (title, source_id))
                conn.execute(
                    "UPDATE passages_fts SET title=? WHERE rowid IN "
                    "(SELECT id FROM passages WHERE source_id=?)",
                    (title, source_id),
                )
                conn.execute(
                    "UPDATE passages SET embedding=NULL,fingerprint=NULL WHERE source_id=?",
                    (source_id,),
                )
                conn.execute(
                    "INSERT INTO index_jobs(source_id,state,error) VALUES(?,'pending',NULL) "
                    "ON CONFLICT(source_id) DO UPDATE SET state='pending',error=NULL,"
                    "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                    (source_id,),
                )
            return self._metadata(conn, self._source(conn, source_id))

    def queue_index(self, source_id):
        """Request or retry durable indexing without performing an embedding request."""
        # A bad or missing ID must not create an otherwise empty library store.
        with self._connect() as conn:
            self._source(conn, source_id)
        with self._connect(write=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            meta = self._metadata(conn, self._source(conn, source_id))
            state = "ready" if meta["index_status"] == "ready" else "pending"
            conn.execute(
                "INSERT INTO index_jobs(source_id,state,error) VALUES(?,?,NULL) "
                "ON CONFLICT(source_id) DO UPDATE SET state=excluded.state,error=NULL,"
                "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                (source_id, state),
            )
            meta["index_job_status"] = state
            meta["index_error"] = None
            return {"source": meta, "queued": state == "pending"}

    def next_index_job(self):
        """Return a pending source, without creating a database on a read."""
        with self._connect() as conn:
            if conn is None:
                return None
            try:
                row = conn.execute(
                    "SELECT source_id FROM index_jobs WHERE state='pending' "
                    "ORDER BY updated_at,source_id LIMIT 1"
                ).fetchone()
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc):
                    raise
                return None
            return row["source_id"] if row else None

    def record_index_progress(self, source_id, *, remaining, error=None, expected_title=None):
        """Persist one batch outcome; a stopped worker can resume pending work."""
        with self._connect(write=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self._source(conn, source_id)
            if expected_title is not None and current["title"] != expected_title:
                # A concurrent rename queued fresh embeddings. Do not overwrite
                # that pending state with the outcome of the old title's batch.
                return self._metadata(conn, current)
            state = "error" if error else "pending" if remaining else "ready"
            conn.execute(
                "UPDATE index_jobs SET state=?,error=?,attempts=attempts+1,"
                "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE source_id=?",
                (state, error, source_id),
            )
            return self._metadata(conn, self._source(conn, source_id))

    def index(self, source_id, *, cancel_check=None):
        """Index one bounded batch; existing batches survive interruption/restart."""
        with self._connect() as conn:
            meta = self._metadata(conn, self._source(conn, source_id))
            try:
                fingerprint = _fingerprint()
            except EmbeddingError:
                return {
                    "source": meta,
                    "remaining": meta["passage_count"],
                    "index_error": "Embedding configuration is incompatible. Saved text remains searchable by keywords.",
                }
            rows = conn.execute(
                "SELECT id,text FROM passages WHERE source_id=? AND (embedding IS NULL OR fingerprint IS NULL OR fingerprint!=?) ORDER BY number LIMIT ?",
                (source_id, fingerprint, INDEX_BATCH_SIZE),
            ).fetchall()
        if not rows:
            return {"source": meta, "remaining": 0}
        if cancel_check and cancel_check():
            raise LibraryError(
                "Indexing cancelled. The original and completed batches are still saved."
            )
        try:
            vectors = get_embeddings_batch(
                [row["text"] for row in rows], role="document", titles=[meta["title"]] * len(rows)
            )
            if len(vectors) != len(rows):
                raise EmbeddingError("Embedding batch count did not match the passages.")
            vectors = [_vector(vector) for vector in vectors]
        except (EmbeddingError, OSError, ValueError) as exc:
            return {
                "source": meta,
                "remaining": meta["passage_count"] - meta["indexed_passages"],
                "index_error": "Embedding service unavailable or incompatible. Saved text remains searchable by keywords.",
                "error_type": type(exc).__name__,
            }
        if cancel_check and cancel_check():
            raise LibraryError(
                "Indexing cancelled. The original and completed batches are still saved."
            )
        with self._connect(write=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self._source(
                conn, source_id
            )  # Never resurrect a concurrently removed source.
            if current["created_at"] != meta["created_at"] or current["title"] != meta["title"]:
                raise LibraryError(
                    "This source was replaced during indexing. Retry for the current source."
                )
            import numpy as np

            for row, vector in zip(rows, vectors):
                conn.execute(
                    "UPDATE passages SET embedding=?,fingerprint=? WHERE id=? AND source_id=? AND text=?",
                    (np.asarray(vector, dtype="<f4").tobytes(), fingerprint, row["id"], source_id, row["text"]),
                )
            meta = self._metadata(conn, self._source(conn, source_id))
        return {"source": meta, "remaining": meta["passage_count"] - meta["indexed_passages"]}

    def search(self, query, *, source_id=None, limit=6, semantic=True):
        if not isinstance(query, str) or not query.strip() or len(query) > 1000:
            raise LibraryError("Search text must contain 1 to 1,000 characters.")
        _integer(limit, "limit", 1, 8)
        if type(semantic) is not bool:
            raise LibraryError("semantic must be true or false.")
        words = list(dict.fromkeys(re.findall(r"\w+", query.lower(), re.UNICODE)))
        terms = [word for word in words if word not in _STOP_WORDS] or words
        expression = fts5_query(terms[:40])
        with self._connect() as conn:
            if source_id is not None:
                self._source(conn, source_id)
            total = conn.execute("SELECT count(*) FROM sources").fetchone()[0] if conn else 0
            if not total:
                return {
                    "passages": [],
                    "retrieval_mode": "empty",
                    "source_count": 0,
                    "mode": self.mode,
                }
            clause = " AND p.source_id=?" if source_id else ""
            args = [source_id] if source_id else []
            lexical = (
                conn.execute(
                    "SELECT p.*, "
                    "highlight(passages_fts,0,char(1),char(2)) != passages_fts.title AS title_hit, "
                    "highlight(passages_fts,1,char(1),char(2)) != passages_fts.text AS text_hit "
                    "FROM passages_fts JOIN passages p ON p.id=passages_fts.rowid WHERE passages_fts MATCH ?"
                    + clause
                    + " ORDER BY bm25(passages_fts,2,1),p.id LIMIT 60",
                    [expression, *args],
                ).fetchall()
                if expression
                else []
            )
            dense = []
            reason = None
            indexed_count = 0
            passage_count = conn.execute(
                "SELECT count(*) FROM passages p WHERE 1=1" + clause, args
            ).fetchone()[0]
            if semantic:
                try:
                    fingerprint = _fingerprint()
                    available = conn.execute(
                        "SELECT count(*) FROM passages p WHERE fingerprint=?" + clause,
                        [fingerprint, *args],
                    ).fetchone()[0]
                    indexed_count = available
                    if available:
                        import numpy as np

                        query_vector = np.asarray(_vector(get_embedding(query, role="query")), dtype=np.float64)
                        query_norm = np.linalg.norm(query_vector)
                        batch = []

                        def score_batch(rows):
                            vectors = np.asarray([
                                np.frombuffer(value, dtype="<f4").astype(np.float64)
                                if isinstance(value := row["embedding"], bytes) else json.loads(value)
                                for row in rows
                            ], dtype=np.float64)
                            if vectors.shape != (len(rows), EMBEDDING_DIMENSIONS) or not np.isfinite(vectors).all():
                                raise ValueError("Stored source embedding is malformed.")
                            norms = np.linalg.norm(vectors, axis=1) * query_norm
                            scores = np.divide(
                                np.einsum("ij,j->i", vectors, query_vector), norms,
                                out=np.zeros(len(rows), dtype=np.float64), where=norms != 0,
                            )
                            dense.extend((float(score), row) for score, row in zip(scores, rows) if score >= 0.3)

                        for row in conn.execute(
                            "SELECT p.id,p.embedding FROM passages p WHERE fingerprint=?" + clause,
                            [fingerprint, *args],
                        ):
                            batch.append(row)
                            if len(batch) == 256:
                                score_batch(batch)
                                batch = []
                        if batch:
                            score_batch(batch)
                        dense.sort(key=lambda item: (-item[0], item[1]["id"]))
                        dense = dense[:60]
                    else:
                        reason = (
                            "No compatible meaning index yet; showing keyword results."
                        )
                except (EmbeddingError, OSError, ValueError) as exc:
                    reason = f"Semantic search unavailable ({type(exc).__name__}); showing keyword matches."
                    dense = []
            lexical_reasons = {
                row["id"]: [
                    reason for reason, present in (("text", row["text_hit"]), ("title", row["title_hit"]))
                    if present
                ]
                for row in lexical
            }
            scores, matches, found = {}, {}, {}
            for kind, ranking in (("keyword", lexical), ("semantic", [row for _, row in dense])):
                for rank, row in enumerate(ranking, 1):
                    key = row["id"]
                    scores[key] = scores.get(key, 0) + reciprocal_rank_score(rank)
                    matches.setdefault(key, []).append(kind)
                    found[key] = row
            passages, metadata = [], {}
            for key in sorted(scores, key=lambda key: (-scores[key], key))[:limit]:
                row = found[key]
                if "text" not in row.keys():
                    row = conn.execute("SELECT p.* FROM passages p WHERE id=?", (key,)).fetchone()
                sid = row["source_id"]
                if sid not in metadata:
                    metadata[sid] = self._metadata(conn, self._source(conn, sid))
                reasons = list(lexical_reasons.get(key, []))
                if "semantic" in matches[key]:
                    reasons.append("semantic")
                passages.append({
                    **self._passage(row, metadata[sid]),
                    "matched_by": matches[key],
                    "match_reasons": reasons,
                })
            return {
                "passages": passages,
                "sources": list(metadata.values()),
                "query": query,
                "retrieval_mode": "hybrid" if semantic and not reason else "keyword",
                "semantic_unavailable_reason": reason,
                "source_count": total,
                "mode": self.mode,
                "total_passages": passage_count,
                "semantic_indexed_passages": indexed_count,
                "semantic_coverage_incomplete": semantic and indexed_count < passage_count,
            }
