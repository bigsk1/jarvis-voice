"""Regression coverage for fallback-safe persistent embedding writes."""

import pickle
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from embeddings import PersistentEmbeddingError
from memory_db import MemoryDB, _tool_definition_content_hash


def test_tool_upsert_preserves_previous_row_when_embedding_fails(tmp_path):
    db = MemoryDB(str(tmp_path / "jarvis_memory.db"))
    old_embedding = pickle.dumps([1.0, 0.0, 0.0])
    old_hash = _tool_definition_content_hash("weather", "Old description", "{}", True)
    db.conn.execute(
        """
        INSERT INTO tool_definitions (
            name, description, schema_json, embedding, enabled, embedding_input_hash
        ) VALUES (?, ?, ?, ?, 1, ?)
        """,
        ("weather", "Old description", "{}", old_embedding, old_hash),
    )
    db.conn.commit()

    try:
        with patch("embeddings.get_embedding", side_effect=RuntimeError("provider unavailable")):
            with pytest.raises(PersistentEmbeddingError):
                db.upsert_tool("weather", "New description", "{}")

        row = db.conn.execute(
            "SELECT description, embedding, embedding_input_hash FROM tool_definitions WHERE name = ?",
            ("weather",),
        ).fetchone()
        assert row["description"] == "Old description"
        assert row["embedding"] == old_embedding
        assert row["embedding_input_hash"] == old_hash
    finally:
        db.close()


def test_remember_update_preserves_previous_embedding_when_generation_fails(tmp_path):
    db = MemoryDB(str(tmp_path / "jarvis_memory.db"))
    try:
        with patch("embeddings.get_embedding", return_value=[1.0, 0.0, 0.0]):
            memory_id = db.remember("personal", "user_birthday", "January 1st")

        original = db.conn.execute(
            "SELECT embedding FROM knowledge_base WHERE id = ?",
            (memory_id,),
        ).fetchone()["embedding"]

        with patch("embeddings.get_embedding", side_effect=RuntimeError("provider unavailable")):
            updated_id = db.remember("personal", "user_birthday", "January 2nd")

        row = db.conn.execute(
            "SELECT value, embedding FROM knowledge_base WHERE id = ?",
            (memory_id,),
        ).fetchone()
        assert updated_id == memory_id
        assert row["value"] == "January 2nd"
        assert row["embedding"] == original
    finally:
        db.close()
