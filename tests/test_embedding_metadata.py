"""Fail-closed fingerprint and rebuild regression coverage."""

import importlib.machinery
import importlib.util
import pickle
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from embedding_metadata import (
    INTELLIGENCE_CONTEXT_NAMESPACE,
    INTELLIGENCE_INSIGHT_NAMESPACE,
    INTELLIGENCE_OUTCOME_NAMESPACE,
    INTELLIGENCE_PATTERN_NAMESPACE,
    INTELLIGENCE_QUERY_NAMESPACE,
    MEMORY_KNOWLEDGE_NAMESPACE,
    MEMORY_TOOLS_NAMESPACE,
    EmbeddingCompatibilityError,
    embedding_namespace_status,
    ensure_embedding_metadata_table,
    read_embedding_metadata,
    record_embedding_namespace_complete,
    require_embedding_namespace,
    start_embedding_namespace_rebuild,
)
from embeddings import EMBEDDING_DIMENSIONS
from intelligence import IntelligenceLayer
from memory_db import MemoryDB


def _load_rebuild_module():
    path = ROOT / "bin" / "rebuild-embeddings"
    loader = importlib.machinery.SourceFileLoader("rebuild_embeddings_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _load_health_module():
    path = ROOT / "bin" / "check-embeddings-health.py"
    loader = importlib.machinery.SourceFileLoader("embedding_health_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_runtime_only_health_does_not_require_a_database():
    module = _load_health_module()
    runtime = {
        "ok": True,
        "model": "bigsk1/jarvis-embedding:bf16-v1",
        "model_digest": "a" * 64,
        "compatible_hosts": ["http://ollama.test:11434"],
        "unavailable_hosts": [],
        "missing_model_hosts": [],
        "error": None,
    }
    with patch.object(module, "get_embedding_runtime_status", return_value=runtime):
        report = module.check_embedding_runtime("cloud")

    assert report["ok"] is True
    assert report["runtime_only"] is True
    assert report["runtime"] == runtime
    assert "db_path" not in report


def test_fresh_databases_create_empty_embedding_metadata_namespaces(tmp_path):
    memory = MemoryDB(str(tmp_path / "jarvis_memory.db"))
    intelligence = IntelligenceLayer(
        str(tmp_path / "jarvis_intelligence.db"),
        load_runtime_config=False,
    )
    try:
        databases = (
            (
                memory.conn,
                (MEMORY_KNOWLEDGE_NAMESPACE, MEMORY_TOOLS_NAMESPACE),
            ),
            (
                intelligence.conn,
                (
                    INTELLIGENCE_QUERY_NAMESPACE,
                    INTELLIGENCE_CONTEXT_NAMESPACE,
                    INTELLIGENCE_OUTCOME_NAMESPACE,
                    INTELLIGENCE_INSIGHT_NAMESPACE,
                    INTELLIGENCE_PATTERN_NAMESPACE,
                ),
            ),
        )
        for conn, namespaces in databases:
            assert conn.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'embedding_metadata'"
            ).fetchone()
            assert conn.execute(
                "SELECT COUNT(*) FROM embedding_metadata"
            ).fetchone()[0] == 0
            for namespace in namespaces:
                status = embedding_namespace_status(
                    conn,
                    namespace,
                    vector_count=0,
                )
                assert status["ok"] is True
                assert status["status"] == "empty"
    finally:
        memory.close()
        intelligence.close()


def test_untracked_vectors_are_incompatible_but_empty_namespace_can_initialize(tmp_path):
    conn = sqlite3.connect(tmp_path / "vectors.db")
    ensure_embedding_metadata_table(conn)
    status = embedding_namespace_status(
        conn,
        MEMORY_KNOWLEDGE_NAMESPACE,
        vector_count=0,
    )
    assert status["ok"] is True
    assert status["status"] == "empty"

    with pytest.raises(EmbeddingCompatibilityError, match="legacy or untracked"):
        require_embedding_namespace(
            conn,
            MEMORY_KNOWLEDGE_NAMESPACE,
            vector_count=1,
        )
    conn.close()


def test_complete_metadata_contains_full_namespace_fingerprint(tmp_path):
    conn = sqlite3.connect(tmp_path / "vectors.db")
    ensure_embedding_metadata_table(conn)
    record_embedding_namespace_complete(conn, MEMORY_KNOWLEDGE_NAMESPACE)
    conn.commit()
    stored = read_embedding_metadata(conn, MEMORY_KNOWLEDGE_NAMESPACE)
    assert stored["provider"] == "ollama"
    assert stored["model_family"] == "embeddinggemma"
    assert stored["dimensions"] == 768
    assert stored["prompt_role"] == "document"
    assert stored["input_format"] == "memory-title-key-text-value-v1"
    assert len(stored["model_digest"]) == 64
    assert embedding_namespace_status(
        conn,
        MEMORY_KNOWLEDGE_NAMESPACE,
        vector_count=1,
    )["ok"] is True
    conn.close()


def test_rebuilding_namespace_is_fail_closed(tmp_path):
    conn = sqlite3.connect(tmp_path / "vectors.db")
    ensure_embedding_metadata_table(conn)
    assert start_embedding_namespace_rebuild(
        conn,
        MEMORY_KNOWLEDGE_NAMESPACE,
    ) == 0
    conn.commit()
    with pytest.raises(EmbeddingCompatibilityError, match="rebuild is incomplete"):
        require_embedding_namespace(
            conn,
            MEMORY_KNOWLEDGE_NAMESPACE,
            vector_count=2,
        )
    conn.close()


def test_memory_semantic_search_uses_fts_when_fingerprint_is_missing(tmp_path):
    db = MemoryDB(str(tmp_path / "memory.db"))
    db.conn.execute(
        "INSERT INTO knowledge_base (category, key, value, embedding) VALUES (?, ?, ?, ?)",
        ("fact", "red planet", "Mars", pickle.dumps([1.0] * EMBEDDING_DIMENSIONS)),
    )
    db.conn.commit()
    try:
        with patch("embeddings.get_embedding") as get_embedding:
            results = db.semantic_search("red planet", limit=3)
        get_embedding.assert_not_called()
        assert results
        assert db.last_semantic_search_meta["retrieval_mode"] == "keyword_fallback"
        assert db.last_semantic_search_meta["semantic_disabled_reason"]
    finally:
        db.close()


def test_memory_rebuild_batches_and_records_complete_fingerprints(tmp_path):
    module = _load_rebuild_module()
    db_path = tmp_path / "memory.db"
    db = MemoryDB(str(db_path))
    db.remember("fact", "one", "first", generate_embedding=False)
    db.remember("fact", "two", "second", generate_embedding=False)
    db.conn.execute(
        "INSERT INTO tool_definitions (name, description, schema_json) VALUES (?, ?, ?)",
        ("weather", "Get the forecast", "{}"),
    )
    db.conn.commit()
    db.close()

    vector = [0.25] * EMBEDDING_DIMENSIONS
    with (
        patch.object(module, "get_embeddings_batch", side_effect=lambda texts, **kwargs: [vector] * len(texts)),
        patch.object(module, "_backup_database", return_value=tmp_path / "backup.db"),
    ):
        rebuilt = module._rebuild_memory(db_path, batch_size=1, force=False)
    assert rebuilt == 3

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM knowledge_base WHERE embedding IS NOT NULL"
        ).fetchone()[0] == 2
        assert read_embedding_metadata(
            conn,
            MEMORY_KNOWLEDGE_NAMESPACE,
        )["state"] == "complete"
    finally:
        conn.close()

    # A current fingerprint must not hide a later missing vector. The default
    # maintenance command repairs the namespace without requiring --force.
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE knowledge_base SET embedding = NULL WHERE key = 'one'")
    conn.commit()
    conn.close()
    with (
        patch.object(module, "get_embeddings_batch", side_effect=lambda texts, **kwargs: [vector] * len(texts)),
        patch.object(module, "_backup_database", return_value=tmp_path / "backup-2.db"),
    ):
        repaired = module._rebuild_memory(db_path, batch_size=2, force=False)
    assert repaired == 2
