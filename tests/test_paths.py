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

    def test_get_local_file_tool_allowed_dirs(self):
        with_p = get_local_file_tool_allowed_dirs(include_pictures=True)
        without_p = get_local_file_tool_allowed_dirs(include_pictures=False)
        self.assertGreater(len(with_p), len(without_p))
        self.assertTrue(any(p.name == "Pictures" for p in with_p))
        self.assertFalse(any(p.name == "Pictures" for p in without_p))


if __name__ == "__main__":
    unittest.main()
