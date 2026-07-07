"""Regression coverage for cleaning up the final deleted Intel file."""

import json
import sys

from lib.memory_db import MemoryDB
from skills import ingest_intel


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

        monkeypatch.setattr(
            ingest_intel,
            "__file__",
            str(tmp_path / "skills" / "ingest_intel.py"),
        )
        monkeypatch.setattr(ingest_intel, "MemoryDB", lambda: db)
        monkeypatch.setattr(sys, "argv", ["ingest_intel.py", "--sync"])

        assert ingest_intel.main() == 0
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
