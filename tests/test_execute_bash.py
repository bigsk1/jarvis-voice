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

    def test_restricted_read_paths_are_blocked(self):
        blocked_cmds = [
            f"cat {PROJECT_ROOT / 'config' / 'cloud.env'}",
            f"head {PROJECT_ROOT / 'data' / 'backups' / 'jarvis_memory-20260704.db'}",
            f"grep foo {PROJECT_ROOT / 'data' / 'secrets' / 'youtube' / 'cookies.txt'}",
            "cat config/local.env",
        ]
        for cmd in blocked_cmds:
            with self.subTest(cmd=cmd):
                is_safe, reason = execute_bash.is_command_safe(cmd, str(PROJECT_ROOT))
                self.assertFalse(is_safe, msg=reason)
                self.assertIn("restricted path", reason)

    def test_non_restricted_data_reads_still_allowed(self):
        is_safe, reason = execute_bash.is_command_safe(
            "ls data/generated_images",
            str(PROJECT_ROOT),
        )
        self.assertTrue(is_safe, msg=reason)
        self.assertEqual(reason, "ok")

    def test_cd_into_restricted_directory_is_blocked(self):
        is_safe, reason = execute_bash.is_command_safe(
            "cd config",
            str(PROJECT_ROOT),
        )
        self.assertFalse(is_safe)
        self.assertIn("restricted path", reason)

    def test_grep_restricted_directory_is_blocked(self):
        is_safe, reason = execute_bash.is_command_safe(
            "grep -r API_KEY config",
            str(PROJECT_ROOT),
        )
        self.assertFalse(is_safe)
        self.assertIn("restricted path", reason)

    def test_rg_restricted_glob_is_blocked(self):
        is_safe, reason = execute_bash.is_command_safe(
            "rg password config/*.env",
            str(PROJECT_ROOT),
        )
        self.assertFalse(is_safe)
        self.assertIn("restricted path", reason)

    def test_restricted_working_directory_is_blocked(self):
        is_safe, reason = execute_bash.is_command_safe(
            "cat cloud.env",
            str(PROJECT_ROOT / "config"),
        )
        self.assertFalse(is_safe)
        self.assertIn("restricted working directory", reason)

    def test_sqlite_on_live_db_still_allowed(self):
        is_safe, reason = execute_bash.is_command_safe(
            'sqlite3 data/mem.db "select 1;"',
            str(PROJECT_ROOT),
        )
        self.assertTrue(is_safe, msg=reason)

    def test_jarvis_filename_does_not_match_vi_editor(self):
        is_safe, reason = execute_bash.is_command_safe(
            'sqlite3 data/jarvis_memory.db "select 1;"',
            str(PROJECT_ROOT),
        )
        self.assertTrue(is_safe, msg=reason)

    def test_command_names_inside_paths_do_not_mark_command_as_modifying(self):
        for cmd in ("stat /tmp/vi/example", "ls /tmp/cp/example"):
            with self.subTest(cmd=cmd):
                self.assertFalse(execute_bash.is_modifying_command(cmd))

    def test_search_pattern_named_config_is_not_treated_as_path(self):
        for cmd in ("grep config README.md", "rg config README.md"):
            with self.subTest(cmd=cmd):
                is_safe, reason = execute_bash.is_command_safe(cmd, str(PROJECT_ROOT))
                self.assertTrue(is_safe, msg=reason)

    def test_common_llm_read_commands_cannot_bypass_restricted_trees(self):
        blocked_cmds = [
            "rg API_KEY",
            "grep -R API_KEY .",
            'find . -path "*/config/*" -type f -exec cat {} \\;',
            "tar -cf /tmp/config-review.tar config",
            "ls config",
            "cat -n config/cloud.env",
            "python -c \"print(open('config/cloud.env').read())\"",
            "bash -c 'cat data/secrets/youtube/cookies.txt'",
        ]
        for cmd in blocked_cmds:
            with self.subTest(cmd=cmd):
                is_safe, reason = execute_bash.is_command_safe(cmd, str(PROJECT_ROOT))
                self.assertFalse(is_safe, msg=reason)
                self.assertIn("restricted path", reason)

if __name__ == "__main__":
    unittest.main()
