#!/usr/bin/env python3
"""
Regression tests for workflow placeholder resolution.

Run:
    python3 tests/test_pipeline_executor.py
"""

import json
import os
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


class EnvCapturingProvider:
    def __init__(self):
        self.enable_search = True
        self.calls = []

    def chat_with_tools(self, **kwargs):
        self.calls.append(
            {
                "enable_search": self.enable_search,
                "xai_disabled": os.environ.get("XAI_DISABLE_SERVER_SIDE_TOOLS"),
                "openai_disabled": os.environ.get("OPENAI_RESPONSES_DISABLE_SERVER_SIDE_TOOLS"),
                "xai_search_override": os.environ.get("JARVIS_OVERRIDE_XAI_SEARCH"),
                "anthropic_search_override": os.environ.get("JARVIS_OVERRIDE_ANTHROPIC_SEARCH"),
                "tools": kwargs.get("tools"),
            }
        )
        return "Solana", None, {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}, None

    def chat(self, *_args):
        raise AssertionError("chat fallback should not be used")


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
        self.assertEqual(
            executor._total_usage["billing_mode"],
            "ollama_cloud_subscription",
        )
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

    def test_workflow_can_disable_provider_native_tools_for_llm_helpers(self):
        provider = EnvCapturingProvider()
        executed = []

        previous_xai_disable = os.environ.get("XAI_DISABLE_SERVER_SIDE_TOOLS")
        os.environ["XAI_DISABLE_SERVER_SIDE_TOOLS"] = "previous"
        try:
            executor = PipelineExecutor(
                mode="cloud",
                executor=SimpleNamespace(
                    execute=lambda tool, params: executed.append((tool, params))
                    or {"ok": True, "data": {"coin_id": params["coin"]}}
                ),
                provider=provider,
            )
            result = executor.execute(
                {
                    "id": "native_tool_free_helpers",
                    "disable_server_side_tools": True,
                    "steps": [
                        {
                            "step": 1,
                            "tool": "crypto_price",
                            "params": {},
                            "llm_prompt": "Extract the second crypto coin.",
                            "extract": {"coin_id": "coin_id"},
                        }
                    ],
                },
                "/crypto bitcoin solana",
            )
            restored_xai_disable = os.environ.get("XAI_DISABLE_SERVER_SIDE_TOOLS")
        finally:
            if previous_xai_disable is None:
                os.environ.pop("XAI_DISABLE_SERVER_SIDE_TOOLS", None)
            else:
                os.environ["XAI_DISABLE_SERVER_SIDE_TOOLS"] = previous_xai_disable

        self.assertTrue(result["ok"])
        self.assertEqual(executed, [("crypto_price", {"coin": "solana"})])
        self.assertEqual(provider.calls[0]["tools"], [])
        self.assertFalse(provider.calls[0]["enable_search"])
        self.assertEqual(provider.calls[0]["xai_disabled"], "true")
        self.assertEqual(provider.calls[0]["openai_disabled"], "true")
        self.assertEqual(provider.calls[0]["xai_search_override"], "false")
        self.assertEqual(provider.calls[0]["anthropic_search_override"], "false")
        self.assertTrue(provider.enable_search)
        self.assertEqual(restored_xai_disable, "previous")

    def test_workflow_llm_helpers_leave_native_tools_enabled_by_default(self):
        provider = EnvCapturingProvider()
        executor = PipelineExecutor(
            mode="cloud",
            executor=SimpleNamespace(execute=lambda *_args, **_kwargs: {"ok": True}),
            provider=provider,
        )

        executor._chat_with_usage("probe")

        self.assertTrue(provider.calls[0]["enable_search"])

    def test_process_all_for_each_runs_every_item(self):
        calls = []

        def execute(tool, params):
            calls.append((tool, params["value"]))
            return {"ok": True, "data": {"saved": params["value"]}}

        executor = PipelineExecutor(
            mode="cloud",
            executor=SimpleNamespace(execute=execute),
            provider=None,
        )
        result = executor._execute_for_each(
            {
                "tool": "stash",
                "for_each": "${items}",
                "process_all": True,
                "params": {},
            },
            "stash",
            None,
            {},
            {"items": [{"value": "one"}, {"value": "two"}]},
            {},
            0,
            10,
        )

        self.assertEqual(calls, [("stash", "one"), ("stash", "two")])
        self.assertEqual(result["items_succeeded"], 2)

    def test_for_each_respects_explicit_step_max_attempts(self):
        calls = []

        def execute(_tool, params):
            calls.append(params["url"])
            return {"ok": False, "error": "unavailable"}

        executor = PipelineExecutor(
            mode="cloud",
            executor=SimpleNamespace(execute=execute),
            provider=None,
        )
        result = executor._execute_for_each(
            {
                "tool": "crawl_url",
                "for_each": "${urls}",
                "params": {},
                "retry": {"max_attempts": 2, "strategy": "next_url"},
                "required_success_count": 1,
                "on_all_fail": "abort_with_message",
            },
            "crawl_url",
            None,
            {},
            {"urls": ["https://one.test", "https://two.test", "https://three.test"]},
            {},
            0,
            10,
        )

        self.assertEqual(calls, ["https://one.test", "https://two.test"])
        self.assertEqual(result["items_processed"], 2)
        self.assertEqual(result["retries"], 2)
        self.assertTrue(result["abort"])

    def test_for_each_empty_items_honors_on_all_fail_abort(self):
        executor = PipelineExecutor(
            mode="cloud",
            executor=SimpleNamespace(execute=lambda *_args, **_kwargs: {"ok": True}),
            provider=None,
        )
        step = {
            "tool": "crawl_url",
            "for_each": "${urls}",
            "on_all_fail": "abort_with_message",
            "required_success_count": 1,
        }

        empty_result = executor._execute_for_each(
            step, "crawl_url", None, {}, {"urls": []}, {}, 0, 10
        )
        self.assertTrue(empty_result["abort"])
        self.assertEqual(empty_result["validated_outputs"], [])

        missing_result = executor._execute_for_each(
            step, "crawl_url", None, {}, {}, {}, 0, 10
        )
        self.assertTrue(missing_result["abort"])

        continue_step = {**step, "on_all_fail": "continue"}
        continue_result = executor._execute_for_each(
            continue_step, "crawl_url", None, {}, {"urls": []}, {}, 0, 10
        )
        self.assertFalse(continue_result["abort"])

    def test_for_each_still_respects_workflow_retry_budget(self):
        calls = []
        executor = PipelineExecutor(
            mode="cloud",
            executor=SimpleNamespace(
                execute=lambda _tool, params: calls.append(params["url"])
                or {"ok": False}
            ),
            provider=None,
        )

        result = executor._execute_for_each(
            {
                "tool": "crawl_url",
                "for_each": "${urls}",
                "retry": {"max_attempts": 5},
            },
            "crawl_url",
            None,
            {},
            {"urls": ["https://one.test", "https://two.test"]},
            {},
            3,
            3,
        )

        self.assertEqual(calls, [])
        self.assertEqual(result["items_processed"], 0)

    def test_non_crawl_for_each_does_not_replace_validated_articles(self):
        article = {"ok": True, "data": {"results": [{"url": "https://example.test", "markdown": "source"}]}}
        variables = {"validated_articles": [article], "items": [{"value": "saved"}]}
        workflow = {
            "id": "preserve_articles",
            "steps": [
                {
                    "step": 1,
                    "tool": "stash",
                    "for_each": "${items}",
                    "process_all": True,
                    "output_var": "saved_files",
                }
            ],
        }
        executor = PipelineExecutor(
            mode="cloud",
            executor=SimpleNamespace(execute=lambda *_args, **_kwargs: {"ok": True, "data": {"saved": True}}),
            provider=None,
        )

        step = workflow["steps"][0]
        step_result = executor._execute_for_each(step, "stash", None, {}, variables, {}, 0, 10)
        executor._store_validated_outputs(step, "stash", step_result, variables)

        self.assertEqual(variables["validated_articles"], [article])
        formatted = executor._format_articles_for_llm(variables["validated_articles"])
        self.assertIn("https://example.test", formatted)
        self.assertIn("source", formatted)

    def test_builtin_research_workflows_declare_validated_article_ownership(self):
        workflows_dir = PROJECT_ROOT / "data" / "workflows"
        deep = json.loads((workflows_dir / "deep_research.json").read_text())
        crypto = json.loads((workflows_dir / "crypto_market_report.json").read_text())

        deep_crawl = next(step for step in deep["steps"] if step["tool"] == "crawl_url")
        deep_stash = next(
            step for step in deep["steps"]
            if step["tool"] == "stash" and step.get("action") == "save"
        )
        crypto_crawl = next(step for step in crypto["steps"] if step["tool"] == "crawl_url")

        self.assertTrue(crypto["disable_server_side_tools"])
        self.assertEqual(deep_crawl["validated_output_var"], "validated_articles")
        self.assertTrue(deep_stash["process_all"])
        self.assertEqual(crypto_crawl["validated_output_var"], "validated_articles")

        deep_canvas = next(step for step in deep["steps"] if step["tool"] == "canvas")
        self.assertEqual(deep_canvas["llm_output_validation"]["param"], "content")

    def test_opt_in_llm_output_validation_rejects_refusal_content(self):
        step = {
            "llm_output_validation": {
                "param": "content",
                "min_length": 20,
                "reject_patterns": ["unable to complete this research summary"],
            }
        }
        error = self.executor._validate_llm_filled_params(
            step,
            {"content": "I am unable to complete this research summary without URLs."},
        )
        self.assertIn("refusal", error)

    def test_llm_output_validation_is_opt_in(self):
        self.assertIsNone(
            self.executor._validate_llm_filled_params({}, {"content": "short"})
        )


if __name__ == "__main__":
    unittest.main()
