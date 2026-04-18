#!/usr/bin/env python3
"""
Regression tests for OpenAI tool schema sanitizing.

Run:
    python3 tests/test_openai_tool_schema.py
"""

import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from lib.tool_schema import ToolSchema, _sanitize_schema_for_openai


class OpenAIToolSchemaTests(unittest.TestCase):
    def test_sanitizes_memory_deduper_top_level_allof(self):
        tool_path = PROJECT_ROOT / "skills" / "memory_deduper.tool.json"
        with tool_path.open("r") as f:
            payload = json.load(f)

        schema = ToolSchema(
            name=payload["name"],
            description=payload["description"],
            parameters=payload["parameters"],
            script_path="memory_deduper.py",
        )

        openai_tool = schema.to_openai_format()
        params = openai_tool["function"]["parameters"]

        self.assertEqual(params["type"], "object")
        self.assertIn("properties", params)
        self.assertNotIn("allOf", params)
        self.assertNotIn("anyOf", params)
        self.assertNotIn("oneOf", params)

    def test_root_schema_defaults_to_object(self):
        params = _sanitize_schema_for_openai({"properties": {"x": {"type": "string"}}}, is_root=True)
        self.assertEqual(params["type"], "object")
        self.assertIn("properties", params)

    def test_collapses_simple_anyof_consts_to_enum(self):
        params = _sanitize_schema_for_openai({
            "type": "object",
            "properties": {
                "safesearch": {
                    "anyOf": [
                        {"type": "string", "const": "off"},
                        {"type": "string", "const": "moderate"},
                        {"type": "string", "const": "strict"},
                    ]
                }
            }
        }, is_root=True)

        prop = params["properties"]["safesearch"]
        self.assertEqual(prop["type"], "string")
        self.assertEqual(prop["enum"], ["off", "moderate", "strict"])
        self.assertNotIn("anyOf", prop)

    def test_preserves_type_for_anyof_with_generic_branch(self):
        params = _sanitize_schema_for_openai({
            "type": "object",
            "properties": {
                "freshness": {
                    "description": "Date freshness shortcut or date range.",
                    "anyOf": [
                        {"type": "string", "const": "pd"},
                        {"type": "string", "const": "pw"},
                        {"type": "string"},
                    ]
                }
            }
        }, is_root=True)

        prop = params["properties"]["freshness"]
        self.assertEqual(prop["type"], "string")
        self.assertNotIn("enum", prop)
        self.assertNotIn("anyOf", prop)


if __name__ == "__main__":
    unittest.main()
