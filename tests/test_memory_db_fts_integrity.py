"""Regression coverage for external-content FTS5 trigger integrity."""

import logging
import sqlite3

from lib.memory_db import MemoryDB


def _assert_external_content_integrity(db: MemoryDB) -> None:
    db.conn.execute(
        "INSERT INTO knowledge_base_fts(knowledge_base_fts, rank) "
        "VALUES('integrity-check', 1)"
    )


def _matching_rowids(db: MemoryDB, query: str) -> list[int]:
    rows = db.conn.execute(
        "SELECT rowid FROM knowledge_base_fts WHERE knowledge_base_fts MATCH ?",
        (query,),
    ).fetchall()
    return [int(row[0]) for row in rows]


def _install_legacy_update_delete_triggers(db: MemoryDB) -> None:
    db.conn.executescript(
        """
        DROP TRIGGER kb_fts_update;
        DROP TRIGGER kb_fts_delete;

        CREATE TRIGGER kb_fts_update AFTER UPDATE ON knowledge_base BEGIN
            UPDATE knowledge_base_fts SET
                category = new.category,
                key = new.key,
                value = new.value,
                long_form = new.long_form
            WHERE rowid = new.id;
        END;

        CREATE TRIGGER kb_fts_delete AFTER DELETE ON knowledge_base BEGIN
            DELETE FROM knowledge_base_fts WHERE rowid = old.id;
        END;
        """
    )
    db.conn.commit()


def test_memory_update_and_delete_keep_external_fts_index_consistent(tmp_path):
    db = MemoryDB(str(tmp_path / "memory.db"))
    try:
        memory_id = db.remember(
            "fact",
            "fts_integrity_probe",
            "alphaolduniqueterm",
            generate_embedding=False,
        )
        db.remember(
            "fact",
            "fts_integrity_probe",
            "betanewuniqueterm",
            generate_embedding=False,
        )

        assert _matching_rowids(db, "alphaolduniqueterm") == []
        assert _matching_rowids(db, "betanewuniqueterm") == [memory_id]
        _assert_external_content_integrity(db)

        assert db.forget(memory_id, mirror_sibling=False) is True
        assert _matching_rowids(db, "betanewuniqueterm") == []
        _assert_external_content_integrity(db)
    finally:
        db.close()


def test_opening_legacy_database_replaces_triggers_and_repairs_index(tmp_path, caplog):
    db_path = tmp_path / "legacy.db"
    db = MemoryDB(str(db_path))
    try:
        _install_legacy_update_delete_triggers(db)
        memory_id = db.remember(
            "fact",
            "legacy_fts_probe",
            "legacyalphauniqueterm",
            generate_embedding=False,
        )
        db.remember(
            "fact",
            "legacy_fts_probe",
            "currentbetauniqueterm",
            generate_embedding=False,
        )
        assert _matching_rowids(db, "legacyalphauniqueterm") == [memory_id]
        try:
            _assert_external_content_integrity(db)
        except sqlite3.DatabaseError:
            pass
        else:
            raise AssertionError("legacy trigger fixture did not corrupt FTS content consistency")
    finally:
        db.close()

    repaired = MemoryDB(str(db_path))
    try:
        assert _matching_rowids(repaired, "legacyalphauniqueterm") == []
        assert _matching_rowids(repaired, "currentbetauniqueterm") == [memory_id]
        _assert_external_content_integrity(repaired)

        trigger_sql = repaired.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = 'kb_fts_update'"
        ).fetchone()[0]
        assert "'delete', old.id" in trigger_sql
        assert "AFTER UPDATE OF category, key, value, long_form" in trigger_sql
    finally:
        repaired.close()

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="lib.memory_db"):
        reopened = MemoryDB(str(db_path))
        reopened.close()
    assert "Rebuilt legacy knowledge_base FTS5 index" not in caplog.text
