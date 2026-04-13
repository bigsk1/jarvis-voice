#!/usr/bin/env python3
"""Focused tests for execute_bash path protection behavior."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

import execute_bash


class ExecuteBashSecurityTests(unittest.TestCase):
    def test_repo_data_write_is_blocked(self):
        cmd = f"touch {PROJECT_ROOT / 'data' / 'portable_test.txt'}"
        is_safe, reason = execute_bash.is_command_safe(cmd)
        self.assertFalse(is_safe)
        self.assertIn(str(PROJECT_ROOT / "data"), reason)

    def test_repo_source_write_is_blocked(self):
        cmd = f"touch {PROJECT_ROOT / 'lib' / 'portable_test.txt'}"
        is_safe, reason = execute_bash.is_command_safe(cmd)
        self.assertFalse(is_safe)
        self.assertIn(str(PROJECT_ROOT), reason)

    def test_relative_repo_data_write_is_blocked(self):
        is_safe, reason = execute_bash.is_command_safe(
            "touch data/portable_test.txt",
            str(PROJECT_ROOT),
        )
        self.assertFalse(is_safe)
        self.assertIn(str(PROJECT_ROOT / "data"), reason)

    def test_relative_repo_source_write_is_blocked(self):
        is_safe, reason = execute_bash.is_command_safe(
            "touch lib/portable_test.txt",
            str(PROJECT_ROOT),
        )
        self.assertFalse(is_safe)
        self.assertIn(str(PROJECT_ROOT), reason)


if __name__ == "__main__":
    unittest.main()
