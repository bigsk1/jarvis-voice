#!/usr/bin/env python3
"""Tests for portable protected / allowed paths (security_utils + paths)."""

import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from paths import get_allowed_write_paths, get_project_root, get_protected_paths
from security_utils import is_path_protected


class SecurityPathsTests(unittest.TestCase):
    def test_protected_includes_project_root(self):
        root = str(get_project_root().resolve())
        self.assertIn(root, get_protected_paths())

    def test_data_under_repo_is_writable(self):
        p = str(get_project_root() / "data" / "test.txt")
        protected, _ = is_path_protected(p, for_write=True)
        self.assertFalse(protected)

    def test_repo_source_file_is_protected(self):
        p = str(get_project_root() / "lib" / "paths.py")
        protected, matched = is_path_protected(p, for_write=True)
        self.assertTrue(protected)
        self.assertIsNotNone(matched)

    def test_allowed_write_paths_cover_data_logs_stash(self):
        allowed = get_allowed_write_paths()
        root = get_project_root().resolve()
        for sub in ("data", "logs", "stash"):
            self.assertIn(str((root / sub).resolve()), allowed)


if __name__ == "__main__":
    unittest.main()
