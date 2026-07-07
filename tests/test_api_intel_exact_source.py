"""Regression coverage for exact Intel source identity in FastAPI routes."""

import asyncio
from unittest.mock import patch

from api.models.intel import IntelUpdate
from api.routes import intel as intel_routes
from lib.memory_db import MemoryDB


def _seed_similar_intel_files(tmp_path):
    intel_dir = tmp_path / "jarvis-intel"
    intel_dir.mkdir()
    target = intel_dir / "my_notes.md"
    neighbor = intel_dir / "my1notes.md"
    target.write_text("target", encoding="utf-8")
    neighbor.write_text("neighbor", encoding="utf-8")

    db = MemoryDB(str(tmp_path / "memory.db"))
    for filename, value in ((target.name, "target fact"), (neighbor.name, "neighbor fact")):
        db.remember(
            "fact",
            f"{filename} fact",
            value,
            source=f"intel/{filename}",
            generate_embedding=False,
            dedupe_by_source=True,
        )
        db.remember(
            "system",
            f"intel_hash_{filename}",
            f"hash-{filename}",
            generate_embedding=False,
        )
    return intel_dir, target, neighbor, db


def test_file_info_treats_underscore_as_literal(tmp_path):
    _intel_dir, target, _neighbor, db = _seed_similar_intel_files(tmp_path)
    try:
        info = intel_routes.get_file_info(target, db)
        assert info.ingested is True
        assert info.fact_count == 1
    finally:
        db.close()


def test_delete_removes_only_exact_source_and_current_hash(tmp_path, monkeypatch):
    intel_dir, target, neighbor, db = _seed_similar_intel_files(tmp_path)
    monkeypatch.setattr(intel_routes, "INTEL_DIR", intel_dir)
    monkeypatch.setattr(intel_routes, "get_db", lambda: db)
    try:
        response = asyncio.run(intel_routes.delete_intel_file(target.name))

        assert "1 associated facts" in response.message
        assert not target.exists()
        assert neighbor.exists()
        assert db.conn.execute(
            "SELECT COUNT(*) FROM knowledge_base WHERE source = ?",
            (f"intel/{neighbor.name}",),
        ).fetchone()[0] == 1
        assert db.conn.execute(
            "SELECT COUNT(*) FROM knowledge_base WHERE key = ?",
            (f"intel_hash_{target.name}",),
        ).fetchone()[0] == 0
        assert db.conn.execute(
            "SELECT COUNT(*) FROM knowledge_base WHERE key = ?",
            (f"intel_hash_{neighbor.name}",),
        ).fetchone()[0] == 1
    finally:
        db.close()


def test_auto_ingest_update_invalidates_only_exact_source(tmp_path, monkeypatch):
    intel_dir, target, neighbor, db = _seed_similar_intel_files(tmp_path)
    monkeypatch.setattr(intel_routes, "INTEL_DIR", intel_dir)
    monkeypatch.setattr(intel_routes, "get_db", lambda: db)
    try:
        with patch.object(intel_routes.subprocess, "Popen"):
            asyncio.run(
                intel_routes.update_intel_file(
                    target.name,
                    IntelUpdate(content="updated", auto_ingest=True),
                )
            )

        assert db.conn.execute(
            "SELECT COUNT(*) FROM knowledge_base WHERE source = ?",
            (f"intel/{target.name}",),
        ).fetchone()[0] == 0
        assert db.conn.execute(
            "SELECT COUNT(*) FROM knowledge_base WHERE source = ?",
            (f"intel/{neighbor.name}",),
        ).fetchone()[0] == 1
        assert db.conn.execute(
            "SELECT COUNT(*) FROM knowledge_base WHERE key = ?",
            (f"intel_hash_{target.name}",),
        ).fetchone()[0] == 0
        assert db.conn.execute(
            "SELECT COUNT(*) FROM knowledge_base WHERE key = ?",
            (f"intel_hash_{neighbor.name}",),
        ).fetchone()[0] == 1
    finally:
        db.close()
