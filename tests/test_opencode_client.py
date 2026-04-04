#!/usr/bin/env python3
"""
Regression tests for OpenCode client session handling.

Run:
    python3 tests/test_opencode_client.py
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from opencode_client import OpenCodeClient


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class OpenCodeClientTests(unittest.TestCase):
    def _make_client(self):
        with patch("opencode_client.requests.get", return_value=FakeResponse({"ok": True})), \
             patch("opencode_client.OpenCodeLogger", return_value=MagicMock()):
            return OpenCodeClient(base_url="http://opencode.test")

    def test_create_session_includes_agent_mode_string(self):
        client = self._make_client()

        with patch("opencode_client.requests.post", return_value=FakeResponse({"sessionId": "ses_123"})) as mock_post:
            response = client.create_session(title="Jarvis: demo", agent_mode="build")

        self.assertEqual(response["sessionId"], "ses_123")
        mock_post.assert_called_once_with(
            "http://opencode.test/session",
            json={"title": "Jarvis: demo", "agent": "build"},
            timeout=client.timeout,
        )

    def test_execute_task_accepts_session_id_response_key(self):
        client = self._make_client()
        client.logger = MagicMock()

        with patch.object(client, "create_session", return_value={"sessionId": "ses_from_server"}) as mock_create_session, \
             patch.object(client, "send_message", side_effect=[
                 {"ok": True},
                 {"ok": True},
                 {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
             ]) as mock_send_message:
            result = client.execute_task(
                task="Build a demo app",
                agent_mode="build",
                context={"task_type": "coding"},
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["session_id"], "ses_from_server")
        mock_create_session.assert_called_once_with(
            title="Jarvis: Build a demo app",
            agent_mode="build",
        )
        self.assertEqual(mock_send_message.call_count, 3)


if __name__ == "__main__":
    unittest.main()
