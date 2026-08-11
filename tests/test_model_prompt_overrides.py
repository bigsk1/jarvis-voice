#!/usr/bin/env python3
"""
Regression tests for model prompt overrides.

Run:
    python3 tests/test_model_prompt_overrides.py
"""

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from lib.model_prompt_overrides import (
    apply_prompt_override_sections,
    get_model_override_candidates,
    load_model_prompt_override,
)


class ModelPromptOverrideTests(unittest.TestCase):
    def test_candidate_generation_handles_dates_and_runtime_suffixes(self):
        candidates = get_model_override_candidates("gpt-5.4-nano-2026-03-17:cloud")
        self.assertEqual(
            candidates,
            [
                "gpt-5.4-nano-2026-03-17:cloud",
                "gpt-5.4-nano-2026-03-17",
                "gpt-5.4-nano",
            ],
        )

    def test_ollama_cloud_model_falls_back_to_base_folder(self):
        candidates = get_model_override_candidates("minimax-m3:cloud")
        self.assertEqual(candidates, ["minimax-m3:cloud", "minimax-m3"])

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            override_dir = root / "ollama" / "minimax-m3"
            override_dir.mkdir(parents=True)
            (override_dir / "prompt_overrides.yaml").write_text(
                (
                    "enabled: true\n"
                    "applies_to_modes: [cloud]\n"
                    "qa_append: |\n"
                    "  Do NOT add meta lead-ins such as Here is the condensed voice-friendly summary.\n"
                ),
                encoding="utf-8",
            )

            override = load_model_prompt_override(
                provider="ollama",
                model="minimax-m3:cloud",
                mode="cloud",
                config_root=root,
            )

            self.assertTrue(override.enabled)
            self.assertEqual(override.matched_model, "minimax-m3")
            self.assertIn("Do NOT add meta lead-ins", override.get("qa_append"))

    def test_glm_5_2_cloud_card_curbing_destructive_canvas_updates_loads(self):
        override = load_model_prompt_override(
            provider="ollama",
            model="glm-5.2:cloud",
            mode="cloud",
        )

        self.assertTrue(override.enabled)
        self.assertEqual(override.matched_model, "glm-5.2")
        self.assertIn("action=append", override.get("tool_calling_prepend"))
        self.assertIn("allow_content_shrink=true", override.get("tool_calling_prepend"))
        self.assertIn("stop tool use", override.get("routing_append"))

    def test_ollama_direct_size_tag_falls_back_to_family(self):
        candidates = get_model_override_candidates("gemma4:31b", provider="ollama")
        self.assertEqual(candidates, ["gemma4:31b", "gemma4"])

    def test_ollama_combined_cloud_tag_falls_back_to_family(self):
        candidates = get_model_override_candidates("gpt-oss:120b-cloud", provider="ollama")
        self.assertEqual(
            candidates,
            ["gpt-oss:120b-cloud", "gpt-oss:120b", "gpt-oss"],
        )

    def test_xai_canonical_release_id_falls_back_to_stable_family(self):
        candidates = get_model_override_candidates("grok-4.20-0309-non-reasoning")

        self.assertEqual(
            candidates,
            ["grok-4.20-0309-non-reasoning", "grok-4.20-non-reasoning"],
        )

    def test_grok_4_5_tool_calling_override_loads(self):
        override = load_model_prompt_override(
            provider="xai",
            model="grok-4.5",
            mode="cloud",
        )

        self.assertTrue(override.enabled)
        self.assertEqual(override.matched_model, "grok-4.5")
        self.assertIn("ABSOLUTE TOOL STOP RULE", override.get("tool_calling_prepend"))
        self.assertIn(
            "NEVER repeat a successful tool call",
            override.get("tool_calling_prepend"),
        )
        self.assertIn("result_truncated=true", override.get("tool_calling_prepend"))
        self.assertIn("STOP TOOL USE AND RESPOND", override.get("tool_calling_prepend"))
        self.assertIn("Canvas export requests", override.get("tool_calling_prepend"))
        self.assertIn("action=create", override.get("tool_calling_prepend"))
        self.assertIn("page link", override.get("tool_calling_prepend"))
        self.assertIn("serpapi_hotel_search", override.get("tool_calling_prepend"))
        self.assertIn("serpapi_yelp_search", override.get("tool_calling_prepend"))
        self.assertIn("serpapi_travel_explore", override.get("tool_calling_prepend"))
        self.assertIn("one successful structured search", override.get("tool_calling_prepend"))
        self.assertIn("Do not search workflows", override.get("tool_calling_prepend"))
        self.assertIn("hosted web search", override.get("tool_calling_prepend"))
        self.assertIn("invented month", override.get("tool_calling_prepend"))
        self.assertIn(
            "trakt_movies and tmdb_movies are independent",
            override.get("tool_calling_prepend"),
        )
        self.assertIn("image_type=all", override.get("tool_calling_prepend"))
        self.assertIn(
            "do not follow it with separate poster",
            override.get("tool_calling_prepend"),
        )
        self.assertIn("action=details once", override.get("tool_calling_prepend"))
        self.assertIn("do not call search first", override.get("tool_calling_prepend"))
        self.assertIn("one action=discover call", override.get("tool_calling_prepend"))
        self.assertIn("do not silently tighten", override.get("tool_calling_prepend"))

    def test_loads_normalized_alias_when_exact_file_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            override_dir = root / "openai" / "gpt-5.4-nano"
            override_dir.mkdir(parents=True)
            (override_dir / "prompt_overrides.yaml").write_text(
                (
                    "enabled: true\n"
                    "routing_prepend: |\n  Prefer direct links.\n"
                    "intelligence_reflection_prepend: |\n"
                    "  Avoid contradictory tool preferences.\n"
                ),
                encoding="utf-8",
            )

            override = load_model_prompt_override(
                provider="openai",
                model="gpt-5.4-nano-2026-03-17",
                mode="cloud",
                config_root=root,
            )

            self.assertTrue(override.enabled)
            self.assertEqual(override.matched_model, "gpt-5.4-nano")
            self.assertEqual(override.get("routing_prepend"), "Prefer direct links.")
            self.assertEqual(
                override.get("intelligence_reflection_prepend"),
                "Avoid contradictory tool preferences.",
            )

    def test_mode_filter_skips_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            override_dir = root / "ollama" / "qwen3"
            override_dir.mkdir(parents=True)
            (override_dir / "prompt_overrides.yaml").write_text(
                "enabled: true\napplies_to_modes: [local]\nqa_prepend: |\n  Be terse.\n",
                encoding="utf-8",
            )

            override = load_model_prompt_override(
                provider="ollama",
                model="qwen3:latest",
                mode="cloud",
                config_root=root,
            )

            self.assertFalse(override.enabled)
            self.assertEqual(override.sections, {})

    def test_invalid_yaml_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            override_dir = root / "openai" / "gpt-5.4-nano"
            override_dir.mkdir(parents=True)
            (override_dir / "prompt_overrides.yaml").write_text(
                "enabled: true\nrouting_prepend: [bad\n",
                encoding="utf-8",
            )

            override = load_model_prompt_override(
                provider="openai",
                model="gpt-5.4-nano",
                mode="cloud",
                config_root=root,
            )

            self.assertFalse(override.enabled)
            self.assertEqual(override.sections, {})

    def test_apply_prompt_sections_wraps_prompt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            override_dir = root / "openai" / "gpt-5.4-nano"
            override_dir.mkdir(parents=True)
            (override_dir / "prompt_overrides.yaml").write_text(
                "\n".join(
                    [
                        "enabled: true",
                        'routing_prepend: "Prefer direct links."',
                        'tool_calling_prepend: "Preserve exact model numbers."',
                        'routing_append: "Keep answers concrete."',
                    ]
                ),
                encoding="utf-8",
            )
            override = load_model_prompt_override(
                provider="openai",
                model="gpt-5.4-nano",
                mode="cloud",
                config_root=root,
            )

            prompt = apply_prompt_override_sections(
                "BASE PROMPT",
                override,
                prepend_sections=("routing_prepend", "tool_calling_prepend"),
                append_sections=("routing_append",),
            )

            self.assertIn("MODEL-SPECIFIC GUIDANCE", prompt)
            self.assertIn("Prefer direct links.", prompt)
            self.assertIn("Preserve exact model numbers.", prompt)
            self.assertIn("BASE PROMPT", prompt)
            self.assertIn("MODEL-SPECIFIC REMINDERS", prompt)
            self.assertIn("Keep answers concrete.", prompt)


if __name__ == "__main__":
    unittest.main()
