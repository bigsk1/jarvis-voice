"""Tool-definition FTS5 synchronization coverage."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

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


def test_recovered_tools_restore_search_without_embeddings_and_respect_blocks(tmp_path):
    from config_loader import config_scope

    from lib.tool_schema import ToolSchema
    db = MemoryDB(str(tmp_path / 'memory.db'))
    try:
        db.conn.execute("INSERT INTO tool_definitions(name, description, schema_json, enabled, embedding) VALUES('old', 'Gmail labels', '{}', 0, ?)", (b'existing-vector',))
        tools = [ToolSchema(name=name, description='Gmail labels', parameters={}, script_path='__mcp__') for name in ('old', 'new', 'blocked')]
        with config_scope('cloud', overrides={'BLOCKED_TOOLS': 'blocked'}):
            db.register_recovered_tools(tools)
        assert db.get_enabled_tool_names() == ['old', 'new']
        assert _matches(db, 'gmail') == ['new', 'old']
        assert db.conn.execute("SELECT embedding FROM tool_definitions WHERE name='old'").fetchone()[0] == b'existing-vector'
        assert db.conn.execute("SELECT embedding FROM tool_definitions WHERE name='new'").fetchone()[0] is None
        tools[0].description = 'New Drive description'
        db.register_recovered_tools([tools[0]])
        assert db.conn.execute("SELECT embedding FROM tool_definitions WHERE name='old'").fetchone()[0] is None
        assert _matches(db, 'gmail') == ['new']
    finally:
        db.close()


def _hybrid_tool_search(db, query, monkeypatch):
    # One unrelated healthy vector keeps semantic retrieval enabled. Exercise
    # the public search path and real FTS admission, not the raw keyword index.
    monkeypatch.setattr('lib.memory_db.require_embedding_namespace', lambda *a, **k: None)
    monkeypatch.setattr('embeddings.get_embedding', lambda *a, **k: [1.0])
    monkeypatch.setattr('embeddings.cosine_similarity', lambda query, stored: stored[0])
    return db.search_tools(query, limit=8, threshold=0.27)


def test_recovered_new_tool_is_retrievable_while_other_embeddings_work(tmp_path, monkeypatch):
    import pickle

    from lib.tool_schema import ToolSchema
    db = MemoryDB(str(tmp_path / 'memory.db'))
    try:
        db.conn.execute("INSERT INTO tool_definitions(name, description, schema_json, enabled, embedding) VALUES('weather', 'Weather forecasts', '{}', 1, ?)", (pickle.dumps([0.1]),))
        tool = ToolSchema(name='mcp_google_workspace_get_drive_file_download_url',
                          description='Download a Google Drive PDF into Jarvis Stash for local work.',
                          parameters={}, script_path='__mcp__')
        db.register_recovered_tools([tool])
        rows = _hybrid_tool_search(db, 'Download that Drive PDF to Stash', monkeypatch)
        hit = next(row for row in rows if row['name'] == tool.name)
        assert hit['retrieval_channels'] == ['keyword']
        assert hit['embedding_pending'] is True
        assert db.last_tool_search_meta['semantic_disabled_reason'] is None
        assert db.conn.execute('SELECT embedding FROM tool_definitions WHERE name=?', (tool.name,)).fetchone()[0] is None
    finally:
        db.close()


def test_changed_recovered_tool_is_searchable_without_reusing_stale_embedding(tmp_path, monkeypatch):
    import pickle

    from lib.tool_schema import ToolSchema
    db = MemoryDB(str(tmp_path / 'memory.db'))
    try:
        db.conn.executemany("INSERT INTO tool_definitions(name, description, schema_json, enabled, embedding) VALUES(?, ?, '{}', ?, ?)", [
            ('weather', 'Weather forecasts', 1, pickle.dumps([0.1])),
            ('mcp_google_workspace_search_drive_files', 'Old description', 0, pickle.dumps([0.9])),
        ])
        tool = ToolSchema(name='mcp_google_workspace_search_drive_files',
                          description='Search Google Drive by filename to find a PDF manual for download into Stash.',
                          parameters={}, script_path='__mcp__')
        db.register_recovered_tools([tool])
        assert db.conn.execute('SELECT embedding FROM tool_definitions WHERE name=?', (tool.name,)).fetchone()[0] is None
        rows = _hybrid_tool_search(db, 'Find the PDF manual in Google Drive for Stash', monkeypatch)
        assert tool.name in [row['name'] for row in rows]
        assert db.last_tool_search_meta['semantic_disabled_reason'] is None
        generic = ToolSchema(name='generic_file_tool', description='Only a generic file operation.',
                             parameters={}, script_path='__mcp__')
        db.register_recovered_tools([generic])
        assert generic.name not in [row['name'] for row in _hybrid_tool_search(db, 'download google drive pdf file stash', monkeypatch)]
    finally:
        db.close()


def test_pending_vector_exception_does_not_bypass_existing_dense_threshold(tmp_path, monkeypatch):
    import pickle
    db = MemoryDB(str(tmp_path / 'memory.db'))
    try:
        db.conn.execute("INSERT INTO tool_definitions(name, description, schema_json, enabled, embedding) VALUES('low_dense_tool', 'Download Google Drive PDF to Stash', '{}', 1, ?)", (pickle.dumps([0.1]),))
        db.conn.commit()
        assert _hybrid_tool_search(db, 'Download Google Drive PDF to Stash', monkeypatch) == []
        assert db.last_tool_search_meta['semantic_disabled_reason'] is None
    finally:
        db.close()
