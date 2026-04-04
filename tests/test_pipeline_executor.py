#!/usr/bin/env python3
"""
Regression tests for workflow placeholder resolution.

Run:
    python3 tests/test_pipeline_executor.py
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from orchestrator.pipeline_executor import PipelineExecutor


class DummyProvider:
    pass


class PipelineExecutorResolutionTests(unittest.TestCase):
    def setUp(self):
        self.executor = PipelineExecutor(
            mode="cloud",
            executor=SimpleNamespace(execute=lambda *args, **kwargs: {}),
            provider=DummyProvider(),
        )

    def test_embedded_indexed_placeholders_resolve(self):
        variables = {
            "location": "Hillsboro, Oregon",
            "forecast_lows": [33, 36, 41],
            "forecast_dates": ["2026-04-03", "2026-04-04", "2026-04-05"],
        }

        resolved = self.executor._resolve_variable(
            "Cold watch for ${location}: tonight ${forecast_lows[0]}F on ${forecast_dates[0]}",
            variables,
        )

        self.assertEqual(
            resolved,
            "Cold watch for Hillsboro, Oregon: tonight 33F on 2026-04-03",
        )

    def test_mixed_placeholder_string_starting_with_placeholder_resolves(self):
        variables = {
            "alert_source": "weather_watch",
            "location": "Hillsboro, Oregon",
            "forecast_dates": ["2026-04-03"],
        }

        resolved = self.executor._resolve_variable(
            "${alert_source}:cold:${location}:${forecast_dates[0]}",
            variables,
        )

        self.assertEqual(
            resolved,
            "weather_watch:cold:Hillsboro, Oregon:2026-04-03",
        )

    def test_deterministic_numeric_condition(self):
        variables = {
            "forecast_lows": [34, 41],
            "cold_threshold_f": 34,
        }

        should_execute = self.executor._evaluate_condition(
            {
                "any": [
                    {"op": "lte", "left": "${forecast_lows[0]}", "right": "${cold_threshold_f}"},
                    {"op": "lte", "left": "${forecast_lows[1]}", "right": "${cold_threshold_f}"},
                ]
            },
            variables,
        )

        self.assertTrue(should_execute)

    def test_contains_any_condition(self):
        variables = {
            "forecast_conditions": ["partly cloudy", "freezing rain"],
        }

        should_execute = self.executor._evaluate_condition(
            {
                "any": [
                    {"op": "contains_any", "left": "${forecast_conditions[0]}", "right": ["thunderstorm", "snow"]},
                    {"op": "contains_any", "left": "${forecast_conditions[1]}", "right": ["thunderstorm", "freezing rain"]},
                ]
            },
            variables,
        )

        self.assertTrue(should_execute)

    def test_missing_numeric_value_does_not_trigger_threshold(self):
        variables = {
            "forecast_wind_maxes": ["n/a", "n/a"],
            "wind_threshold_mph": 25,
        }

        should_execute = self.executor._evaluate_condition(
            {
                "any": [
                    {"op": "gte", "left": "${forecast_wind_maxes[0]}", "right": "${wind_threshold_mph}"},
                    {"op": "gte", "left": "${forecast_wind_maxes[1]}", "right": "${wind_threshold_mph}"},
                ]
            },
            variables,
        )

        self.assertFalse(should_execute)


if __name__ == "__main__":
    unittest.main()
