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

from intel_content import normalize_intel_content, normalize_intel_document_eof
from ingest_intel import extract_facts_from_content
from manage_intel import (
    append_intel_file,
    auto_ingest,
    format_ingest_summary,
    replace_intel_content,
    search_intel_file,
)


def _fake_export_environment(mode):
    return {
        "JARVIS_MODE": mode,
        "LLM_PROVIDER": "xai" if mode == "cloud" else "ollama",
    }


class TestIntelContentNormalization(unittest.TestCase):
    def test_document_eof_collapses_trailing_blank_lines_only(self) -> None:
        content = "# Lessons\n\nFirst paragraph.\n\nSecond paragraph.\n\n\n"

        normalized, changed = normalize_intel_document_eof(content)

        self.assertTrue(changed)
        self.assertEqual(normalized, "# Lessons\n\nFirst paragraph.\n\nSecond paragraph.\n")

    def test_document_eof_adds_missing_final_newline(self) -> None:
        normalized, changed = normalize_intel_document_eof("# Lessons")

        self.assertTrue(changed)
        self.assertEqual(normalized, "# Lessons\n")

    def test_document_eof_preserves_empty_file(self) -> None:
        normalized, changed = normalize_intel_document_eof("")

        self.assertFalse(changed)
        self.assertEqual(normalized, "")

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

    def test_search_returns_tail_context_line_numbers_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            intel_dir = Path(tmpdir)
            target = intel_dir / "garden.md"
            target.write_text(
                "# Garden\n\n## Original\nKeep this.\n\n## Duplicate\nRemove this.\n",
                encoding="utf-8",
            )

            result = search_intel_file(
                intel_dir,
                "garden.md",
                "## Duplicate",
                context_lines=2,
            )

            self.assertEqual(result["match_count"], 1)
            self.assertEqual(result["matches"][0]["match_start_line"], 6)
            self.assertIn("6: ## Duplicate", result["matches"][0]["line_numbered_content"])
            self.assertIn("Remove this.", result["matches"][0]["content"])
            self.assertEqual(len(result["file_sha256"]), 64)

    def test_replace_removes_one_exact_block_with_matching_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            intel_dir = Path(tmpdir)
            target = intel_dir / "garden.md"
            duplicate = "\n## Duplicate\nRemove this.\n"
            target.write_text("# Garden\n" + duplicate + "\n## Keep\nKeep this.\n", encoding="utf-8")
            search = search_intel_file(intel_dir, "garden.md", "## Duplicate")

            result = replace_intel_content(
                intel_dir,
                "garden.md",
                duplicate,
                "",
                expected_replacements=1,
                expected_file_sha256=search["file_sha256"],
            )

            self.assertTrue(result["removed"])
            self.assertEqual(result["replacements"], 1)
            self.assertNotIn("Duplicate", target.read_text(encoding="utf-8"))
            self.assertIn("## Keep", target.read_text(encoding="utf-8"))

    def test_replace_refuses_ambiguous_match_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            intel_dir = Path(tmpdir)
            target = intel_dir / "garden.md"
            original = "duplicate\nkeep\nduplicate\n"
            target.write_text(original, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Expected 1 exact match.*found 2"):
                replace_intel_content(
                    intel_dir,
                    "garden.md",
                    "duplicate\n",
                    "",
                    expected_replacements=1,
                )

            self.assertEqual(target.read_text(encoding="utf-8"), original)

    def test_replace_refuses_stale_file_hash_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            intel_dir = Path(tmpdir)
            target = intel_dir / "garden.md"
            target.write_text("old block\n", encoding="utf-8")
            search = search_intel_file(intel_dir, "garden.md", "old block")
            target.write_text("new prefix\nold block\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "File changed after it was inspected"):
                replace_intel_content(
                    intel_dir,
                    "garden.md",
                    "old block\n",
                    "",
                    expected_file_sha256=search["file_sha256"],
                )

            self.assertEqual(target.read_text(encoding="utf-8"), "new prefix\nold block\n")

    def test_format_ingest_summary_mentions_both_dbs(self) -> None:
        summary = format_ingest_summary({
            "ingested": True,
            "new_files": 2,
            "total_facts": 28,
            "modes": ["cloud", "local"],
        })

        self.assertIn("cloud and local", summary)
        self.assertIn("28 total facts", summary)
        self.assertIn("across both DBs", summary)

    def test_auto_ingest_runs_current_then_sibling_sequentially(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skills_dir = root / "skills"
            data_dir = root / "data"
            skills_dir.mkdir()
            data_dir.mkdir()
            (skills_dir / "ingest_intel.py").write_text("# stub\n", encoding="utf-8")
            (data_dir / "jarvis_memory.db").write_text("", encoding="utf-8")
            (data_dir / "jarvis_memory_local.db").write_text("", encoding="utf-8")

            calls = []

            def fake_run(cmd, capture_output, text, timeout, env):
                calls.append((env["JARVIS_MODE"], env["LLM_PROVIDER"]))

                class Result:
                    returncode = 0
                    stdout = '{"ok": true, "data": {"new_files": 0, "total_facts": 0, "deleted_files": 1, "deleted_facts": 2}}'
                    stderr = ""

                return Result()

            with (
                patch("manage_intel.export_config_environment", side_effect=_fake_export_environment),
                patch("manage_intel.subprocess.run", side_effect=fake_run),
            ):
                result = auto_ingest(root, "cloud")

            self.assertTrue(result["ingested"])
            self.assertEqual(result["modes"], ["cloud", "local"])
            self.assertEqual(calls, [("cloud", "xai"), ("local", "ollama")])

    def test_auto_ingest_skips_missing_sibling_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skills_dir = root / "skills"
            data_dir = root / "data"
            skills_dir.mkdir()
            data_dir.mkdir()
            (skills_dir / "ingest_intel.py").write_text("# stub\n", encoding="utf-8")
            (data_dir / "jarvis_memory_local.db").write_text("", encoding="utf-8")

            calls = []

            def fake_run(cmd, capture_output, text, timeout, env):
                calls.append((env["JARVIS_MODE"], env["LLM_PROVIDER"]))

                class Result:
                    returncode = 0
                    stdout = '{"ok": true, "data": {"new_files": 0, "total_facts": 0}}'
                    stderr = ""

                return Result()

            with (
                patch("manage_intel.export_config_environment", side_effect=_fake_export_environment),
                patch("manage_intel.subprocess.run", side_effect=fake_run),
            ):
                result = auto_ingest(root, "local")

            self.assertTrue(result["ingested"])
            self.assertEqual(result["modes"], ["local"])
            self.assertEqual(calls, [("local", "ollama")])

    def test_auto_ingest_treats_sibling_failure_as_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skills_dir = root / "skills"
            data_dir = root / "data"
            skills_dir.mkdir()
            data_dir.mkdir()
            (skills_dir / "ingest_intel.py").write_text("# stub\n", encoding="utf-8")
            (data_dir / "jarvis_memory.db").write_text("", encoding="utf-8")
            (data_dir / "jarvis_memory_local.db").write_text("", encoding="utf-8")

            calls = []

            def fake_run(cmd, capture_output, text, timeout, env):
                calls.append((env["JARVIS_MODE"], env["LLM_PROVIDER"]))

                class Result:
                    stderr = ""

                result = Result()
                if env["JARVIS_MODE"] == "cloud":
                    result.returncode = 0
                    result.stdout = '{"ok": true, "data": {"new_files": 1, "total_facts": 3}}'
                else:
                    result.returncode = 1
                    result.stdout = "ollama unavailable"
                    result.stderr = "ollama unavailable"
                return result

            with (
                patch("manage_intel.export_config_environment", side_effect=_fake_export_environment),
                patch("manage_intel.subprocess.run", side_effect=fake_run),
            ):
                result = auto_ingest(root, "cloud")

            self.assertTrue(result["ingested"])
            self.assertTrue(result["partial"])
            self.assertEqual(result["modes"], ["cloud"])
            self.assertEqual(result["failed_modes"], ["local"])
            self.assertIn("local ingest failed", result["warning"])
            self.assertEqual(calls, [("cloud", "xai"), ("local", "ollama")])

    def test_auto_ingest_fails_when_current_mode_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skills_dir = root / "skills"
            data_dir = root / "data"
            skills_dir.mkdir()
            data_dir.mkdir()
            (skills_dir / "ingest_intel.py").write_text("# stub\n", encoding="utf-8")
            (data_dir / "jarvis_memory.db").write_text("", encoding="utf-8")

            def fake_run(cmd, capture_output, text, timeout, env):
                class Result:
                    returncode = 1
                    stdout = "primary failed"
                    stderr = "primary failed"

                return Result()

            with (
                patch("manage_intel.export_config_environment", side_effect=_fake_export_environment),
                patch("manage_intel.subprocess.run", side_effect=fake_run),
            ):
                result = auto_ingest(root, "cloud")

            self.assertFalse(result["ingested"])
            self.assertIn("cloud ingest failed", result["error"])


if __name__ == "__main__":
    unittest.main()
