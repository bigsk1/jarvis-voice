#!/usr/bin/env python3
"""
Regression tests for the Jarvis Web log explorer service.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))

from server_package_utils import load_server_package

load_server_package("jarvis_web_test_server", PROJECT_ROOT / "jarvis-web" / "server")

from jarvis_web_test_server.services.log_explorer import LogExplorerService


class LogExplorerServiceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.logs_root = Path(self.tempdir.name)
        self.explorer = LogExplorerService(self.logs_root)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_list_folders_only_returns_supported_log_folders(self):
        (self.logs_root / "api").mkdir()
        (self.logs_root / "api" / "access-2026-04-11.jsonl").write_text("{}\n", encoding="utf-8")
        (self.logs_root / "services").mkdir()
        (self.logs_root / "services" / "scheduled_task_runner.log").write_text("line\n", encoding="utf-8")
        (self.logs_root / "services" / "scheduled_task_runner.pid").write_text("123\n", encoding="utf-8")
        (self.logs_root / ".hidden").mkdir()
        (self.logs_root / ".hidden" / "ignored.log").write_text("skip\n", encoding="utf-8")
        (self.logs_root / "notes").mkdir()
        (self.logs_root / "notes" / "readme.txt").write_text("ignore\n", encoding="utf-8")

        folders = self.explorer.list_folders()
        labels = [folder["label"] for folder in folders]

        self.assertEqual(labels, ["api", "services"])

    def test_list_files_searches_filename_and_contents(self):
        (self.logs_root / "tools").mkdir()
        tool_file = self.logs_root / "tools" / "tool-calls-2026-04-11.jsonl"
        tool_file.write_text(
            json.dumps({"tool_name": "calendar_lookup", "status": "ok"}) + "\n",
            encoding="utf-8",
        )
        other_file = self.logs_root / "tools" / "tool-builder-2026-04-11.jsonl"
        other_file.write_text(
            json.dumps({"tool_name": "search_memory", "status": "ok"}) + "\n",
            encoding="utf-8",
        )

        by_name = self.explorer.list_files(folder="tools", search="builder")
        self.assertEqual([item["filename"] for item in by_name["files"]], ["tool-builder-2026-04-11.jsonl"])

        by_content = self.explorer.list_files(folder="tools", search="calendar_lookup")
        self.assertEqual([item["filename"] for item in by_content["files"]], ["tool-calls-2026-04-11.jsonl"])
        self.assertGreaterEqual(by_content["files"][0]["search_hit_count"], 1)

    def test_json_only_prompt_guard_incidents_are_discoverable_in_both_modes(self):
        for mode in ("cloud", "local"):
            incident_dir = self.logs_root / "prompt-guard" / "incidents" / mode
            incident_dir.mkdir(parents=True)
            (incident_dir / "2026-11-09-pg-example.json").write_text(
                json.dumps({"incident_id": "pg-example", "mode": mode}, indent=2),
                encoding="utf-8",
            )

        folders = self.explorer.list_folders()

        self.assertEqual(
            [folder["path"] for folder in folders],
            ["prompt-guard/incidents/cloud", "prompt-guard/incidents/local"],
        )
        for folder in folders:
            with self.subTest(folder=folder["path"]):
                self.assertEqual(folder["file_count"], 1)
                self.assertEqual(folder["extensions"], ["json"])
                self.assertEqual(folder["latest_file"], "2026-11-09-pg-example.json")

    def test_json_filter_searches_incident_contents_and_filename(self):
        incident_dir = self.logs_root / "prompt-guard" / "incidents" / "cloud"
        incident_dir.mkdir(parents=True)
        (incident_dir / "2026-11-09-pg-target.json").write_text(
            json.dumps({"evidence": {"text": "Unique quarantine evidence"}}, indent=2),
            encoding="utf-8",
        )
        (incident_dir / "2026-11-09-pg-other.json").write_text(
            json.dumps({"evidence": {"text": "Unrelated content"}}, indent=2),
            encoding="utf-8",
        )
        (incident_dir / "diagnostic.log").write_text(
            "Unique quarantine evidence\n", encoding="utf-8",
        )

        for extension in ("json", ".json"):
            with self.subTest(extension=extension):
                result = self.explorer.list_files(
                    folder="prompt-guard/incidents/cloud",
                    extension=extension,
                    search="QUARANTINE EVIDENCE",
                )
                self.assertEqual(result["total"], 1)
                self.assertEqual(
                    [item["filename"] for item in result["files"]],
                    ["2026-11-09-pg-target.json"],
                )
                self.assertEqual(result["files"][0]["extension"], ".json")
                self.assertGreaterEqual(result["files"][0]["search_hit_count"], 1)

        by_name = self.explorer.list_files(
            folder="prompt-guard/incidents/cloud", extension="json", search="pg-target",
        )
        self.assertEqual([item["filename"] for item in by_name["files"]], ["2026-11-09-pg-target.json"])

    def test_pretty_json_is_one_complete_yaml_record_with_finite_paging(self):
        report = {
            "incident_id": "pg-example",
            "timestamp": "2026-11-09T12:34:56Z",
            "mode": "local",
            "scan": {
                "score": 0.98,
                "diagnostics": {
                    "winning_window_index": 1,
                    "windows": [{"index": 0, "score": 0.2}, {"index": 1, "score": 0.98}],
                },
            },
            "evidence": {"text": "First line\nNeedle evidence: <script>untrusted()</script>"},
            "candidate_source_urls": ["https://example.com/a", "https://example.com/b"],
        }
        (self.logs_root / "incident.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

        result = self.explorer.read_file("incident.json", offset=0, limit=1)

        self.assertEqual(result["view_type"], "yaml-records")
        self.assertEqual(result["extension"], ".json")
        self.assertEqual(result["returned"], 1)
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["records"][0]["timestamp"], report["timestamp"])
        self.assertEqual(yaml.safe_load(result["records"][0]["yaml"]), report)
        self.assertFalse(result["has_more"])
        self.assertEqual(result["next_offset"], 1)

        next_page = self.explorer.read_file("incident.json", offset=1, limit=1)
        self.assertEqual(next_page["records"], [])
        self.assertEqual(next_page["returned"], 0)
        self.assertEqual(next_page["next_offset"], 1)
        self.assertFalse(next_page["has_more"])

        matching = self.explorer.read_file("incident.json", search="  NEEDLE EVIDENCE  ")
        self.assertEqual(len(matching["records"]), 1)
        self.assertEqual(yaml.safe_load(matching["records"][0]["yaml"]), report)

    def test_json_document_search_without_a_match_has_no_records(self):
        (self.logs_root / "incident.json").write_text(
            json.dumps({"timestamp": "2026-11-09T12:34:56Z", "evidence": {"text": "Example"}}, indent=2),
            encoding="utf-8",
        )

        result = self.explorer.read_file("incident.json", search="absent phrase", offset=0, limit=1)

        self.assertEqual(result["view_type"], "yaml-records")
        self.assertEqual(result["records"], [])
        self.assertEqual(result["returned"], 0)
        self.assertEqual(result["next_offset"], 0)
        self.assertFalse(result["has_more"])

    def test_malformed_json_retains_the_whole_document_as_raw_evidence(self):
        malformed = '{\n  "evidence": "<script>untrusted()</script>",\n  "incomplete":'
        (self.logs_root / "incident.json").write_text(malformed, encoding="utf-8")

        result = self.explorer.read_file("incident.json", offset=0, limit=1)

        self.assertEqual(result["view_type"], "yaml-records")
        self.assertEqual(result["returned"], 1)
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(yaml.safe_load(result["records"][0]["yaml"]), {"raw_line": malformed})
        self.assertFalse(result["has_more"])

    def test_read_jsonl_nestifies_dotted_keys_and_returns_newest_first(self):
        file_path = self.logs_root / "llm-calls-2026-04-11.jsonl"
        file_path.write_text(
            "\n".join([
                json.dumps({"timestamp": "2026-04-11T10:00:00", "tool.name": "search", "tool.args.query": "alpha"}),
                json.dumps({"timestamp": "2026-04-11T11:00:00", "tool.name": "status", "tool.args.query": "beta"}),
            ]) + "\n",
            encoding="utf-8",
        )

        payload = self.explorer.read_file("llm-calls-2026-04-11.jsonl", offset=0, limit=1)

        self.assertEqual(payload["view_type"], "yaml-records")
        self.assertEqual(len(payload["records"]), 1)
        self.assertEqual(payload["records"][0]["timestamp"], "2026-04-11T11:00:00")
        self.assertIn("tool:", payload["records"][0]["yaml"])
        self.assertIn("name: status", payload["records"][0]["yaml"])
        self.assertIn("query: beta", payload["records"][0]["yaml"])
        self.assertTrue(payload["has_more"])

    def test_search_results_prioritize_files_with_more_hits(self):
        (self.logs_root / "services").mkdir()
        low_hits = self.logs_root / "services" / "follow_up_daemon-2026-04-11.log"
        low_hits.write_text("search term once\n", encoding="utf-8")
        high_hits = self.logs_root / "services" / "scheduled_task_runner-2026-04-11.log"
        high_hits.write_text("search term\nsearch term again\n", encoding="utf-8")

        payload = self.explorer.list_files(folder="services", search="search term")

        self.assertEqual(
            [item["filename"] for item in payload["files"]],
            ["scheduled_task_runner-2026-04-11.log", "follow_up_daemon-2026-04-11.log"],
        )
        self.assertEqual(payload["files"][0]["search_hit_count"], 2)

    def test_read_log_returns_newest_lines_first(self):
        file_path = self.logs_root / "scheduled_task_runner.log"
        file_path.write_text("first\nsecond\nthird\n", encoding="utf-8")

        payload = self.explorer.read_file("scheduled_task_runner.log", offset=0, limit=2)

        self.assertEqual(payload["view_type"], "text-lines")
        self.assertEqual(payload["lines"], ["third", "second"])
        self.assertTrue(payload["has_more"])

    def test_read_jsonl_filters_records_when_search_is_active(self):
        file_path = self.logs_root / "intelligence-2026-04-11.jsonl"
        file_path.write_text(
            "\n".join([
                json.dumps({"timestamp": "2026-04-11T10:00:00", "provider": "openai"}),
                json.dumps({"timestamp": "2026-04-11T11:00:00", "provider": "anthropic"}),
                json.dumps({"timestamp": "2026-04-11T12:00:00", "provider": "xai"}),
            ]) + "\n",
            encoding="utf-8",
        )

        payload = self.explorer.read_file("intelligence-2026-04-11.jsonl", search="anthropic", offset=0, limit=10)

        self.assertEqual(len(payload["records"]), 1)
        self.assertEqual(payload["records"][0]["timestamp"], "2026-04-11T11:00:00")
        self.assertIn("provider: anthropic", payload["records"][0]["yaml"])

    def test_yaml_display_strips_trailing_newlines_from_string_values(self):
        file_path = self.logs_root / "errors-2026-03-31.jsonl"
        file_path.write_text(
            json.dumps({
                "timestamp": "2026-03-31T22:25:30.023737",
                "service": "web-ui",
                "response_body": "{\"error\":\"Invalid password\",\"ok\":false}\n",
            }) + "\n",
            encoding="utf-8",
        )

        payload = self.explorer.read_file("errors-2026-03-31.jsonl", offset=0, limit=1)
        yaml_text = payload["records"][0]["yaml"]

        self.assertIn('response_body: \'{"error":"Invalid password","ok":false}\'', yaml_text)
        self.assertNotIn('\n\n  \'', yaml_text)

    def test_read_log_filters_lines_when_search_is_active(self):
        file_path = self.logs_root / "test-cloud.log"
        file_path.write_text(
            "openai connected\nanthropic connected\nxai connected\nanthropic retry\n",
            encoding="utf-8",
        )

        payload = self.explorer.read_file("test-cloud.log", search="anthropic", offset=0, limit=10)

        self.assertEqual(payload["lines"], ["anthropic retry", "anthropic connected"])


if __name__ == "__main__":
    unittest.main()
