#!/usr/bin/env python3
"""Regression coverage for concurrent cloud/local Intelligence ownership."""

import asyncio
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import intelligence
import intelligence_hooks
import config_loader


class FakeLayer:
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = object()
        self.close_calls = 0

    def close(self):
        self.close_calls += 1
        self.conn = None


class IntelligenceModeCacheTests(unittest.TestCase):
    def setUp(self):
        intelligence.reset_intelligence_layer()
        intelligence_hooks._intelligence_layer = None
        intelligence_hooks._intelligence_checked = False

    def tearDown(self):
        intelligence.reset_intelligence_layer()
        intelligence_hooks._intelligence_layer = None
        intelligence_hooks._intelligence_checked = False

    def test_switching_modes_does_not_close_other_mode_layer(self):
        with patch.object(intelligence, "IntelligenceLayer", side_effect=FakeLayer) as layer_class:
            cloud = intelligence.get_intelligence_layer("cloud")
            local = intelligence.get_intelligence_layer("local")
            cloud_again = intelligence.get_intelligence_layer("cloud")

        self.assertIs(cloud_again, cloud)
        self.assertIsNot(local, cloud)
        self.assertIsNotNone(cloud.conn)
        self.assertIsNotNone(local.conn)
        self.assertEqual(cloud.close_calls, 0)
        self.assertEqual(local.close_calls, 0)
        self.assertEqual(layer_class.call_count, 2)

    def test_reset_can_close_only_one_mode(self):
        with patch.object(intelligence, "IntelligenceLayer", side_effect=FakeLayer):
            cloud = intelligence.get_intelligence_layer("cloud")
            local = intelligence.get_intelligence_layer("local")
            intelligence.reset_intelligence_layer("local")

        self.assertIsNotNone(cloud.conn)
        self.assertIsNone(local.conn)
        self.assertEqual(cloud.close_calls, 0)
        self.assertEqual(local.close_calls, 1)

    def test_hooks_resolve_each_concurrent_request_by_mode(self):
        layers = {mode: FakeLayer(f"{mode}.db") for mode in ("cloud", "local")}
        barrier = threading.Barrier(2)
        results = {}

        def get_layer(mode):
            barrier.wait()
            return layers[mode]

        def worker(mode):
            with config_loader.config_scope(mode):
                results[mode] = intelligence_hooks._get_intel()

        with patch.object(intelligence, "get_intelligence_layer", side_effect=get_layer):
            threads = [threading.Thread(target=worker, args=(mode,)) for mode in ("cloud", "local")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertIs(results["cloud"], layers["cloud"])
        self.assertIs(results["local"], layers["local"])

    def test_run_async_preserves_scoped_config_from_running_loop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_dir = root / "config"
            config_dir.mkdir()
            model = "bigsk1/jarvis-embedding:bf16-v1"
            (config_dir / "cloud.env").write_text(f"OLLAMA_EMBEDDING_MODEL={model}\n")
            (config_dir / "local.env").write_text(f"OLLAMA_EMBEDDING_MODEL={model}\n")

            async def probe():
                return (
                    config_loader.get_active_config_mode(),
                    config_loader.get_config_value("OLLAMA_EMBEDDING_MODEL"),
                )

            async def run_probe():
                with config_loader.config_scope("local"):
                    return intelligence_hooks._run_async(probe())

            with patch.object(config_loader, "get_project_root", return_value=root):
                observed = asyncio.run(run_probe())

        self.assertEqual(observed, ("local", "bigsk1/jarvis-embedding:bf16-v1"))

    def test_maintenance_hook_honors_explicit_local_mode(self):
        class MaintenanceLayer:
            async def run_decay_job(self, *, force, dry_run):
                return {
                    "status": "dry_run",
                    "active_mode": config_loader.get_active_config_mode(),
                    "force": force,
                    "dry_run": dry_run,
                }

        with patch.object(
            intelligence_hooks,
            "_get_intel",
            return_value=MaintenanceLayer(),
        ) as get_intel:
            result = intelligence_hooks.run_decay_job(
                force=True,
                dry_run=True,
                mode="local",
            )

        get_intel.assert_called_once_with("local")
        self.assertEqual(result["active_mode"], "local")
        self.assertTrue(result["force"])
        self.assertTrue(result["dry_run"])

    def test_cosine_accepts_rebuilt_list_vectors_and_rejects_shape_mismatch(self):
        layer = object.__new__(intelligence.IntelligenceLayer)
        self.assertAlmostEqual(
            layer._cosine_similarity(np.array([1.0, 0.0]), [1.0, 0.0]),
            1.0,
        )
        with self.assertRaisesRegex(ValueError, "shape mismatch"):
            layer._cosine_similarity(np.array([1.0, 0.0]), [1.0])


if __name__ == "__main__":
    unittest.main()
