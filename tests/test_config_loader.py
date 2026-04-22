#!/usr/bin/env python3
"""Unit tests for lib/config_loader portable path expansion."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from config_loader import _expand_env_value, load_env_file


class TestExpandEnvValue(unittest.TestCase):
    def test_home_and_tilde(self):
        fake = "/tmp/jarvis-test-home"
        os.environ["HOME"] = fake
        self.assertEqual(
            _expand_env_value("$HOME/jarvis-voice/audio"),
            fake + "/jarvis-voice/audio",
        )
        self.assertEqual(_expand_env_value("${HOME}/x"), fake + "/x")
        self.assertEqual(
            _expand_env_value("~/jarvis-voice/audio"),
            fake + "/jarvis-voice/audio",
        )

    def test_preserves_dollar_not_home(self):
        os.environ["HOME"] = "/h"
        self.assertEqual(_expand_env_value("sk-$not_a_var-end"), "sk-$not_a_var-end")

    def test_empty(self):
        self.assertEqual(_expand_env_value(""), "")

    def test_load_env_file_strips_unquoted_inline_comments(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "test.env"
            env_file.write_text(
                "\n".join(
                    [
                        "INT_VALUE=30  # every 30 days",
                        "HASH_VALUE=abc#123",
                        'QUOTED_VALUE="30  # keep this"',
                    ]
                )
            )

            loaded = load_env_file(env_file)

        self.assertEqual(loaded["INT_VALUE"], "30")
        self.assertEqual(loaded["HASH_VALUE"], "abc#123")
        self.assertEqual(loaded["QUOTED_VALUE"], "30  # keep this")


if __name__ == "__main__":
    unittest.main()
