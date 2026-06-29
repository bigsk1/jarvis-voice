#!/usr/bin/env python3
"""Regression tests for Web UI OpenAI vision model selection."""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))

fake_socketio = types.ModuleType("flask_socketio")
fake_socketio.emit = lambda *args, **kwargs: None
fake_socketio.join_room = lambda *args, **kwargs: None
fake_socketio.leave_room = lambda *args, **kwargs: None
sys.modules.setdefault("flask_socketio", fake_socketio)

fake_flask = types.ModuleType("flask")
fake_flask.request = object()
sys.modules.setdefault("flask", fake_flask)

from server_package_utils import load_server_package

load_server_package("jarvis_web_test_server", PROJECT_ROOT / "jarvis-web" / "server")

from jarvis_web_test_server.sockets.chat import ChatHandler


class _Response:
    status_code = 200
    text = ""

    @staticmethod
    def json():
        return {"choices": [{"message": {"content": "vision ok"}}]}


def _settings(values):
    def fake_get(key, default=""):
        return values.get(key, default)

    return fake_get


class OpenAIVisionModelTests(unittest.TestCase):
    def setUp(self):
        self.handler = ChatHandler.__new__(ChatHandler)

    def test_blank_vision_model_uses_openai_model(self):
        settings = _settings({
            "OPENAI_API_KEY": "sk-test",
            "VISION_MODEL": "",
            "OPENAI_MODEL": "gpt-5.4-mini",
        })

        with patch("jarvis_web_test_server.config.get_jarvis_setting", side_effect=settings), \
             patch("requests.post", return_value=_Response()) as post:
            result = self.handler._vision_openai("base64", "what is this?", "")

        self.assertEqual(result, "vision ok")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "gpt-5.4-mini")
        image_input = payload["messages"][0]["content"][0]["image_url"]
        self.assertEqual(image_input["detail"], "high")
        self.assertIn("max_completion_tokens", payload)
        self.assertNotIn("max_tokens", payload)

    def test_non_openai_vision_model_falls_back_to_openai_model(self):
        settings = _settings({
            "OPENAI_API_KEY": "sk-test",
            "VISION_MODEL": "grok-4.3",
            "OPENAI_MODEL": "gpt-5.4-mini",
        })

        with patch("jarvis_web_test_server.config.get_jarvis_setting", side_effect=settings), \
             patch("requests.post", return_value=_Response()) as post:
            result = self.handler._vision_openai("base64", "what is this?", "grok-4.3")

        self.assertEqual(result, "vision ok")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "gpt-5.4-mini")

    def test_openai_vision_model_override_is_honored(self):
        settings = _settings({
            "OPENAI_API_KEY": "sk-test",
            "VISION_MODEL": "gpt-4o",
            "OPENAI_MODEL": "gpt-5.4-mini",
        })

        with patch("jarvis_web_test_server.config.get_jarvis_setting", side_effect=settings), \
             patch("requests.post", return_value=_Response()) as post:
            result = self.handler._vision_openai("base64", "what is this?", "gpt-4o")

        self.assertEqual(result, "vision ok")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "gpt-4o")
        self.assertIn("max_tokens", payload)

    def test_openai_vision_detail_is_forwarded(self):
        settings = _settings({
            "OPENAI_API_KEY": "sk-test",
            "VISION_MODEL": "",
            "OPENAI_MODEL": "gpt-5.4",
            "VISION_DETAIL": "original",
        })

        with patch("jarvis_web_test_server.config.get_jarvis_setting", side_effect=settings), \
             patch("requests.post", return_value=_Response()) as post:
            result = self.handler._vision_openai("base64", "what is this?", "")

        self.assertEqual(result, "vision ok")
        payload = post.call_args.kwargs["json"]
        image_input = payload["messages"][0]["content"][0]["image_url"]
        self.assertEqual(image_input["detail"], "original")

    def test_openai_original_detail_falls_back_for_mini_models(self):
        settings = _settings({
            "OPENAI_API_KEY": "sk-test",
            "VISION_MODEL": "",
            "OPENAI_MODEL": "gpt-5.4-mini",
            "VISION_DETAIL": "original",
        })

        with patch("jarvis_web_test_server.config.get_jarvis_setting", side_effect=settings), \
             patch("requests.post", return_value=_Response()) as post:
            result = self.handler._vision_openai("base64", "what is this?", "")

        self.assertEqual(result, "vision ok")
        payload = post.call_args.kwargs["json"]
        image_input = payload["messages"][0]["content"][0]["image_url"]
        self.assertEqual(image_input["detail"], "high")

    def test_openai_vision_detail_invalid_defaults_to_high(self):
        settings = _settings({
            "OPENAI_API_KEY": "sk-test",
            "VISION_MODEL": "",
            "OPENAI_MODEL": "gpt-5.4-mini",
            "VISION_DETAIL": "full-blast",
        })

        with patch("jarvis_web_test_server.config.get_jarvis_setting", side_effect=settings), \
             patch("requests.post", return_value=_Response()) as post:
            result = self.handler._vision_openai("base64", "what is this?", "")

        self.assertEqual(result, "vision ok")
        payload = post.call_args.kwargs["json"]
        image_input = payload["messages"][0]["content"][0]["image_url"]
        self.assertEqual(image_input["detail"], "high")


if __name__ == "__main__":
    unittest.main()
