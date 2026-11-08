"""Portable memory edits survive a sibling's unavailable semantic index."""

from __future__ import annotations

import importlib
import json
import pickle
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import config_loader
import embeddings
import pytest
from config_loader import config_scope
from embedding_metadata import (
    MEMORY_KNOWLEDGE_NAMESPACE,
    embedding_namespace_status,
    read_embedding_metadata,
    record_embedding_namespace_complete,
)
from server_package_utils import load_server_package

from lib.memory_db import MemoryDB

ROOT = Path(__file__).resolve().parents[1]
MODEL = "bigsk1/jarvis-embedding:bf16-v1"
SOURCE_DIGEST = "a" * 64
OLD_VECTOR = pickle.dumps([0.1] * embeddings.EMBEDDING_DIMENSIONS)
NEW_VECTOR = [0.25] * embeddings.EMBEDDING_DIMENSIONS


@dataclass
class MemoryHarness:
    source_mode: str
    paths: dict[str, Path]
    config_root: Path
    service_module: ModuleType
    provider: Mock

    @property
    def target_mode(self) -> str:
        return "local" if self.source_mode == "cloud" else "cloud"

    def set_mode_digest(self, mode: str, digest: str) -> None:
        (self.config_root / "config" / f"{mode}.env").write_text(
            f"OLLAMA_EMBEDDING_MODEL={MODEL}\n"
            f"OLLAMA_EMBEDDING_MODEL_DIGEST={digest}\n",
            encoding="utf-8",
        )

    def seed(self, mode: str, namespace_state: str = "complete") -> int:
        """Create real schema, FTS triggers and namespace metadata in a temp DB."""
        with config_scope(mode):
            db = MemoryDB(str(self.paths[mode]))
            try:
                cursor = db.conn.execute(
                    """INSERT INTO knowledge_base
                       (category, key, value, importance, metadata, embedding)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        "personal", "user_birthday", "January 1st", 5,
                        json.dumps({"verified": False}), OLD_VECTOR,
                    ),
                )
                memory_id = cursor.lastrowid
                # Keep another vector present after the edited row is cleared: an
                # untracked namespace must not become implicitly trustworthy.
                db.conn.execute(
                    """INSERT INTO knowledge_base (category, key, value, embedding)
                       VALUES ('fact', 'untouched', 'A separate memory', ?)""",
                    (OLD_VECTOR,),
                )
                record_embedding_namespace_complete(db.conn, MEMORY_KNOWLEDGE_NAMESPACE)
                if namespace_state == "incompatible":
                    db.conn.execute(
                        "UPDATE embedding_metadata SET model_digest = ? WHERE namespace = ?",
                        ("c" * 64, MEMORY_KNOWLEDGE_NAMESPACE),
                    )
                elif namespace_state == "rebuilding":
                    db.conn.execute(
                        """UPDATE embedding_metadata SET state = 'rebuilding', last_row_id = 17
                           WHERE namespace = ?""",
                        (MEMORY_KNOWLEDGE_NAMESPACE,),
                    )
                elif namespace_state == "untracked":
                    db.conn.execute(
                        "DELETE FROM embedding_metadata WHERE namespace = ?",
                        (MEMORY_KNOWLEDGE_NAMESPACE,),
                    )
                else:
                    assert namespace_state == "complete"
                db.conn.commit()
                assert memory_id is not None
                return memory_id
            finally:
                db.close()

    def metadata(self, mode: str) -> dict | None:
        with closing(sqlite3.connect(self.paths[mode])) as conn:
            return read_embedding_metadata(conn, MEMORY_KNOWLEDGE_NAMESPACE)

    def rows(self, mode: str) -> list[dict]:
        with closing(sqlite3.connect(self.paths[mode])) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute("SELECT * FROM knowledge_base ORDER BY id")]

    def update(self, writer: str, memory_id: int, **kwargs) -> bool:
        with config_scope(self.source_mode):
            if writer == "ui":
                service = self.service_module.MemoryService(self.source_mode)
                return service.update_memory(memory_id, **kwargs)
            assert writer == "library"
            db = MemoryDB(str(self.paths[self.source_mode]))
            try:
                return db.update_memory(memory_id, **kwargs)
            finally:
                db.close()


@pytest.fixture(params=["cloud", "local"])
def memory_harness(tmp_path, monkeypatch, request):
    alias = "jarvis_memory_sibling_compatibility_tests"
    load_server_package(alias, ROOT / "jarvis-memory" / "server")
    service_module = importlib.import_module(f"{alias}.services.memory_service")
    config_root = tmp_path / "settings"
    (config_root / "config").mkdir(parents=True)
    monkeypatch.setattr(config_loader, "get_project_root", lambda: config_root)
    paths = {
        "cloud": tmp_path / "jarvis_memory.db",
        "local": tmp_path / "jarvis_memory_local.db",
    }
    monkeypatch.setattr(service_module, "DB_PATHS", paths)
    provider = Mock(return_value=list(NEW_VECTOR))
    monkeypatch.setattr(embeddings, "get_persistable_embedding", provider)
    monkeypatch.setattr(service_module, "get_persistable_embedding", provider)
    harness = MemoryHarness(request.param, paths, config_root, service_module, provider)
    for mode in paths:
        harness.set_mode_digest(mode, SOURCE_DIGEST)
    yield harness


@pytest.fixture(params=["ui", "library"])
def writer(request):
    return request.param


def _edit(harness: MemoryHarness, writer: str, memory_id: int) -> None:
    changes: dict = {"value": "January 2nd", "importance": 9}
    if writer == "ui":
        changes.update(category="profile", key="birthday", metadata={"verified": True})
    assert harness.update(writer, memory_id, **changes) is True


def _assert_mirrored(
    harness: MemoryHarness, writer: str, *, target_other_vector: bytes | None = OLD_VECTOR,
) -> dict:
    source, source_other = harness.rows(harness.source_mode)
    target, target_other = harness.rows(harness.target_mode)
    assert source["value"] == target["value"] == "January 2nd"
    assert source["importance"] == target["importance"] == 9
    for field in ("category", "key", "metadata"):
        assert target[field] == source[field]
    if writer == "ui":
        assert target["category"] == "profile"
        assert target["key"] == "birthday"
        assert json.loads(target["metadata"]) == {"verified": True}
    assert source_other["value"] == target_other["value"] == "A separate memory"
    assert source_other["embedding"] == OLD_VECTOR
    assert target_other["embedding"] == target_other_vector
    return target


@pytest.mark.parametrize("state", ["incompatible", "rebuilding", "untracked"])
def test_incompatible_sibling_still_receives_text_without_accepting_vectors(
    memory_harness, writer, state,
):
    harness = memory_harness
    memory_id = harness.seed(harness.source_mode)
    harness.seed(harness.target_mode, state)
    target_metadata = harness.metadata(harness.target_mode)

    _edit(harness, writer, memory_id)

    target = _assert_mirrored(harness, writer)
    assert target["embedding"] is None
    assert harness.rows(harness.source_mode)[0]["embedding"] == pickle.dumps(NEW_VECTOR)
    assert harness.metadata(harness.target_mode) == target_metadata
    with (
        config_scope(harness.target_mode),
        closing(sqlite3.connect(harness.paths[harness.target_mode])) as conn,
    ):
        status = embedding_namespace_status(conn, MEMORY_KNOWLEDGE_NAMESPACE, vector_count=1)
    assert status["ok"] is False


def test_compatible_sibling_reuses_the_generated_vector(memory_harness, writer):
    harness = memory_harness
    memory_id = harness.seed(harness.source_mode)
    harness.seed(harness.target_mode)

    _edit(harness, writer, memory_id)

    target = _assert_mirrored(harness, writer)
    assert target["embedding"] == pickle.dumps(NEW_VECTOR)
    assert harness.metadata(harness.target_mode)["state"] == "complete"
    harness.provider.assert_called_once()


def test_sibling_with_different_configured_fingerprint_gets_text_only(memory_harness, writer):
    harness = memory_harness
    harness.set_mode_digest(harness.target_mode, "b" * 64)
    memory_id = harness.seed(harness.source_mode)
    harness.seed(harness.target_mode)
    target_metadata = harness.metadata(harness.target_mode)

    _edit(harness, writer, memory_id)

    target = _assert_mirrored(harness, writer)
    assert target["embedding"] is None
    assert harness.metadata(harness.target_mode) == target_metadata
    assert target_metadata["model_digest"] == "b" * 64
    assert harness.metadata(harness.source_mode)["model_digest"] == SOURCE_DIGEST
    harness.provider.assert_called_once()


@pytest.mark.parametrize("same_contract", [True, False])
def test_empty_target_namespace_initializes_only_for_the_matching_contract(
    memory_harness, writer, same_contract,
):
    harness = memory_harness
    if not same_contract:
        harness.set_mode_digest(harness.target_mode, "b" * 64)
    memory_id = harness.seed(harness.source_mode)
    harness.seed(harness.target_mode)
    with closing(sqlite3.connect(harness.paths[harness.target_mode])) as conn, conn:
        conn.execute("UPDATE knowledge_base SET embedding = NULL")
        conn.execute("DELETE FROM embedding_metadata WHERE namespace = ?", (MEMORY_KNOWLEDGE_NAMESPACE,))
    assert harness.metadata(harness.target_mode) is None

    _edit(harness, writer, memory_id)

    target = _assert_mirrored(harness, writer, target_other_vector=None)
    target_metadata = harness.metadata(harness.target_mode)
    if same_contract:
        assert target["embedding"] == pickle.dumps(NEW_VECTOR)
        assert target_metadata["model_digest"] == SOURCE_DIGEST
        assert target_metadata["state"] == "complete"
    else:
        assert target["embedding"] is None
        assert target_metadata is None


def test_importance_only_edit_preserves_the_existing_vector_and_namespace(memory_harness, writer):
    harness = memory_harness
    memory_id = harness.seed(harness.source_mode)
    harness.seed(harness.target_mode, "rebuilding")
    target_metadata = harness.metadata(harness.target_mode)

    assert harness.update(writer, memory_id, importance=9) is True

    source = harness.rows(harness.source_mode)[0]
    target = harness.rows(harness.target_mode)[0]
    assert source["value"] == target["value"] == "January 1st"
    assert source["importance"] == target["importance"] == 9
    assert source["embedding"] == target["embedding"] == OLD_VECTOR
    assert harness.metadata(harness.target_mode) == target_metadata
    harness.provider.assert_not_called()


def test_importance_only_ui_edit_clears_a_vector_when_sibling_text_is_different(memory_harness):
    harness = memory_harness
    memory_id = harness.seed(harness.source_mode)
    harness.seed(harness.target_mode)
    target_path = harness.paths[harness.target_mode]
    with closing(sqlite3.connect(target_path)) as conn, conn:
        conn.execute(
            "UPDATE knowledge_base SET value = ? WHERE key = ?",
            ("October 3rd", "user_birthday"),
        )
    target_metadata = harness.metadata(harness.target_mode)

    assert harness.update("ui", memory_id, importance=9) is True

    source, source_other = harness.rows(harness.source_mode)
    target, target_other = harness.rows(harness.target_mode)
    assert source["value"] == target["value"] == "January 1st"
    assert source["importance"] == target["importance"] == 9
    assert source["embedding"] == OLD_VECTOR
    assert target["embedding"] is None
    assert source_other["embedding"] == target_other["embedding"] == OLD_VECTOR
    assert harness.metadata(harness.target_mode) == target_metadata
    harness.provider.assert_not_called()


def test_failed_provider_clears_both_edited_vectors_and_preserves_bad_target_state(
    memory_harness, writer,
):
    harness = memory_harness
    memory_id = harness.seed(harness.source_mode)
    harness.seed(harness.target_mode, "rebuilding")
    target_metadata = harness.metadata(harness.target_mode)
    harness.provider.side_effect = RuntimeError("Test embedding provider unavailable")

    _edit(harness, writer, memory_id)

    target = _assert_mirrored(harness, writer)
    assert target["embedding"] is None
    assert harness.rows(harness.source_mode)[0]["embedding"] is None
    assert harness.metadata(harness.target_mode) == target_metadata


def test_edit_does_not_create_a_missing_sibling_database(memory_harness, writer):
    harness = memory_harness
    memory_id = harness.seed(harness.source_mode)
    target_path = harness.paths[harness.target_mode]
    assert not target_path.exists()

    _edit(harness, writer, memory_id)

    assert harness.rows(harness.source_mode)[0]["value"] == "January 2nd"
    assert not target_path.exists()
