#!/usr/bin/env python3
"""Regression coverage for concurrent cloud/local Intelligence ownership."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import intelligence


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

    def tearDown(self):
        intelligence.reset_intelligence_layer()

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


if __name__ == "__main__":
    unittest.main()
