"""Tool-definition FTS5 synchronization coverage."""

from lib.memory_db import MemoryDB


def _matches(db: MemoryDB, query: str) -> list[str]:
    rows = db.conn.execute(
        "SELECT name FROM tool_definitions_fts "
        "WHERE tool_definitions_fts MATCH ? ORDER BY name",
        (query,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def test_tool_fts_index_tracks_insert_update_and_delete(tmp_path):
    db = MemoryDB(str(tmp_path / "memory.db"))
    try:
        db.conn.execute(
            """
            INSERT INTO tool_definitions(name, description, schema_json, enabled)
            VALUES('weather_forecast', 'Find alphacloud weather', '{}', 1)
            """
        )
        db.conn.commit()
        assert _matches(db, "alphacloud") == ["weather_forecast"]
        assert _matches(db, "weather") == ["weather_forecast"]

        db.conn.execute(
            "UPDATE tool_definitions SET description = 'Find betastorm weather' "
            "WHERE name = 'weather_forecast'"
        )
        db.conn.commit()
        assert _matches(db, "alphacloud") == []
        assert _matches(db, "betastorm") == ["weather_forecast"]

        db.conn.execute(
            "DELETE FROM tool_definitions WHERE name = 'weather_forecast'"
        )
        db.conn.commit()
        assert _matches(db, "betastorm") == []
    finally:
        db.close()


def test_reopening_fresh_database_keeps_tool_fts_rows(tmp_path):
    db_path = tmp_path / "memory.db"
    db = MemoryDB(str(db_path))
    db.conn.execute(
        """
        INSERT INTO tool_definitions(name, description, schema_json, enabled)
        VALUES('send_email', 'Send electronic mail', '{}', 1)
        """
    )
    db.conn.commit()
    db.close()

    reopened = MemoryDB(str(db_path))
    try:
        assert _matches(reopened, "email") == ["send_email"]
    finally:
        reopened.close()


def test_tool_search_uses_ranked_keyword_fallback_without_embeddings(tmp_path):
    db = MemoryDB(str(tmp_path / "memory.db"))
    try:
        db.conn.executemany(
            """
            INSERT INTO tool_definitions(name, description, schema_json, enabled)
            VALUES(?, ?, '{}', 1)
            """,
            [
                ("weather", "Get a weather forecast for a location."),
                ("send_email", "Send an email message."),
            ],
        )
        db.conn.commit()

        results = db.search_tools("weather forecast", limit=5, threshold=0.28)

        assert [row["name"] for row in results] == ["weather"]
        assert results[0]["retrieval_channels"] == ["keyword"]
        assert db.last_tool_search_meta["retrieval_mode"] == "keyword_fallback"
        assert db.last_tool_search_meta["semantic_disabled_reason"] == (
            "no enabled tool embeddings"
        )
    finally:
        db.close()
