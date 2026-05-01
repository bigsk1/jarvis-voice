#!/usr/bin/env python3
"""Regression tests for intel content normalization."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

from intel_content import normalize_intel_content
from ingest_intel import extract_facts_from_content
from manage_intel import append_intel_file


class TestIntelContentNormalization(unittest.TestCase):
    def test_normalizes_escaped_multiline_markdown(self) -> None:
        content = (
            "# Supa Crawl Knowledge\\n\\n"
            "## Current Crawled Sites\\n\\n"
            "- Ollama Docs\\n"
            "- Supabase Docs"
        )

        normalized, changed = normalize_intel_content(content)

        self.assertTrue(changed)
        self.assertIn("\n## Current Crawled Sites\n", normalized)
        self.assertNotIn("\\n", normalized)

    def test_preserves_single_line_paths_with_backslashes(self) -> None:
        content = r"C:\newfolder\notes.md"

        normalized, changed = normalize_intel_content(content)

        self.assertFalse(changed)
        self.assertEqual(content, normalized)

    def test_ingest_extracts_multiple_facts_from_escaped_markdown(self) -> None:
        content = (
            "# Supa Crawl Knowledge\\n\\n"
            "## Current Crawled Sites\\n\\n"
            "- Ollama Docs\\n"
            "- Supabase Docs\\n"
            "**When to use supa_crawl_knowledge:** Use it for crawled sites."
        )

        facts = extract_facts_from_content(content, "supa_crawl_knowledge.md")

        self.assertGreaterEqual(len(facts), 3)
        values = [fact["value"] for fact in facts]
        self.assertIn("Ollama Docs", values)
        self.assertIn("Supabase Docs", values)

    def test_append_preserves_heading_structure_and_uses_local_zone_label(self) -> None:
        tz = ZoneInfo("America/Los_Angeles")
        fake_now = datetime(2026, 5, 1, 0, 44, tzinfo=tz)

        with tempfile.TemporaryDirectory() as tmpdir:
            intel_dir = Path(tmpdir)
            target = intel_dir / "garden.md"
            target.write_text("# Garden\n", encoding="utf-8")

            with patch("manage_intel.now_local", return_value=fake_now):
                append_intel_file(
                    intel_dir,
                    "garden.md",
                    "## 2026-05-01\n- Observation: structure preserved",
                )

            content = target.read_text(encoding="utf-8")
            self.assertIn("[2026-05-01 00:44 PDT]\n## 2026-05-01", content)
            self.assertIn("- Observation: structure preserved", content)


if __name__ == "__main__":
    unittest.main()
