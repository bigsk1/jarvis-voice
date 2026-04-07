#!/usr/bin/env python3
"""Regression tests for serpapi_search parameter normalization."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

from serpapi_search import normalize_sort_by


class SerpApiSearchParamsTests(unittest.TestCase):
    def test_amazon_review_sort_mapping(self):
        key, value = normalize_sort_by("amazon", "review_score")
        self.assertEqual(key, "s")
        self.assertEqual(value, "review-rank")

    def test_amazon_price_sort_mapping(self):
        key, value = normalize_sort_by("amazon", "price_low")
        self.assertEqual(key, "s")
        self.assertEqual(value, "price-asc-rank")

    def test_non_amazon_sort_passthrough(self):
        key, value = normalize_sort_by("google_shopping", "review_score")
        self.assertEqual(key, "sort_by")
        self.assertEqual(value, "review_score")


if __name__ == "__main__":
    unittest.main()
