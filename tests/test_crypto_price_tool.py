#!/usr/bin/env python3
"""
Regression tests for crypto_price single and multi-coin behavior.

Run:
    python3 tests/test_crypto_price_tool.py
"""

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

import crypto_price


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class CryptoPriceToolTests(unittest.TestCase):
    def run_tool(self, tool_input, api_payload):
        stdout = io.StringIO()

        with patch.object(crypto_price, "load_config"), \
             patch.object(crypto_price, "get_config_value", return_value=""), \
             patch.object(crypto_price, "get_proxy_config", return_value=None), \
             patch.object(crypto_price, "http_request", return_value=FakeResponse(api_payload)), \
             patch.object(crypto_price.sys, "argv", ["crypto_price.py", json.dumps(tool_input)]), \
             redirect_stdout(stdout):
            exit_code = crypto_price.main()

        return exit_code, json.loads(stdout.getvalue())

    def test_single_coin_preserves_legacy_shape(self):
        exit_code, result = self.run_tool(
            {"coin": "bitcoin"},
            {
                "bitcoin": {
                    "usd": 78703,
                    "usd_market_cap": 1576177403500.16,
                    "usd_24h_change": 0.7247509295,
                }
            },
        )

        self.assertEqual(exit_code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["coin"], "Bitcoin")
        self.assertEqual(result["data"]["coin_id"], "bitcoin")
        self.assertEqual(result["data"]["price_usd"], 78703)
        self.assertIn("change_24h_percent", result["data"])
        self.assertNotIn("coins", result["data"])
        self.assertNotIn("requested", result["data"])
        self.assertIn("Bitcoin is currently", result["speech"])

    def test_multi_coin_array_returns_combined_result(self):
        exit_code, result = self.run_tool(
            {"coins": ["btc", "sol"]},
            {
                "bitcoin": {
                    "usd": 78703,
                    "usd_market_cap": 1576177403500.16,
                    "usd_24h_change": 0.7247509295,
                },
                "solana": {
                    "usd": 84.3,
                    "usd_market_cap": 48583044723.64,
                    "usd_24h_change": 0.7350887021,
                },
            },
        )

        self.assertEqual(exit_code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["count"], 2)
        self.assertEqual([coin["coin_id"] for coin in result["data"]["coins"]], ["bitcoin", "solana"])
        self.assertEqual([coin["requested"] for coin in result["data"]["coins"]], ["btc", "sol"])
        self.assertIn("Bitcoin is currently", result["speech"])
        self.assertIn("Solana is currently", result["speech"])

    def test_comma_separated_legacy_coin_input_supports_multiple(self):
        exit_code, result = self.run_tool(
            {"coin": "bitcoin, solana"},
            {
                "bitcoin": {
                    "usd": 78703,
                    "usd_market_cap": 1576177403500.16,
                    "usd_24h_change": 0.7247509295,
                },
                "solana": {
                    "usd": 84.3,
                    "usd_market_cap": 48583044723.64,
                    "usd_24h_change": 0.7350887021,
                },
            },
        )

        self.assertEqual(exit_code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["count"], 2)
        self.assertEqual([coin["requested"] for coin in result["data"]["coins"]], ["bitcoin", "solana"])

    def test_multi_coin_partial_success_reports_missing(self):
        exit_code, result = self.run_tool(
            {"coins": ["bitcoin", "notarealcoin"]},
            {
                "bitcoin": {
                    "usd": 78703,
                    "usd_market_cap": 1576177403500.16,
                    "usd_24h_change": 0.7247509295,
                }
            },
        )

        self.assertEqual(exit_code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["count"], 1)
        self.assertEqual(result["data"]["missing_coins"], ["notarealcoin"])
        self.assertIn("I couldn't find Notarealcoin.", result["speech"])


if __name__ == "__main__":
    unittest.main()
