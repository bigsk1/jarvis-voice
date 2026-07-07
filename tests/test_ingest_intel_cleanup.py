"""Regression coverage for cleaning up the final deleted Intel file."""

import json
import sys
from unittest.mock import patch

from lib.memory_db import MemoryDB
from skills import ingest_intel


def _run_ingest_from_tmp_project(tmp_path, db, monkeypatch):
    monkeypatch.setattr(
        ingest_intel,
        "__file__",
        str(tmp_path / "skills" / "ingest_intel.py"),
    )
    monkeypatch.setattr(ingest_intel, "MemoryDB", lambda: db)
    monkeypatch.setattr(sys, "argv", ["ingest_intel.py", "--sync"])
    with patch("embeddings.get_embedding", return_value=[1.0, 0.0, 0.0]):
        return ingest_intel.main()


def test_empty_intel_folder_removes_stale_facts_and_hash(tmp_path, monkeypatch, capsys):
    intel_dir = tmp_path / "jarvis-intel"
    intel_dir.mkdir()
    (tmp_path / "skills").mkdir()

    db = MemoryDB(str(tmp_path / "memory.db"))
    try:
        fact_id = db.remember(
            "fact",
            "Only Intel File content",
            "staleinteluniqueterm",
            source="intel/only-file.md",
            generate_embedding=False,
        )
        db.remember(
            "system",
            "intel_hash_only-file.md",
            "old-hash",
            generate_embedding=False,
        )

        assert _run_ingest_from_tmp_project(tmp_path, db, monkeypatch) == 0
        payload = json.loads(capsys.readouterr().out)

        assert payload["ok"] is True
        assert payload["data"]["deleted_files"] == 1
        assert payload["data"]["deleted_facts"] == 1
        assert "Cleaned up 1 deleted file" in payload["speech"]
        assert db.conn.execute(
            "SELECT 1 FROM knowledge_base WHERE id = ?", (fact_id,)
        ).fetchone() is None
        assert db.conn.execute(
            "SELECT 1 FROM knowledge_base WHERE key = 'intel_hash_only-file.md'"
        ).fetchone() is None
        assert db.conn.execute(
            "SELECT rowid FROM knowledge_base_fts WHERE knowledge_base_fts MATCH ?",
            ("staleinteluniqueterm",),
        ).fetchall() == []
        db.conn.execute(
            "INSERT INTO knowledge_base_fts(knowledge_base_fts, rank) "
            "VALUES('integrity-check', 1)"
        )
    finally:
        db.close()


def test_overlapping_fact_keys_remain_owned_by_each_intel_file(tmp_path, monkeypatch, capsys):
    intel_dir = tmp_path / "jarvis-intel"
    intel_dir.mkdir()
    (tmp_path / "skills").mkdir()
    first_file = intel_dir / "site_a.md"
    second_file = intel_dir / "site_b.md"
    first_file.write_text("## Servers\nIP: 10.0.0.1\n", encoding="utf-8")
    second_file.write_text("## Servers\nIP: 192.168.1.1\n", encoding="utf-8")

    db = MemoryDB(str(tmp_path / "memory.db"))
    try:
        assert _run_ingest_from_tmp_project(tmp_path, db, monkeypatch) == 0
        capsys.readouterr()
        rows = db.conn.execute(
            """
            SELECT value, source FROM knowledge_base
            WHERE category = 'network' AND key = 'Servers - IP'
            ORDER BY source
            """
        ).fetchall()
        assert [(row["source"], row["value"]) for row in rows] == [
            ("intel/site_a.md", "10.0.0.1 (source: intel/site_a.md)"),
            ("intel/site_b.md", "192.168.1.1 (source: intel/site_b.md)"),
        ]

        second_file.unlink()
        assert _run_ingest_from_tmp_project(tmp_path, db, monkeypatch) == 0
        capsys.readouterr()
        survivor = db.conn.execute(
            """
            SELECT value, source FROM knowledge_base
            WHERE category = 'network' AND key = 'Servers - IP'
            """
        ).fetchall()
        assert [(row["source"], row["value"]) for row in survivor] == [
            ("intel/site_a.md", "10.0.0.1 (source: intel/site_a.md)"),
        ]
    finally:
        db.close()


def test_unchanged_hash_self_repairs_legacy_cross_file_collision(tmp_path, monkeypatch, capsys):
    intel_dir = tmp_path / "jarvis-intel"
    intel_dir.mkdir()
    (tmp_path / "skills").mkdir()
    first_file = intel_dir / "site_a.md"
    second_file = intel_dir / "site_b.md"
    first_file.write_text("## Servers\nIP: 10.0.0.1\n", encoding="utf-8")
    second_file.write_text("## Servers\nIP: 192.168.1.1\n", encoding="utf-8")

    db = MemoryDB(str(tmp_path / "legacy.db"))
    try:
        # Reproduce the old global category/key identity: site_b overwrites
        # site_a and both file hashes still claim ingestion is current.
        db.remember(
            "network", "Servers - IP", "10.0.0.1", source="intel/site_a.md",
            generate_embedding=False,
        )
        db.remember(
            "network", "Servers - IP", "192.168.1.1", source="intel/site_b.md",
            generate_embedding=False,
        )
        for filepath in (first_file, second_file):
            db.remember(
                "system",
                f"intel_hash_{filepath.name}",
                ingest_intel.get_file_hash(filepath),
                generate_embedding=False,
            )

        assert _run_ingest_from_tmp_project(tmp_path, db, monkeypatch) == 0
        capsys.readouterr()
        rows = db.conn.execute(
            """
            SELECT source FROM knowledge_base
            WHERE category = 'network' AND key = 'Servers - IP'
            ORDER BY source
            """
        ).fetchall()
        assert [row["source"] for row in rows] == [
            "intel/site_a.md",
            "intel/site_b.md",
        ]
    finally:
        db.close()
