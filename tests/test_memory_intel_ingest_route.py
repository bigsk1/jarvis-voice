#!/usr/bin/env python3
"""Regression tests for the Memory UI intel ingest route."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _purge_server_modules() -> None:
    for key in list(sys.modules.keys()):
        if key == "server" or key.startswith("server."):
            del sys.modules[key]


class MemoryIntelIngestRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _purge_server_modules()
        web = str(PROJECT_ROOT / "jarvis-web")
        if web in sys.path:
            sys.path.remove(web)
        sys.path.insert(0, str(PROJECT_ROOT / "jarvis-memory"))
        from server.app import app

        cls.app = app

    def test_ingest_route_uses_dual_mode_helper(self) -> None:
        fake_result = {
            "ingested": True,
            "new_files": 0,
            "total_facts": 81,
            "modes": ["cloud"],
            "failed_modes": ["local"],
            "partial": True,
            "warning": "local ingest failed: ollama unavailable",
        }

        with patch("server.routes.intel.auto_ingest", return_value=fake_result) as mock_ingest:
            with self.app.test_client() as client:
                response = client.post("/api/intel/ingest?mode=cloud")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["mode"], "cloud")
        self.assertIn("Intel ingest complete for cloud.", payload["speech"])
        self.assertIn("81 total facts", payload["speech"])
        self.assertIn("local ingest failed", payload["speech"])
        self.assertEqual(payload["data"]["failed_modes"], ["local"])
        mock_ingest.assert_called_once()
        args, _kwargs = mock_ingest.call_args
        self.assertEqual(args[1], "cloud")

    def test_ingest_route_mentions_both_dbs_on_dual_success(self) -> None:
        fake_result = {
            "ingested": True,
            "new_files": 2,
            "total_facts": 28,
            "modes": ["cloud", "local"],
        }

        with patch("server.routes.intel.auto_ingest", return_value=fake_result):
            with self.app.test_client() as client:
                response = client.post("/api/intel/ingest?mode=cloud")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertIn("cloud and local", payload["speech"])
        self.assertIn("28 total facts", payload["speech"])
        self.assertIn("across both DBs", payload["speech"])

    def test_ingest_route_rejects_invalid_mode(self) -> None:
        with self.app.test_client() as client:
            response = client.post("/api/intel/ingest?mode=weird")

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("Invalid mode", payload["error"])

    def test_ingest_route_surfaces_timeout_as_504(self) -> None:
        fake_result = {"ingested": False, "error": "Ingest timeout (300s per mode)"}

        with patch("server.routes.intel.auto_ingest", return_value=fake_result):
            with self.app.test_client() as client:
                response = client.post("/api/intel/ingest?mode=local")

        self.assertEqual(response.status_code, 504)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("timeout", payload["error"].lower())


if __name__ == "__main__":
    unittest.main()
