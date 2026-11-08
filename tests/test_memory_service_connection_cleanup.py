"""Memory edit requests release per-request SQLite connections immediately."""

import importlib
import sqlite3
from pathlib import Path

import pytest
from flask import Flask
from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
ALIAS = "memory_connection_cleanup_test_server"
load_server_package(ALIAS, ROOT / "jarvis-memory" / "server")
memory_service = importlib.import_module(f"{ALIAS}.services.memory_service")
memory_routes = importlib.import_module(f"{ALIAS}.routes.memories")


@pytest.mark.parametrize(("payload", "status", "connection_count"), [
    ({}, 400, 1),
    ({"value": None}, 200, 2),
])
def test_empty_and_null_edits_release_connections_without_waiting_for_gc(
    tmp_path, monkeypatch, payload, status, connection_count,
):
    path = tmp_path / "memory.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE knowledge_base (id INTEGER PRIMARY KEY, category TEXT, key TEXT, "
        "value TEXT, importance INTEGER, metadata TEXT, embedding BLOB, "
        "created_at TEXT, updated_at TEXT, source TEXT, long_form TEXT)"
    )
    connection.execute(
        "INSERT INTO knowledge_base (id, category, key, value, importance, metadata) "
        "VALUES (1, 'fact', 'sample', 'original', 5, '{}')"
    )
    connection.commit()
    connection.close()
    service = memory_service.MemoryService("cloud")
    service.db_path = path
    opened = []

    def connect():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        opened.append(conn)
        return conn

    monkeypatch.setattr(service, "_get_conn", connect)
    monkeypatch.setattr(memory_routes, "MemoryService", lambda _mode: service)
    app = Flask(__name__)
    app.register_blueprint(memory_routes.memories_bp)
    try:
        response = app.test_client().put("/api/memories/1", json=payload)
        assert response.status_code == status
        assert response.get_json()["ok"] is False
        assert len(opened) == connection_count
        for conn in opened:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                conn.execute("SELECT 1")
        with sqlite3.connect(path) as check:
            assert check.execute("SELECT value FROM knowledge_base WHERE id = 1").fetchone()[0] == "original"
    finally:
        for conn in opened:
            conn.close()
