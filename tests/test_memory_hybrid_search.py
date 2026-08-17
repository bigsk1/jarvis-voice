"""Regression coverage for memory dense/keyword fusion admission."""

import pickle
from unittest.mock import patch

from lib.memory_db import MemoryDB


def _add_memory(
    db: MemoryDB,
    key: str,
    value: str,
    *,
    similarity: float | None = None,
) -> int:
    memory_id = db.remember(
        "fact",
        key,
        value,
        generate_embedding=False,
    )
    if similarity is not None:
        db.conn.execute(
            "UPDATE knowledge_base SET embedding = ? WHERE id = ?",
            (pickle.dumps([similarity]), memory_id),
        )
        db.conn.commit()
    return memory_id


def _keyword_row(db: MemoryDB, memory_id: int) -> dict:
    row = dict(
        db.conn.execute(
            "SELECT * FROM knowledge_base WHERE id = ?",
            (memory_id,),
        ).fetchone()
    )
    row.pop("embedding", None)
    return row


def _run_with_fake_dense(db: MemoryDB, query: str, *, limit: int = 5) -> list[dict]:
    with (
        patch("lib.memory_db.require_embedding_namespace"),
        patch("embeddings.get_embedding", return_value=[1.0]),
        patch(
            "embeddings.cosine_similarity",
            side_effect=lambda _query, stored: stored[0],
        ),
    ):
        return db.semantic_search(
            query,
            limit=limit,
            similarity_threshold=0.30,
        )


def test_broad_keyword_only_hit_cannot_bury_dense_memory(tmp_path):
    db = MemoryDB(str(tmp_path / "memory.db"))
    try:
        top_id = _add_memory(db, "travel preference", "Likes trains", similarity=0.80)
        mid_id = _add_memory(db, "holiday plan", "Visit Kyoto", similarity=0.45)
        broad_id = _add_memory(db, "generic price", "Unrelated price note")
        broad_row = _keyword_row(db, broad_id)

        with (
            patch.object(db, "fts_search", return_value=[broad_row]),
            patch.object(db, "fts_search_precise", return_value=[]),
        ):
            results = _run_with_fake_dense(db, "Kyoto trip price")

        result_ids = [int(row["id"]) for row in results]
        assert result_ids == [top_id, mid_id]
        assert broad_id not in result_ids
        assert db.last_semantic_search_meta["keyword_candidate_count"] == 1
        assert db.last_semantic_search_meta["keyword_admitted_count"] == 0
    finally:
        db.close()


def test_precise_keyword_only_hit_remains_eligible_with_dense_search(tmp_path):
    db = MemoryDB(str(tmp_path / "memory.db"))
    try:
        dense_id = _add_memory(db, "travel preference", "Likes trains", similarity=0.80)
        precise_id = _add_memory(db, "Kyoto trip price", "Budget is 500 dollars")
        precise_row = _keyword_row(db, precise_id)

        with (
            patch.object(db, "fts_search", return_value=[]),
            patch.object(db, "fts_search_precise", return_value=[precise_row]),
        ):
            results = _run_with_fake_dense(db, "Kyoto trip price")

        by_id = {int(row["id"]): row for row in results}
        assert dense_id in by_id
        assert precise_id in by_id
        assert by_id[precise_id]["retrieval_channels"] == ["keyword"]
        assert by_id[precise_id]["keyword_match_mode"] == "precise"
    finally:
        db.close()


def test_broad_keyword_search_remains_fallback_when_embeddings_fail(tmp_path):
    db = MemoryDB(str(tmp_path / "memory.db"))
    try:
        memory_id = _add_memory(db, "generic price", "Fallback result")
        keyword_row = _keyword_row(db, memory_id)

        with (
            patch.object(db, "fts_search", return_value=[keyword_row]),
            patch.object(db, "fts_search_precise", return_value=[]),
        ):
            results = db.semantic_search("Kyoto trip price", limit=3)

        assert [int(row["id"]) for row in results] == [memory_id]
        assert results[0]["keyword_match_mode"] == "fallback"
        assert db.last_semantic_search_meta["retrieval_mode"] == "keyword_fallback"
        assert db.last_semantic_search_meta["semantic_disabled_reason"]
    finally:
        db.close()
