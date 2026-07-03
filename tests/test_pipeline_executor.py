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


class UnknownCostProvider:
    def __init__(self):
        self.tool_calls = 0
        self.fallback_calls = 0

    def chat_with_tools(self, **_kwargs):
        self.tool_calls += 1
        return (
            "first response",
            None,
            {
                "input_tokens": 3,
                "output_tokens": 2,
                "total_tokens": 5,
                "cost_usd": None,
                "cost_known": False,
                "billing_mode": "ollama_cloud_subscription",
            },
            None,
        )

    def chat(self, *_args):
        self.fallback_calls += 1
        return "unexpected fallback"


class CachedCostProvider:
    def chat_with_tools(self, **_kwargs):
        return (
            "cached response",
            None,
            {
                "input_tokens": 10,
                "output_tokens": 2,
                "total_tokens": 1_012,
                "cost_usd": 0.02,
                "cache_creation_tokens": 1_000,
                "cache_read_tokens": 0,
                "cache_write_cost_usd": 0.0125,
                "cache_read_cost_usd": 0.0,
                "cache_cost_usd": 0.0125,
                "cache_savings_usd": 0.0,
            },
            None,
        )


class SequencedUsageProvider:
    def __init__(self):
        self.usages = iter((
            {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110, "cost_usd": 0.01},
            {"input_tokens": 240, "output_tokens": 20, "total_tokens": 260, "cost_usd": 0.02},
        ))

    def chat_with_tools(self, **_kwargs):
        return "response", None, next(self.usages), None


class PipelineExecutorResolutionTests(unittest.TestCase):
    def setUp(self):
        self.executor = PipelineExecutor(
            mode="cloud",
            executor=SimpleNamespace(execute=lambda *args, **kwargs: {}),
            provider=DummyProvider(),
        )

    def test_embedded_indexed_placeholders_resolve(self):
        variables = {
            "location": "Portland, Oregon",
            "forecast_lows": [33, 36, 41],
            "forecast_dates": ["2026-04-03", "2026-04-04", "2026-04-05"],
        }

        resolved = self.executor._resolve_variable(
            "Cold watch for ${location}: tonight ${forecast_lows[0]}F on ${forecast_dates[0]}",
            variables,
        )

        self.assertEqual(
            resolved,
            "Cold watch for Portland, Oregon: tonight 33F on 2026-04-03",
        )

    def test_mixed_placeholder_string_starting_with_placeholder_resolves(self):
        variables = {
            "alert_source": "weather_watch",
            "location": "Portland, Oregon",
            "forecast_dates": ["2026-04-03"],
        }

        resolved = self.executor._resolve_variable(
            "${alert_source}:cold:${location}:${forecast_dates[0]}",
            variables,
        )

        self.assertEqual(
            resolved,
            "weather_watch:cold:Portland, Oregon:2026-04-03",
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

    def test_unknown_subscription_cost_does_not_retry_llm_call(self):
        provider = UnknownCostProvider()
        executor = PipelineExecutor(
            mode="cloud",
            executor=SimpleNamespace(execute=lambda *args, **kwargs: {}),
            provider=provider,
        )

        result = executor._chat_with_usage("probe")

        self.assertEqual(result, "first response")
        self.assertEqual(provider.tool_calls, 1)
        self.assertEqual(provider.fallback_calls, 0)
        self.assertEqual(executor._total_usage["cost_usd"], 0.0)
        self.assertTrue(executor._total_usage["has_unknown_cost"])
        self.assertFalse(executor._total_usage["cost_known"])
        self.assertEqual(executor._total_usage["model_calls"], 1)
        self.assertEqual(executor._total_usage["peak_context_tokens"], 5)

    def test_cache_cost_breakdown_survives_workflow_aggregation(self):
        executor = PipelineExecutor(
            mode="cloud",
            executor=SimpleNamespace(execute=lambda *args, **kwargs: {}),
            provider=CachedCostProvider(),
        )

        result = executor._chat_with_usage("probe")

        self.assertEqual(result, "cached response")
        self.assertEqual(executor._total_usage["cost_usd"], 0.02)
        self.assertEqual(executor._total_usage["cache_creation_tokens"], 1_000)
        self.assertEqual(executor._total_usage["cache_write_cost_usd"], 0.0125)
        self.assertEqual(executor._total_usage["model_calls"], 1)
        self.assertEqual(executor._total_usage["peak_context_tokens"], 1_012)

    def test_usage_tracks_calls_and_largest_single_call_context(self):
        executor = PipelineExecutor(
            mode="cloud",
            executor=SimpleNamespace(execute=lambda *args, **kwargs: {}),
            provider=SequencedUsageProvider(),
        )

        executor._chat_with_usage("first")
        executor._chat_with_usage("second")

        self.assertEqual(executor._total_usage["total_tokens"], 370)
        self.assertEqual(executor._total_usage["model_calls"], 2)
        self.assertEqual(executor._total_usage["peak_context_tokens"], 260)


if __name__ == "__main__":
    unittest.main()
