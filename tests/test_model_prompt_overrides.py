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
