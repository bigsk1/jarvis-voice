"""Verified, non-overwriting backup and disaster restore for mode libraries."""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

from source_library import LibraryError, SourceLibrary


def _existing_parent(path: Path) -> Path:
    parent = path.parent
    while not parent.exists():
        parent = parent.parent
    return parent


def verify_database(path: Path) -> dict:
    """Check database structure and original-byte hashes, without modifying it."""
    path = Path(path).expanduser()
    if not path.is_file() or path.is_symlink():
        raise LibraryError("Choose a regular source-library database file.")
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
            result = conn.execute("PRAGMA integrity_check").fetchone()
            if result is None or result[0] != "ok":
                raise LibraryError("The source-library database failed SQLite integrity_check.")
            if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise LibraryError("The source-library database has broken source references.")
            passage_count = conn.execute("SELECT count(*) FROM passages").fetchone()[0]
            fts_count = conn.execute("SELECT count(*) FROM passages_fts").fetchone()[0]
            if passage_count != fts_count:
                raise LibraryError("The source-library full-text index does not match its passages.")
            count, original_bytes = 0, 0
            for source_id, original in conn.execute("SELECT id,original FROM sources"):
                if hashlib.sha256(original).hexdigest() != source_id:
                    raise LibraryError(f"Stored original failed SHA-256 verification: {source_id}")
                count += 1
                original_bytes += len(original)
    except sqlite3.DatabaseError as exc:
        raise LibraryError("This is not a healthy source-library database.") from exc
    return {
        "sources": count, "passages": passage_count,
        "original_bytes": original_bytes, "database_bytes": path.stat().st_size,
    }


def _private_temp(parent: Path) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=".source-library-", suffix=".db", dir=parent)
    os.close(descriptor)
    return Path(name)


def backup_database(library: SourceLibrary, destination: Path) -> dict:
    """Create a consistent SQLite snapshot; never overwrite an existing backup."""
    destination = Path(destination).expanduser().absolute()
    if not library.store_exists():
        raise LibraryError("This mode has no source-library database to back up.")
    if destination.exists() or destination.is_symlink():
        raise LibraryError("Backup destination already exists; choose a new path.")
    if destination == library.path.absolute():
        raise LibraryError("A backup must not replace the active library.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = _private_temp(destination.parent)
    try:
        with library._connect() as source:
            if source is None:
                raise LibraryError("This mode has no source-library database to back up.")
            with sqlite3.connect(temporary) as snapshot:
                source.backup(snapshot)
        report = verify_database(temporary)
        os.link(temporary, destination)  # O_EXCL-style publication; never overwrite.
        return {**report, "backup": str(destination), "mode": library.mode}
    finally:
        temporary.unlink(missing_ok=True)


def restore_database(library: SourceLibrary, backup: Path, *, apply=False) -> dict:
    """Verify and restore into a missing mode store; default is a dry run."""
    backup = Path(backup).expanduser().absolute()
    report = verify_database(backup)
    if library.store_exists():
        raise LibraryError("The target mode already has a library; restore will not overwrite it.")
    required = report["database_bytes"] * 2 + 16 * 1024 * 1024
    free = shutil.disk_usage(_existing_parent(library.path)).free
    result = {
        **report, "mode": library.mode, "target": str(library.path),
        "required_disk_bytes": required, "free_disk_bytes": free,
        "enough_disk": free >= required, "restored": False,
    }
    if not result["enough_disk"]:
        raise LibraryError("Not enough free disk for the verified library restore.")
    if not apply:
        return result
    with library._store_directory(create=True) as store:
        location, root_fd = store
        if library._store_entry(root_fd) is not None:
            raise LibraryError("The target mode already has a library; restore will not overwrite it.")
        temporary = _private_temp(Path(location))
        try:
            with sqlite3.connect(backup.resolve().as_uri() + "?mode=ro", uri=True) as source:
                with sqlite3.connect(temporary) as target:
                    source.backup(target)
            verify_database(temporary)
            if root_fd is None:
                os.link(temporary, library.path)
            else:
                os.link(temporary, library.path.name, dst_dir_fd=root_fd)
            result["restored"] = True
            return result
        finally:
            temporary.unlink(missing_ok=True)
