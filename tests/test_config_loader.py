#!/usr/bin/env python3
"""Unit tests for lib/config_loader portable path expansion."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from config_loader import _expand_env_value


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


if __name__ == "__main__":
    unittest.main()
