#!/usr/bin/env python3
"""Tests for web chat usage metadata enrichment."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

from server_package_utils import load_server_package


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
load_server_package("jarvis_web_test_server", PROJECT_ROOT / "jarvis-web" / "server")

from jarvis_web_test_server.services.usage_metadata import (  # noqa: E402
    enrich_usage_metadata,
    format_usage_markdown,
)
from jarvis_web_test_server.services.conversation_store import ConversationStore  # noqa: E402


class EnrichUsageMetadataTests(unittest.TestCase):
    def test_adds_provider_and_model_without_overwriting(self):
        usage = enrich_usage_metadata(
            {"input_tokens": 10, "provider": "xai"},
            provider="anthropic",
            model="claude-sonnet-5",
            mode="cloud",
        )
        self.assertEqual(usage["provider"], "xai")
        self.assertEqual(usage["model"], "claude-sonnet-5")
        self.assertEqual(usage["mode"], "cloud")

    def test_fills_missing_provider_model(self):
        usage = enrich_usage_metadata(
            {"input_tokens": 10, "cache_read_tokens": 500},
            provider="anthropic",
            model="claude-sonnet-5",
        )
        self.assertEqual(usage["provider"], "anthropic")
        self.assertEqual(usage["model"], "claude-sonnet-5")
        self.assertEqual(usage["cache_read_tokens"], 500)

    def test_returns_none_for_empty_usage(self):
        self.assertIsNone(enrich_usage_metadata(None, provider="xai", model="grok-4.3"))

    def test_markdown_describes_per_response_identity_and_usage(self):
        lines = format_usage_markdown({
            "provider": "ollama",
            "model": "deepseek-v4-pro",
            "mode": "cloud",
            "router_prompt_version": "v1",
            "input_tokens": 27_088,
            "output_tokens": 83,
            "model_calls": 2,
            "peak_context_tokens": 13_842,
        })

        self.assertEqual(lines[0], "**LLM:** ollama / deepseek-v4-pro (cloud)")
        self.assertEqual(lines[1], "**Router prompt:** v1")
        self.assertIn("processed 27,088 input / 83 output", lines[2])
        self.assertIn("2 model calls", lines[2])
        self.assertIn("peak context 13,842 tokens", lines[2])


class ConversationStoreLlmMetadataTests(unittest.TestCase):
    def test_update_llm_metadata_persists_on_conversation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ConversationStore(Path(tmp))
            conv = store.create_conversation(title="test")
            self.assertTrue(
                store.update_llm_metadata(conv["id"], provider="xai", model="grok-build-0.1")
            )
            loaded = store.get_conversation(conv["id"])
            self.assertEqual(loaded["llm_provider"], "xai")
            self.assertEqual(loaded["llm_model"], "grok-build-0.1")


class ImportConversationMetadataTests(unittest.TestCase):
    def test_import_preserves_llm_metadata_and_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ConversationStore(Path(tmp))
            source = store.create_conversation(title="export me")
            store.update_llm_metadata(source["id"], provider="anthropic", model="claude-sonnet-5")
            store.add_message(
                source["id"],
                "assistant",
                "hello",
                data={
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "total_tokens": 120,
                        "provider": "anthropic",
                        "model": "claude-sonnet-5",
                        "mode": "cloud",
                        "router_prompt_version": "v1",
                        "model_calls": 2,
                        "peak_context_tokens": 3_400,
                        "cache_read_tokens": 5000,
                    }
                },
            )
            exported = store.get_conversation(source["id"])

            imported = store.create_conversation(title=exported.get("title", "Imported"))
            conv = store.get_conversation(imported["id"])
            conv["messages"] = [
                {
                    "id": "abc12345",
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", ""),
                    "timestamp": msg.get("timestamp"),
                    "data": msg.get("data"),
                    "tools_used": msg.get("tools_used", []),
                }
                for msg in exported.get("messages", [])
            ]
            if exported.get("llm_provider"):
                conv["llm_provider"] = exported["llm_provider"]
            if exported.get("llm_model"):
                conv["llm_model"] = exported["llm_model"]
            conv_file = store.conversations_dir / f"{imported['id']}.json"
            with open(conv_file, "w") as handle:
                json.dump(conv, handle, indent=2)

            loaded = store.get_conversation(imported["id"])
            self.assertEqual(loaded["llm_provider"], "anthropic")
            self.assertEqual(loaded["llm_model"], "claude-sonnet-5")
            usage = loaded["messages"][0]["data"]["usage"]
            self.assertEqual(usage["cache_read_tokens"], 5000)
            self.assertEqual(usage["provider"], "anthropic")
            self.assertEqual(usage["mode"], "cloud")
            self.assertEqual(usage["router_prompt_version"], "v1")
            self.assertEqual(usage["model_calls"], 2)
            self.assertEqual(usage["peak_context_tokens"], 3_400)


if __name__ == "__main__":
    unittest.main()
