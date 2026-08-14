#!/usr/bin/env python3
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.join(ROOT, "orchestrator"))
sys.path.insert(0, os.path.join(ROOT, "skills"))

import tool_search as tool_search_script  # noqa: E402
from context_assembler import ContextAssembler  # noqa: E402
from tool_schema import ToolSchema, _merged_ghost_tool_names  # noqa: E402
from tool_logger import ToolLogger  # noqa: E402
from tool_search_runtime import search_tools_runtime  # noqa: E402


class _FakeRegistry:
    def __init__(self, tools):
        self.tools = {tool.name: tool for tool in tools}

    def get_tool(self, name):
        return self.tools.get(name)


class _FakeDB:
    def __init__(self, results, *, fallback_embeddings=None):
        self.results = results
        self.last_query = None
        self.last_limit = None
        self.last_threshold = None
        self.last_tool_search_meta = {
            "fallback_embeddings": fallback_embeddings,
        }

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

    def test_semantic_fallback_reaches_structured_tool_log(self):
        db = _FakeDB(
            [{"name": "weather", "similarity": 0.88}],
            fallback_embeddings=True,
        )
        with patch("tool_search_runtime.get_memory_db", return_value=db):
            result = search_tools_runtime(
                registry=self.registry,
                query="forecast weather",
                limit=5,
            )

        self.assertIs(result["fallback_embeddings"], True)
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

        self.assertIs(entry["fallback_embeddings"], True)

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
                        "execute_bash",
                        "network_tools",
                        "speaker_volume",
                        "system_monitor",
                    ],
                    "tool_results": {
                        "execute_bash": {
                            "exit_code": 0,
                            "stdout_excerpt": "ok \"quoted\"\nnext line",
                            "stderr_excerpt": "",
                        },
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

        self.assertEqual(serialized_tools["execute_bash"]["exit_code"], 0)
        self.assertEqual(
            serialized_tools["execute_bash"]["stdout_excerpt"],
            "ok \"quoted\"\nnext line",
        )
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
        self.assertNotIn("stderr_excerpt", serialized_tools["execute_bash"])
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
