#!/usr/bin/env python3
"""Tests for lib/paths.py (portable home / repo / workspace)."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from paths import (
    get_allowed_write_paths,
    get_jarvis_workspace,
    get_local_file_tool_allowed_dirs,
    get_project_root,
    get_protected_paths,
    get_restricted_read_match,
    get_restricted_read_paths,
    resolve_local_file_tool_output_path,
    resolve_local_file_tool_path,
    validate_tool_output_filename,
    get_user_home,
)


class PathsTests(unittest.TestCase):
    def test_get_user_home_is_absolute(self):
        h = get_user_home()
        self.assertTrue(h.is_absolute())
        self.assertEqual(h, Path.home().resolve())

    def test_get_project_root_matches_repo_layout(self):
        self.assertEqual(get_project_root(), PROJECT_ROOT)

    def test_get_jarvis_workspace_default(self):
        self.assertEqual(get_jarvis_workspace(), get_user_home() / "jarvis-workspace")

    def test_get_jarvis_workspace_respects_env(self):
        expected = PROJECT_ROOT / "tmp-ws-override"
        with patch.dict(os.environ, {"JARVIS_WORKSPACE_ROOT": str(expected)}):
            self.assertEqual(get_jarvis_workspace(), expected.resolve())

    def test_get_protected_paths_contains_repo_root(self):
        self.assertIn(str(get_project_root().resolve()), get_protected_paths())

    def test_get_allowed_write_paths_contains_data(self):
        self.assertIn(str((get_project_root() / "data").resolve()), get_allowed_write_paths())

    def test_get_restricted_read_paths_covers_backups_secrets_config(self):
        root = get_project_root().resolve()
        restricted = get_restricted_read_paths()
        self.assertIn(str((root / "data" / "backups").resolve()), restricted)
        self.assertIn(str((root / "data" / "secrets").resolve()), restricted)
        self.assertIn(str((root / "config").resolve()), restricted)

    def test_resolve_local_file_tool_path_blocks_restricted_subtrees(self):
        root = get_project_root().resolve()
        blocked_paths = [
            root / "data" / "backups" / "example.db",
            root / "data" / "secrets" / "youtube" / "cookies.txt",
            root / "config" / "cloud.env",
        ]
        for path in blocked_paths:
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    resolve_local_file_tool_path(path, include_pictures=False)

    def test_get_restricted_read_match_returns_prefix(self):
        root = get_project_root().resolve()
        matched = get_restricted_read_match(root / "config" / "local.env")
        self.assertEqual(matched, str((root / "config").resolve()))

    def test_get_local_file_tool_allowed_dirs(self):
        with_p = get_local_file_tool_allowed_dirs(include_pictures=True)
        without_p = get_local_file_tool_allowed_dirs(include_pictures=False)
        self.assertGreater(len(with_p), len(without_p))
        self.assertTrue(any(p.name == "Pictures" for p in with_p))
        self.assertFalse(any(p.name == "Pictures" for p in without_p))

    def test_validate_tool_output_filename_rejects_traversal(self):
        for name in ("../report.pdf", "folder/report.pdf", "folder\\report.pdf", "/tmp/report.pdf"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    validate_tool_output_filename(name)
        self.assertEqual(validate_tool_output_filename("report.pdf"), "report.pdf")

    def test_resolve_tool_output_path_allows_shared_write_dirs(self):
        self.assertEqual(
            resolve_local_file_tool_output_path("/tmp/jarvis-output.jpg"),
            Path("/tmp/jarvis-output.jpg"),
        )

    def test_resolve_tool_output_path_blocks_restricted_and_repo_source_paths(self):
        blocked = [
            PROJECT_ROOT / "config" / "screenshot.jpg",
            PROJECT_ROOT / "lib" / "screenshot.jpg",
        ]
        for path in blocked:
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    resolve_local_file_tool_output_path(path)

    def test_resolve_tool_output_path_stays_under_base_directory(self):
        base = PROJECT_ROOT / "data" / "stash" / "space_test"
        self.assertEqual(
            resolve_local_file_tool_output_path("report.pdf", base_dir=base),
            base / "report.pdf",
        )
        with self.assertRaises(ValueError):
            resolve_local_file_tool_output_path("../../config/cloud.env", base_dir=base)


if __name__ == "__main__":
    unittest.main()
