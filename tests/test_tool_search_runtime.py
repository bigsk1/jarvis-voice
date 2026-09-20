#!/usr/bin/env python3
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from itertools import product
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.join(ROOT, "orchestrator"))
sys.path.insert(0, os.path.join(ROOT, "skills"))

import tool_search as tool_search_script  # noqa: E402
from context_assembler import ContextAssembler  # noqa: E402
from tool_logger import ToolLogger  # noqa: E402
from tool_schema import (  # noqa: E402
    ToolRegistry,
    ToolSchema,
    _merged_ghost_tool_names,
    _select_tool_candidates,
)
from tool_search_runtime import search_tools_runtime  # noqa: E402


class _FakeRegistry:
    def __init__(self, tools):
        self.tools = {tool.name: tool for tool in tools}

    def get_tool(self, name):
        return self.tools.get(name)


class _FakeDB:
    def __init__(
        self,
        results,
        *,
        retrieval_mode="hybrid",
        semantic_disabled_reason=None,
    ):
        self.results = results
        self.last_query = None
        self.last_limit = None
        self.last_threshold = None
        self.last_tool_search_meta = {
            "retrieval_mode": retrieval_mode,
            "semantic_disabled_reason": semantic_disabled_reason,
        }

    def search_tools(self, query, limit=5, threshold=0.0):
        self.last_query = query
        self.last_limit = limit
        self.last_threshold = threshold
        return self.results[:limit]

    def close(self):
        return None


class _QueryAwareFakeDB(_FakeDB):
    def __init__(self, results_by_query):
        super().__init__([], retrieval_mode="hybrid")
        self.results_by_query = results_by_query
        self.queries = []

    def search_tools(self, query, limit=5, threshold=0.0):
        self.queries.append(query)
        self.last_query = query
        self.last_limit = limit
        self.last_threshold = threshold
        self.last_tool_search_meta = {
            "retrieval_mode": "hybrid",
            "semantic_disabled_reason": None,
            "dense_candidate_count": 12,
            "keyword_candidate_count": 4,
            "fused_candidate_count": len(self.results_by_query.get(query, [])),
        }
        return self.results_by_query.get(query, [])[:limit]


class ToolSearchRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.weather = ToolSchema(
            name="weather",
            description="Get current weather and forecast for a location.",
            parameters={
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City name or place"},
                    "duration": {"type": "integer", "description": "Forecast day count"},
                },
                "required": ["location"],
            },
            script_path="skills/weather.py",
        )
        self.send_email = ToolSchema(
            name="send_email",
            description="Send an email with a recipient, subject, and body.",
            parameters={
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Email recipient"},
                    "subject": {"type": "string", "description": "Email subject"},
                },
                "required": ["to", "subject"],
            },
            script_path="skills/send_email.py",
        )
        self.search_memory = ToolSchema(
            name="search_memory",
            description="Search memory entries with keyword matching.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keyword search text"},
                },
                "required": ["query"],
            },
            script_path="skills/search_memory.py",
        )
        self.tool_search = ToolSchema(
            name="tool_search",
            description="Discover enabled tools.",
            parameters={"type": "object", "properties": {}},
            script_path="skills/tool_search.py",
        )
        self.registry = _FakeRegistry([self.weather, self.send_email, self.search_memory, self.tool_search])

    def test_standalone_entrypoint_loads_selected_mode_before_search(self):
        output = StringIO()
        result = {"ok": True, "data": {"matches": []}}
        with patch.dict(os.environ, {"JARVIS_MODE": "cloud"}, clear=False), patch.object(
            sys,
            "argv",
            ["tool_search.py", json.dumps({"query": "yard maintenance"})],
        ), patch.object(tool_search_script, "load_config") as load_config, patch.object(
            tool_search_script,
            "get_tool_registry",
            return_value=self.registry,
        ) as get_registry, patch.object(
            tool_search_script,
            "search_tools_runtime",
            return_value=result,
        ) as search, redirect_stdout(output):
            exit_code = tool_search_script.main()

        self.assertEqual(exit_code, 0)
        load_config.assert_called_once_with("cloud")
        get_registry.assert_called_once_with(mode="cloud")
        self.assertEqual(search.call_args.kwargs["query"], "yard maintenance")
        self.assertEqual(json.loads(output.getvalue()), result)

    def test_semantic_search_excludes_self_and_request_exclusions(self):
        db = _FakeDB(
            [
                {"name": "tool_search", "similarity": 0.99},
                {"name": "search_memory", "similarity": 0.97},
                {"name": "weather", "similarity": 0.88},
                {"name": "send_email", "similarity": 0.44},
            ]
        )
        with patch("tool_search_runtime.get_memory_db", return_value=db):
            result = search_tools_runtime(
                registry=self.registry,
                query="forecast weather",
                excluded_tools={"send_email"},
                limit=5,
            )

        names = [item["name"] for item in result["data"]["matches"]]
        self.assertEqual(names, ["weather"])
        self.assertEqual(result["data"]["selected_tool_hints"], ["weather"])
        self.assertEqual(result["data"]["search_space"], 1)

    def test_semantic_disabled_reason_reaches_structured_tool_log(self):
        db = _FakeDB(
            [{"name": "weather"}],
            retrieval_mode="keyword_fallback",
            semantic_disabled_reason="embedding fingerprint mismatch",
        )
        with patch("tool_search_runtime.get_memory_db", return_value=db):
            result = search_tools_runtime(
                registry=self.registry,
                query="forecast weather",
                limit=5,
            )

        self.assertEqual(result["retrieval_mode"], "keyword_fallback")
        self.assertEqual(result["data"]["search_mode"], "keyword_fallback")
        self.assertNotIn("fallback_embeddings", result)
        self.assertNotIn(
            "fallback_embeddings",
            result["data"]["embedding_diagnostics"],
        )
        self.assertEqual(
            result["semantic_disabled_reason"],
            "embedding fingerprint mismatch",
        )
        with tempfile.TemporaryDirectory() as log_dir:
            logger = ToolLogger(log_dir=log_dir)
            logger.log_tool_call(
                tool_name="tool_search",
                arguments={"query": "forecast weather"},
                result=result,
                duration_ms=12.0,
                mode="cloud",
            )
            entry = logger.get_recent_logs(limit=1)[0]

        self.assertEqual(entry["retrieval_mode"], "keyword_fallback")
        self.assertEqual(
            entry["semantic_disabled_reason"],
            "embedding fingerprint mismatch",
        )

    def test_registry_failure_returns_ghost_tools_instead_of_all_tools(self):
        registry = ToolRegistry.__new__(ToolRegistry)
        registry.tools = {
            self.search_memory.name: self.search_memory,
            self.weather.name: self.weather,
        }
        registry.last_tool_search_meta = {}

        with patch(
            "memory_db.get_memory_db",
            side_effect=RuntimeError("embedding host unavailable"),
        ):
            tools = registry.find_tools("forecast weather", limit=5)

        self.assertEqual([tool.name for tool in tools], ["search_memory"])
        self.assertEqual(
            registry.last_tool_search_meta["retrieval_mode"],
            "ghost_only",
        )
        self.assertEqual(
            registry.last_tool_search_meta["semantic_disabled_reason"],
            "embedding host unavailable",
        )

    def test_registry_adaptively_trims_dynamic_tail_but_keeps_ghosts(self):
        registry = ToolRegistry.__new__(ToolRegistry)
        workflow = ToolSchema(
            name="workflow",
            description="Discover and run workflows.",
            parameters={"type": "object", "properties": {}},
            script_path="skills/workflow.py",
        )
        registry.tools = {
            tool.name: tool
            for tool in (
                self.search_memory,
                self.tool_search,
                workflow,
                self.weather,
                self.send_email,
            )
        }
        registry.last_tool_search_meta = {}
        db = _FakeDB(
            [
                {"name": "weather", "hybrid_score": 1.0, "similarity": 0.52},
                {"name": "send_email", "hybrid_score": 0.20, "similarity": 0.31},
            ],
            retrieval_mode="hybrid",
        )

        with patch("memory_db.get_memory_db", return_value=db), patch(
            "config_loader.get_config_value", return_value="search_memory"
        ), patch("config_loader.get_float", return_value=0.28):
            tools = registry.find_tools("weather forecast", limit=5)

        self.assertEqual(
            [tool.name for tool in tools],
            ["search_memory", "tool_search", "workflow", "weather"],
        )
        self.assertEqual(
            registry.last_tool_search_meta["adaptive_selection"]["reason"],
            "dominant_top_result",
        )

    def test_registry_preserves_secondary_compound_action(self):
        registry = ToolRegistry.__new__(ToolRegistry)

        def tool(name):
            return ToolSchema(
                name=name,
                description=name.replace("_", " "),
                parameters={"type": "object", "properties": {}},
                script_path=f"skills/{name}.py",
            )

        tools = [
            self.search_memory,
            self.tool_search,
            tool("workflow"),
            tool("stock_price"),
            tool("status_recap"),
            tool("serpapi_google_news_light"),
            tool("gpu_hot_status"),
        ]
        registry.tools = {item.name: item for item in tools}
        registry.last_tool_search_meta = {}

        query = "Look up NVIDIA stock price and the latest news about NVIDIA."
        db = _QueryAwareFakeDB(
            {
                query: [
                    {"name": "stock_price", "hybrid_score": 1.0, "similarity": 0.42},
                    {"name": "status_recap", "hybrid_score": 0.109, "similarity": 0.30},
                    {
                        "name": "serpapi_google_news_light",
                        "hybrid_score": 0.038,
                        "similarity": 0.287,
                    },
                ],
                "Look up NVIDIA stock price": [
                    {"name": "stock_price", "hybrid_score": 1.0, "similarity": 0.51},
                    {"name": "status_recap", "hybrid_score": 0.058, "similarity": 0.30},
                ],
                "the latest news about NVIDIA": [
                    {"name": "gpu_hot_status", "hybrid_score": 0.72, "similarity": 0.31},
                    {
                        "name": "serpapi_google_news_light",
                        "hybrid_score": 0.503,
                        "similarity": 0.289,
                    },
                ],
            }
        )

        with patch("memory_db.get_memory_db", return_value=db), patch(
            "config_loader.get_config_value", return_value="search_memory"
        ), patch("config_loader.get_float", return_value=0.28), patch(
            "tool_schema.expand_tool_rag_query_for_typo_hints",
            side_effect=lambda text, *_args, **_kwargs: (text, []),
        ):
            selected = registry.find_tools(query, limit=15)

        names = [item.name for item in selected]
        self.assertIn("stock_price", names)
        self.assertIn("serpapi_google_news_light", names)
        self.assertNotIn("status_recap", names)
        self.assertEqual(
            registry.last_tool_search_meta["compound_segments"],
            [
                "Look up NVIDIA stock price",
                "the latest news about NVIDIA",
            ],
        )
        self.assertIn(
            "serpapi_google_news_light",
            registry.last_tool_search_meta["segment_supported_tools"],
        )

    def test_youtube_summary_keeps_both_actions_and_the_full_request_url(self):
        query = "Get this YouTube video and summarize it https://www.youtube.com/watch?v=4JofSJIrjwU"
        registry = ToolRegistry.__new__(ToolRegistry)
        names = ["youtube_video", "serpapi_youtube", "serpapi_youtube_search", "text_summarizer"]
        registry.tools = {
            name: ToolSchema(name=name, description=name, parameters={}, script_path=f"{name}.py")
            for name in names
        }
        registry.tools.update({self.tool_search.name: self.tool_search, self.search_memory.name: self.search_memory})
        # Rounded scores from the live request: the full-query shortlist alone
        # loses the summarizer once the first YouTube clause is promoted.
        db = _QueryAwareFakeDB({
            query: [
                {"name": "serpapi_youtube", "hybrid_score": 0.72},
                {"name": "youtube_video", "hybrid_score": 0.65},
                {"name": "text_summarizer", "hybrid_score": 0.65},
                {"name": "serpapi_youtube_search", "hybrid_score": 0.356},
            ],
            "Get this YouTube video": [
                {"name": "youtube_video", "hybrid_score": 1.0},
                {"name": "serpapi_youtube", "hybrid_score": 0.881},
            ],
            "summarize it": [
                {"name": "text_summarizer", "hybrid_score": 1.0},
            ],
        })
        with patch("memory_db.get_memory_db", return_value=db), patch(
            "config_loader.get_config_value", return_value="search_memory"
        ), patch("tool_schema.expand_tool_rag_query_for_typo_hints", side_effect=lambda text, *_args, **_kwargs: (text, [])):
            selected = registry.find_tools(query, limit=15, similarity_threshold=0.27)

        self.assertEqual(db.queries, [query, "Get this YouTube video", "summarize it"])
        self.assertIn("youtube_video", [tool.name for tool in selected])
        self.assertIn("text_summarizer", [tool.name for tool in selected])

    def test_ghost_and_unavailable_rows_do_not_consume_action_budget(self):
        registry = ToolRegistry.__new__(ToolRegistry)
        self.weather.permissions["enabled"] = False
        registry.tools = {tool.name: tool for tool in [self.search_memory, self.tool_search, self.weather, self.send_email]}
        db = _FakeDB([
            {"name": name, "hybrid_score": 1.0 - index * 0.02}
            for index, name in enumerate([
                "stale_tool", "search_memory", "tool_search", "another_stale_tool", "weather", "send_email",
            ])
        ])
        with patch("memory_db.get_memory_db", return_value=db), patch(
            "config_loader.get_config_value", return_value="search_memory"
        ), patch("tool_schema.expand_tool_rag_query_for_typo_hints", side_effect=lambda text, *_args, **_kwargs: (text, [])):
            selected = registry.find_tools("send the report", limit=15, similarity_threshold=0.27)

        self.assertEqual([tool.name for tool in selected], ["search_memory", "tool_search", "send_email"])
        self.assertEqual(registry.last_tool_search_meta["adaptive_selection"]["selected_count"], 1)

    def test_pasted_youtube_link_supplements_the_action_within_normal_and_tight_caps(self):
        registry = ToolRegistry.__new__(ToolRegistry)
        names = ["youtube_video", "youtube_transcript", "serpapi_youtube", "text_summarizer", "workflow"]
        registry.tools = {
            name: ToolSchema(name=name, description=name, parameters={}, script_path=f"{name}.py")
            for name in names
        }
        registry.tools.update({self.tool_search.name: self.tool_search, self.search_memory.name: self.search_memory})
        for url in [
            "https://www.youtube.com/watch?v=4JofSJIrjwU",
            "youtu.be/4JofSJIrjwU",
            "youtube.com/watch?v=4JofSJIrjwU",
            "m.youtube.com/watch?v=4JofSJIrjwU",
        ]:
            for limit in [4, 6, 15]:
                with self.subTest(url=url, limit=limit):
                    query = f"Get this {url} and summarize it"
                    # Rounded live HTTPS scores: the primary query has no
                    # youtube_video candidate. Its source clause must supply it.
                    db = _QueryAwareFakeDB({
                        query: [
                            {"name": "serpapi_youtube", "hybrid_score": 0.72, "similarity": 0.317},
                            {"name": "text_summarizer", "hybrid_score": 0.65},
                            {"name": "youtube_transcript", "hybrid_score": 0.238, "similarity": 0.285},
                        ],
                        f"Get this {url}": [
                            {"name": "youtube_video", "hybrid_score": 0.72, "similarity": 0.323},
                            {"name": "youtube_transcript", "hybrid_score": 0.670, "similarity": 0.320},
                        ],
                        "summarize it": [{"name": "text_summarizer", "hybrid_score": 1.0, "similarity": 0.398}],
                    })
                    with patch("memory_db.get_memory_db", return_value=db), patch(
                        "config_loader.get_config_value", return_value="search_memory"
                    ), patch(
                        "tool_schema.expand_tool_rag_query_for_typo_hints",
                        side_effect=lambda text, *_args, **_kwargs: (text, []),
                    ):
                        selected = registry.find_tools(query, limit=limit, similarity_threshold=0.27)
                    self.assertEqual(db.queries, [query, f"Get this {url}", "summarize it"])
                    selected_names = [tool.name for tool in selected]
                    self.assertIn("youtube_video", selected_names)
                    self.assertIn("text_summarizer", selected_names)
                    self.assertLessEqual(
                        registry.last_tool_search_meta["adaptive_selection"]["selected_count"],
                        min(5, limit - 2),
                    )

    def test_weaker_clause_winners_do_not_displace_stronger_full_query_matches(self):
        primary = [
            {"name": name, "hybrid_score": score}
            for name, score in [
                ("youtube_video", 0.99), ("text_summarizer", 0.98), ("send_email", 0.96),
                ("serpapi_youtube", 0.4), ("status_recap", 0.3),
            ]
        ]
        segments = [
            ("Get this YouTube video", [
                {"name": "serpapi_youtube", "hybrid_score": 0.85},
                {"name": "youtube_video", "hybrid_score": 0.84},
            ]),
            ("summarize it", [
                {"name": "status_recap", "hybrid_score": 0.83},
                {"name": "text_summarizer", "hybrid_score": 0.82},
            ]),
            ("email the summary", [{"name": "send_email", "hybrid_score": 0.8}]),
        ]
        for budget in [0, 1, 2, 3, 5]:
            for clause_order in [segments, list(reversed(segments))]:
                with self.subTest(budget=budget, clause_order=[clause for clause, _ in clause_order]):
                    selected, meta, _ = _select_tool_candidates(
                        primary, clause_order, budget=budget,
                        enabled_names={row["name"] for row in primary}, ghost_tools=[],
                    )
                    names = [row["name"] for row in selected]
                    self.assertEqual(names, [row["name"] for row in primary[:budget]])
                    self.assertEqual(meta["selected_count"], len(names))

    def test_source_verbs_and_paste_separators_retrieve_both_action_tools(self):
        registry = ToolRegistry.__new__(ToolRegistry)
        registry.tools = {
            name: ToolSchema(name=name, description=name, parameters={}, script_path=f"{name}.py")
            for name in ["youtube_video", "text_summarizer", "serpapi_youtube", "workflow", "tool_search"]
        }
        url = "https://youtu.be/abc123"
        # The full query favors search and cannot supply the desired pair.
        # Both clause lookups must contribute to recover source + summarizer.
        for prefix, separator in product(
            ["", "Get this ", "Open this ", "Watch ", "Download ", "Fetch "],
            [" and ", " then ", ", ", ": ", "; ", ". ", "\n"],
        ):
            with self.subTest(prefix=prefix, separator=separator):
                source = f"{prefix}{url}"
                query = f"{source}{separator}summarize it"
                db = _QueryAwareFakeDB({
                    query: [{"name": "serpapi_youtube", "hybrid_score": 0.65}],
                    source: [{"name": "youtube_video", "hybrid_score": 0.72}],
                    "summarize it": [{"name": "text_summarizer", "hybrid_score": 1.0}],
                })
                with patch("memory_db.get_memory_db", return_value=db), patch(
                    "config_loader.get_config_value", return_value=""
                ), patch(
                    "tool_schema.expand_tool_rag_query_for_typo_hints",
                    side_effect=lambda text, *_args, **_kwargs: (text, []),
                ):
                    selected = registry.find_tools(query, limit=4, similarity_threshold=0.27)
                names = {tool.name for tool in selected}
                self.assertTrue({"youtube_video", "text_summarizer"}.issubset(names))
                self.assertNotIn("serpapi_youtube", names)
                self.assertEqual(db.queries[0], query)

    def test_reaction_clause_cannot_promote_junk_tools_or_hide_later_actions(self):
        registry = ToolRegistry.__new__(ToolRegistry)
        registry.tools = {
            name: ToolSchema(name=name, description=name, parameters={}, script_path=f"{name}.py")
            for name in ["youtube_video", "text_summarizer", "send_email", "crazy_taxi_tool", "pdf_read", "workflow", "tool_search"]
        }
        url = "https://youtu.be/abc123"
        query = f"{url}. Crazy right? Summarize it and email the summary. Thanks!"
        db = _QueryAwareFakeDB({
            query: [{"name": "youtube_video", "hybrid_score": 0.90}],
            url: [{"name": "youtube_video", "hybrid_score": 0.90}],
            "Summarize it": [{"name": "text_summarizer", "hybrid_score": 0.89}],
            "email the summary": [{"name": "send_email", "hybrid_score": 0.88}],
            "Crazy right": [
                {"name": "crazy_taxi_tool", "hybrid_score": 1.0},
                {"name": "pdf_read", "hybrid_score": 0.99},
            ],
        })
        with patch("memory_db.get_memory_db", return_value=db), patch(
            "config_loader.get_config_value", return_value=""
        ), patch(
            "tool_schema.expand_tool_rag_query_for_typo_hints",
            side_effect=lambda text, *_args, **_kwargs: (text, []),
        ):
            selected = registry.find_tools(query, limit=5, similarity_threshold=0.27)
        names = {tool.name for tool in selected}
        self.assertTrue({"youtube_video", "text_summarizer", "send_email"}.issubset(names))
        self.assertTrue(names.isdisjoint({"crazy_taxi_tool", "pdf_read"}))
        self.assertEqual(db.queries, [query, url, "Summarize it", "email the summary"])

    def test_weak_clause_does_not_override_a_dominant_match_or_its_diagnostics(self):
        primary = [
            {"name": "text_summarizer", "hybrid_score": 1.0},
            {"name": "pdf_read", "hybrid_score": 0.1},
        ]
        for clause in ["Read", "S", "v2"]:
            with self.subTest(clause=clause):
                selected, meta, _ = _select_tool_candidates(
                    primary, [(clause, [{"name": "pdf_read", "hybrid_score": 0.2}])], budget=3,
                    enabled_names={row["name"] for row in primary}, ghost_tools=[],
                )
                self.assertEqual([row["name"] for row in selected], ["text_summarizer"])
                self.assertEqual(meta["reason"], "dominant_top_result")
                self.assertEqual(meta["selected_count"], 1)

    def test_registry_promotes_general_web_search_from_compound_clause(self):
        registry = ToolRegistry.__new__(ToolRegistry)

        def tool(name):
            return ToolSchema(
                name=name,
                description=name.replace("_", " "),
                parameters={"type": "object", "properties": {}},
                script_path=f"skills/{name}.py",
            )

        dynamic_names = [
            "semantic_recall",
            "recall",
            "deep_memory_search",
            "generate_image",
            "serpapi_google_trending_now",
            "serpapi_search_index",
        ]
        tools = [
            self.search_memory,
            self.tool_search,
            tool("workflow"),
            *(tool(name) for name in dynamic_names),
        ]
        registry.tools = {item.name: item for item in tools}
        registry.last_tool_search_meta = {}

        query = (
            "Search Google for EmbeddingGemma retrieval prompts and give me "
            "the top findings."
        )
        db = _QueryAwareFakeDB(
            {
                query: [
                    {"name": "semantic_recall", "hybrid_score": 0.72, "similarity": 0.435},
                    {"name": "search_memory", "hybrid_score": 0.604, "similarity": 0.410},
                    {"name": "recall", "hybrid_score": 0.521, "similarity": 0.392},
                    {"name": "deep_memory_search", "hybrid_score": 0.437, "similarity": 0.374},
                    {"name": "generate_image", "hybrid_score": 0.336, "similarity": 0.352},
                    {
                        "name": "serpapi_search_index",
                        "hybrid_score": 0.289,
                        "similarity": 0.342,
                    },
                ],
                "Search Google for EmbeddingGemma retrieval prompts": [],
                "give me the top findings": [
                    {
                        "name": "serpapi_google_trending_now",
                        "hybrid_score": 0.72,
                        "similarity": 0.351,
                    },
                    {
                        "name": "serpapi_search_index",
                        "hybrid_score": 0.699,
                        "similarity": 0.349,
                    },
                ],
            }
        )

        with patch("memory_db.get_memory_db", return_value=db), patch(
            "config_loader.get_config_value", return_value="search_memory"
        ), patch("config_loader.get_float", return_value=0.28), patch(
            "tool_schema.expand_tool_rag_query_for_typo_hints",
            side_effect=lambda text, *_args, **_kwargs: (text, []),
        ):
            selected = registry.find_tools(query, limit=15)

        names = [item.name for item in selected]
        self.assertIn("serpapi_search_index", names)
        self.assertNotIn("generate_image", names)

    def test_exact_lookup_can_include_schema(self):
        result = search_tools_runtime(
            registry=self.registry,
            tool_names=["search_memory", "weather", "tool_search", "missing_tool"],
            include_schema=True,
            limit=5,
        )

        self.assertEqual(result["data"]["search_mode"], "exact")
        self.assertEqual(result["data"]["selected_tool_hints"], ["search_memory", "weather"])
        match = result["data"]["matches"][0]
        self.assertEqual(match["name"], "search_memory")
        self.assertIn("parameters_schema", match)
        self.assertEqual(match["required_parameters"], ["query"])

    def test_invalid_limit_falls_back_to_default_range(self):
        db = _FakeDB([{"name": "weather", "similarity": 0.88}])
        with patch("tool_search_runtime.get_memory_db", return_value=db):
            result = search_tools_runtime(
                registry=self.registry,
                query="forecast weather",
                limit="eight",
            )

        self.assertEqual(db.last_limit, 24)
        self.assertEqual(result["data"]["count"], 1)
        self.assertEqual(result["data"]["selected_tool_hints"], ["weather"])

    def test_browse_excludes_ghost_tools(self):
        result = search_tools_runtime(
            registry=self.registry,
            query="",
            limit=10,
        )

        names = [item["name"] for item in result["data"]["matches"]]
        self.assertEqual(names, ["send_email", "weather"])
        self.assertEqual(result["data"]["search_space"], 2)

    def test_mandatory_ghost_tools_follow_effective_registry(self):
        names = _merged_ghost_tool_names(
            "search_memory,remember",
            {"tool_search", "workflow", "weather"},
        )
        self.assertEqual(names, ["search_memory", "remember", "tool_search", "workflow"])

        profile_disabled = _merged_ghost_tool_names(
            "search_memory,remember",
            {"tool_search", "weather"},
        )
        self.assertEqual(profile_disabled, ["search_memory", "remember", "tool_search"])

    def test_turn_context_surfaces_selected_tool_hints_from_tool_search(self):
        assembler = ContextAssembler(
            timezone_obj=ZoneInfo("UTC"),
            auto_context_window=3,
            auto_context_minutes=10,
            safe_iso_to_local_datetime=lambda value: datetime.fromisoformat(value) if value else None,
            format_age_seconds=lambda value: "0s" if value is not None else "n/a",
            format_gap_for_prompt=lambda value: "0s" if value is not None else "n/a",
            conversation_has_text_summary_for_ref=lambda ctx, ref: False,
            stash_ref_from_result=lambda data, args: "",
            get_memory_db_fn=lambda: None,
            now_utc_fn=lambda: datetime.now(ZoneInfo("UTC")),
            parse_utc_timestamp_fn=lambda value: datetime.fromisoformat(value),
        )

        context = assembler.build_turn_context(
            "help me find the right tool",
            [
                {
                    "tool": "tool_search",
                    "result": {
                        "ok": True,
                        "speech": "I found 2 matching tools.",
                        "data": {
                            "selected_tool_hints": ["weather", "send_email"],
                            "matches": [],
                        },
                    },
                    "meta": {
                        "executed_at_iso": "2026-04-28T12:00:00+00:00",
                        "executed_at_local": "2026-04-28 12:00:00 UTC",
                        "ttl_seconds": None,
                        "source": "tool",
                        "authoritative_live": False,
                    },
                }
            ],
        )

        self.assertIn("Selected tool hints: weather, send_email.", context)
        self.assertIn("eligible for direct calls on the next turn", context)

    def test_conversation_context_preserves_false_and_zero_tool_values(self):
        assembler = ContextAssembler(
            timezone_obj=ZoneInfo("UTC"),
            auto_context_window=3,
            auto_context_minutes=10,
            safe_iso_to_local_datetime=lambda value: datetime.fromisoformat(value) if value else None,
            format_age_seconds=lambda value: "0s" if value is not None else "n/a",
            format_gap_for_prompt=lambda value: "0s" if value is not None else "n/a",
            conversation_has_text_summary_for_ref=lambda ctx, ref: False,
            stash_ref_from_result=lambda data, args: "",
            get_memory_db_fn=lambda: None,
            now_utc_fn=lambda: datetime.now(ZoneInfo("UTC")),
            parse_utc_timestamp_fn=lambda value: datetime.fromisoformat(value),
        )

        context = assembler.format_conversation_context(
            "What did those checks find?",
            [
                {
                    "role": "assistant",
                    "content": "The checks completed.",
                    "tools_used": [
                        "network_tools",
                        "speaker_volume",
                        "system_monitor",
                    ],
                    "tool_results": {
                        "network_tools": {
                            "packet_loss_percent": 0.0,
                            "legacy_nan": float("nan"),
                        },
                        "speaker_volume": {"volume": 0, "muted": False},
                        "system_monitor": {
                            "issue_count": 0,
                            "issues": [],
                            "details": {},
                            "note": None,
                        },
                    },
                }
            ],
        )

        serialized_tools = {}
        for line in context.splitlines():
            if not line.startswith("  └─ ") or " data: " not in line:
                continue
            tool_label, payload = line.removeprefix("  └─ ").split(" data: ", 1)
            serialized_tools[tool_label] = json.loads(payload)

        self.assertEqual(
            serialized_tools["network_tools"]["packet_loss_percent"],
            0.0,
        )
        self.assertIn(
            "non-finite number normalized for follow-up context",
            serialized_tools["network_tools"]["legacy_nan"],
        )
        self.assertEqual(serialized_tools["speaker_volume"]["volume"], 0)
        self.assertIs(serialized_tools["speaker_volume"]["muted"], False)
        self.assertEqual(serialized_tools["system_monitor"]["issue_count"], 0)
        self.assertNotIn("issues", serialized_tools["system_monitor"])
        self.assertNotIn("details", serialized_tools["system_monitor"])
        self.assertNotIn("note", serialized_tools["system_monitor"])

    def test_turn_context_marks_completed_workflow_recipe_as_authoritative(self):
        assembler = ContextAssembler(
            timezone_obj=ZoneInfo("UTC"),
            auto_context_window=3,
            auto_context_minutes=10,
            safe_iso_to_local_datetime=lambda value: datetime.fromisoformat(value) if value else None,
            format_age_seconds=lambda value: "0s" if value is not None else "n/a",
            format_gap_for_prompt=lambda value: "0s" if value is not None else "n/a",
            conversation_has_text_summary_for_ref=lambda ctx, ref: False,
            stash_ref_from_result=lambda data, args: "",
            get_memory_db_fn=lambda: None,
            now_utc_fn=lambda: datetime.now(ZoneInfo("UTC")),
            parse_utc_timestamp_fn=lambda value: datetime.fromisoformat(value),
        )

        context = assembler.build_turn_context(
            "research AI agents",
            [
                {
                    "tool": "workflow",
                    "arguments": {"action": "run", "workflow_id": "deep_research"},
                    "result": {
                        "ok": True,
                        "speech": "Research complete.",
                        "data": {
                            "action": "run",
                            "workflow_id": "deep_research",
                            "component_tools_used": ["crawl_url", "canvas"],
                        },
                    },
                    "meta": {
                        "executed_at_iso": "2026-04-28T12:00:00+00:00",
                        "executed_at_local": "2026-04-28 12:00:00 UTC",
                        "ttl_seconds": None,
                        "source": "tool",
                        "authoritative_live": False,
                    },
                }
            ],
        )

        self.assertIn("deterministic recipe already completed", context)
        self.assertIn("Component tools already executed: crawl_url, canvas.", context)


if __name__ == "__main__":
    unittest.main()
