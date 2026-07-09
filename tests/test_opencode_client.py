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

from opencode_client import OpenCodeClient, resolve_opencode_defaults


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
    def _make_client(self, config=None):
        config = config or {}

        def fake_get_config(key, default=None):
            values = {
                "OPENCODE_MODEL": "grok-build-0.1",
                "OPENCODE_PROVIDER": "xai",
                "OPENCODE_SERVER_PASSWORD": "",
                "OPENCODE_SERVER_USERNAME": "opencode",
            }
            values.update(config)
            return values.get(key, default)

        with patch("opencode_client.requests.get", return_value=FakeResponse({"ok": True})), \
             patch("config_loader.get_config_value", side_effect=fake_get_config), \
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

    def test_uses_basic_auth_when_server_password_is_configured(self):
        client = self._make_client({
            "OPENCODE_SERVER_USERNAME": "jarvis",
            "OPENCODE_SERVER_PASSWORD": "secret",
        })

        with patch("opencode_client.requests.post", return_value=FakeResponse({"sessionId": "ses_123"})) as mock_post:
            client.create_session(title="Jarvis: demo", agent_mode="build")

        mock_post.assert_called_once_with(
            "http://opencode.test/session",
            json={"title": "Jarvis: demo", "agent": "build"},
            timeout=client.timeout,
            auth=("jarvis", "secret"),
        )

    def test_resolve_opencode_defaults_uses_catalog_when_model_unset(self):
        def fake_get_config(key, default=""):
            values = {
                "OPENCODE_PROVIDER": "xai",
                "OPENCODE_MODEL": "",
            }
            return values.get(key, default)

        with patch("config_loader.get_config_value", side_effect=fake_get_config):
            defaults = resolve_opencode_defaults("cloud")

        self.assertEqual(defaults["providerID"], "xai")
        self.assertEqual(defaults["modelID"], "grok-4.5")

    def test_client_uses_catalog_fallback_when_opencode_model_unset(self):
        def fake_get_config(key, default=None):
            values = {
                "OPENCODE_PROVIDER": "anthropic",
                "OPENCODE_MODEL": "",
                "OPENCODE_SERVER_PASSWORD": "",
                "OPENCODE_SERVER_USERNAME": "opencode",
            }
            return values.get(key, default)

        with patch("opencode_client.requests.get", return_value=FakeResponse({"ok": True})), \
             patch("config_loader.get_config_value", side_effect=fake_get_config), \
             patch("opencode_client.OpenCodeLogger", return_value=MagicMock()):
            client = OpenCodeClient(base_url="http://opencode.test")

        self.assertEqual(client.default_provider_id, "anthropic")
        self.assertEqual(client.default_model_id, "claude-sonnet-5")

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
