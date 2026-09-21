"""Backups preserve original hashes and restore without overwriting a library."""

import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from source_library import LibraryError, SourceLibrary
from source_library_archive import backup_database, restore_database, verify_database


def test_verified_backup_and_explicit_restore_to_missing_store(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_OVERRIDE_SOURCE_LIBRARY_DIR", str(tmp_path / "active"))
    active = SourceLibrary("local")
    original = b"Archive rescue plan\nCedar checkpoint"
    sid = active.save(original, "plan.txt")["source_id"]
    backup = tmp_path / "private" / "library-copy.db"
    report = backup_database(active, backup)
    assert report["sources"] == 1 and report["passages"] == 1
    assert verify_database(backup)["original_bytes"] == len(original)
    with pytest.raises(LibraryError, match="already exists"):
        backup_database(active, backup)

    monkeypatch.setenv("JARVIS_OVERRIDE_SOURCE_LIBRARY_DIR", str(tmp_path / "recovered"))
    recovered = SourceLibrary("local")
    preview = restore_database(recovered, backup)
    assert preview["enough_disk"] and not preview["restored"]
    assert not recovered.path.exists(), "Default restore is a dry run."
    assert restore_database(recovered, backup, apply=True)["restored"]
    assert recovered.download(sid)[0] == original
    assert recovered.search("Cedar", semantic=False)["passages"][0]["source_id"] == sid
    with pytest.raises(LibraryError, match="will not overwrite"):
        restore_database(recovered, backup, apply=True)


def test_sha_mismatch_rejects_backup_before_restore(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_OVERRIDE_SOURCE_LIBRARY_DIR", str(tmp_path / "active"))
    active = SourceLibrary("cloud")
    sid = active.save(b"Trustworthy original", "note.txt")["source_id"]
    with sqlite3.connect(active.path) as conn:
        conn.execute("UPDATE sources SET original=? WHERE id=?", (b"tampered", sid))
    with pytest.raises(LibraryError, match="SHA-256"):
        backup_database(active, tmp_path / "should-not-publish.db")
    assert not (tmp_path / "should-not-publish.db").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX no-follow directory handles")
def test_backup_and_restore_reject_symlinked_library_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_OVERRIDE_SOURCE_LIBRARY_DIR", str(tmp_path / "library"))
    active = SourceLibrary("local")
    active.save(b"Private archive note", "note.txt")
    backup = tmp_path / "verified.db"
    backup_database(active, backup)

    root = active.path.parent
    root.rename(tmp_path / "original-library")
    outside = tmp_path / "outside"
    outside.mkdir()
    root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(LibraryError, match="directory"):
        backup_database(active, tmp_path / "must-not-publish.db")
    with pytest.raises(LibraryError, match="directory"):
        restore_database(active, backup)
    assert not (outside / "local.db").exists()
