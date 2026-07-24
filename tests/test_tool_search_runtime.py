#!/usr/bin/env python3
import os
import sys
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.join(ROOT, "orchestrator"))

from context_assembler import ContextAssembler  # noqa: E402
from tool_schema import ToolSchema, _merged_ghost_tool_names  # noqa: E402
from tool_search_runtime import search_tools_runtime  # noqa: E402


class _FakeRegistry:
    def __init__(self, tools):
        self.tools = {tool.name: tool for tool in tools}

    def get_tool(self, name):
        return self.tools.get(name)


class _FakeDB:
    def __init__(self, results):
        self.results = results
        self.last_query = None
        self.last_limit = None
        self.last_threshold = None

    def search_tools(self, query, limit=5, threshold=0.0):
        self.last_query = query
        self.last_limit = limit
        self.last_threshold = threshold
        return self.results[:limit]

    def close(self):
        return None


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
