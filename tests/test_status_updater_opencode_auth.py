#!/usr/bin/env python3
"""
Regression tests for OpenCode status polling auth.

Run:
    python3 tests/test_status_updater_opencode_auth.py
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from status_updater import StatusUpdater


class FakeResponse:
    status_code = 200

    def json(self):
        return {
            "messages": [
                {"content": "Working on project files"},
            ]
        }


class StatusUpdaterOpenCodeAuthTests(unittest.TestCase):
    def test_poll_opencode_session_uses_basic_auth_when_configured(self):
        def fake_config(key, default=None):
            values = {
                "OPENCODE_BASE_URL": "http://opencode.test",
                "OPENCODE_SERVER_USERNAME": "jarvis",
                "OPENCODE_SERVER_PASSWORD": "secret",
            }
            return values.get(key, default)

        updater = StatusUpdater.__new__(StatusUpdater)

        with patch("status_updater.get_config_value", side_effect=fake_config), \
             patch("requests.get", return_value=FakeResponse()) as mock_get:
            context = updater._poll_opencode_session("ses_123")

        self.assertEqual(context, "Working on project files")
        mock_get.assert_called_once_with(
            "http://opencode.test/session/ses_123",
            timeout=3,
            auth=("jarvis", "secret"),
        )

    def test_poll_opencode_session_omits_auth_without_password(self):
        def fake_config(key, default=None):
            values = {
                "OPENCODE_BASE_URL": "http://opencode.test",
                "OPENCODE_SERVER_USERNAME": "jarvis",
                "OPENCODE_SERVER_PASSWORD": "",
            }
            return values.get(key, default)

        updater = StatusUpdater.__new__(StatusUpdater)

        with patch("status_updater.get_config_value", side_effect=fake_config), \
             patch("requests.get", return_value=FakeResponse()) as mock_get:
            context = updater._poll_opencode_session("ses_123")

        self.assertEqual(context, "Working on project files")
        mock_get.assert_called_once_with(
            "http://opencode.test/session/ses_123",
            timeout=3,
        )


if __name__ == "__main__":
    unittest.main()
