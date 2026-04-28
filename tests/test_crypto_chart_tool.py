#!/usr/bin/env python3
"""Tests for the crypto_chart tool."""

import contextlib
import io
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from skills import crypto_chart


class _MockResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class TestCryptoChartTool(unittest.TestCase):
    def test_main_returns_structured_chart_payload(self):
        payload = {
            "prices": [
                [1710000000000, 100.0],
                [1710003600000, 110.0],
                [1710007200000, 120.0],
                [1710010800000, 130.0],
            ],
            "market_caps": [
                [1710000000000, 1000.0],
                [1710003600000, 1100.0],
                [1710007200000, 1200.0],
                [1710010800000, 1300.0],
            ],
            "total_volumes": [
                [1710000000000, 10.0],
                [1710003600000, 11.0],
                [1710007200000, 12.0],
                [1710010800000, 13.0],
            ],
        }

        with patch.object(crypto_chart, "load_config"), \
             patch.object(crypto_chart, "http_request", return_value=_MockResponse(payload)), \
             patch.object(crypto_chart, "get_proxy_config", return_value={"https": "http://proxy"}), \
             patch.object(
                 crypto_chart,
                 "get_config_value",
                 side_effect=lambda key, default="": "demo-key" if key == "COINGECKO_API_KEY" else default,
             ), \
             patch.object(
                 sys,
                 "argv",
                 ["crypto_chart.py", json.dumps({"coin": "btc", "days": "7", "points_limit": 3})],
             ):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = crypto_chart.main()

        self.assertEqual(exit_code, 0)
        result = json.loads(stdout.getvalue())
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["coin_id"], "bitcoin")
        self.assertEqual(result["data"]["days"], "7")
        self.assertEqual(result["data"]["points_returned"], 3)
        self.assertEqual(result["data"]["original_points"], 4)
        self.assertAlmostEqual(result["data"]["current_price"], 130.0)
        self.assertAlmostEqual(result["data"]["change_percent"], 30.0)
        self.assertEqual(len(result["data"]["series"]["prices"]), 3)
        self.assertEqual(result["data"]["series"]["prices"][0]["timestamp_ms"], 1710000000000)
        self.assertEqual(result["data"]["series"]["prices"][-1]["timestamp_ms"], 1710010800000)
        self.assertTrue(result["data"]["authenticated"])
        self.assertTrue(result["data"]["proxy_enabled"])


if __name__ == "__main__":
    unittest.main()
