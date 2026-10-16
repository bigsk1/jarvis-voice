#!/usr/bin/env python3
"""Regression tests for Memory UI memory ID search."""

from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server_package_utils import load_server_package

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class MemoryUiMemorySearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cloud_path = Path(self.temp_dir.name) / "jarvis_memory.db"
        self.local_path = Path(self.temp_dir.name) / "jarvis_memory_local.db"

        load_server_package("memory_search_test_server", PROJECT_ROOT / "jarvis-memory/server")
        memory_service_module = importlib.import_module("memory_search_test_server.services.memory_service")

        self.memory_service_module = memory_service_module
        self.original_db_paths = dict(memory_service_module.DB_PATHS)
        memory_service_module.DB_PATHS = {
            "cloud": self.cloud_path,
            "local": self.local_path,
        }

        app_module = importlib.import_module("memory_search_test_server.app")
        self.app = app_module.app
        self.MemoryService = memory_service_module.MemoryService
        self.auth_patcher = patch.object(app_module, "is_auth_enabled", return_value=False)
        self.auth_patcher.start()
        self.addCleanup(self.auth_patcher.stop)

        self._create_schema(self.cloud_path)
        self._create_schema(self.local_path)

    def tearDown(self) -> None:
        self.memory_service_module.DB_PATHS = self.original_db_paths
        self.temp_dir.cleanup()

    def _create_schema(self, path: Path) -> None:
        service = self.MemoryService("cloud" if path == self.cloud_path else "local")
        conn = service._get_conn()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_base (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    importance INTEGER DEFAULT 5,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    source TEXT,
                    metadata TEXT,
                    embedding BLOB,
                    long_form TEXT
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def test_search_memories_supports_plain_and_hash_id_in_selected_mode(self) -> None:
        cloud = self.MemoryService("cloud")
        local = self.MemoryService("local")
        cloud_id = cloud.create_memory("personal", "favorite_color", "blue")
        local_seed_id = local.create_memory("system", "seed", "ignore me")
        local_id = local.create_memory("personal", "favorite_color", "green")

        with self.app.test_client() as client:
            plain_resp = client.get(f"/api/memories/search?q={cloud_id}&mode=cloud")
            hash_resp = client.get(f"/api/memories/search?q=%23{cloud_id}&mode=cloud")
            local_resp = client.get(f"/api/memories/search?q={cloud_id}&mode=local")
            local_plain_resp = client.get(f"/api/memories/search?q={local_id}&mode=local")
            local_hash_resp = client.get(f"/api/memories/search?q=%23{local_id}&mode=local")

        plain_payload = plain_resp.get_json()
        hash_payload = hash_resp.get_json()
        local_payload = local_resp.get_json()
        local_plain_payload = local_plain_resp.get_json()
        local_hash_payload = local_hash_resp.get_json()

        self.assertEqual(plain_resp.status_code, 200)
        self.assertEqual(hash_resp.status_code, 200)
        self.assertEqual(local_resp.status_code, 200)
        self.assertEqual(local_plain_resp.status_code, 200)
        self.assertEqual(local_hash_resp.status_code, 200)

        self.assertEqual(plain_payload["count"], 1)
        self.assertEqual(hash_payload["count"], 1)
        self.assertEqual(plain_payload["memories"][0]["id"], cloud_id)
        self.assertEqual(hash_payload["memories"][0]["id"], cloud_id)
        self.assertEqual(plain_payload["memories"][0]["value"], "blue")
        self.assertEqual(hash_payload["memories"][0]["value"], "blue")

        self.assertEqual(local_payload["count"], 1)
        self.assertEqual(local_payload["memories"][0]["id"], local_seed_id)
        self.assertEqual(local_payload["memories"][0]["value"], "ignore me")
        self.assertEqual(local_plain_payload["count"], 1)
        self.assertEqual(local_hash_payload["count"], 1)
        self.assertEqual(local_plain_payload["memories"][0]["id"], local_id)
        self.assertEqual(local_hash_payload["memories"][0]["id"], local_id)
        self.assertEqual(local_plain_payload["memories"][0]["value"], "green")
        self.assertEqual(local_hash_payload["memories"][0]["value"], "green")


if __name__ == "__main__":
    unittest.main()
