#!/usr/bin/env python3
"""Regression tests for shared OpenAI vision model/detail selection."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

import vision_provider


class _Response:
    status_code = 200
    text = ""

    @staticmethod
    def json():
        return {"choices": [{"message": {"content": "vision ok"}}]}


def _config(values):
    return lambda key, default="": values.get(key, default)


class OpenAIVisionModelTests(unittest.TestCase):
    def _run(self, values, model=None):
        with patch.object(
            vision_provider, "get_config_value", side_effect=_config(values)
        ), patch.object(vision_provider.requests, "post", return_value=_Response()) as post:
            result = vision_provider.analyze_images(
                ["base64"],
                "what is this?",
                mode="cloud",
                provider="openai",
                model=model,
            )
        return result, post.call_args.kwargs["json"]

    def test_blank_model_uses_openai_model(self):
        result, payload = self._run({
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_MODEL": "gpt-5.4-mini",
            "VISION_DETAIL": "high",
        })
        self.assertEqual(result, "vision ok")
        self.assertEqual(payload["model"], "gpt-5.4-mini")
        self.assertEqual(payload["messages"][0]["content"][0]["image_url"]["detail"], "high")
        self.assertIn("max_completion_tokens", payload)

    def test_explicit_openai_model_is_honored(self):
        _, payload = self._run(
            {"OPENAI_API_KEY": "sk-test", "VISION_DETAIL": "high"},
            model="gpt-4o",
        )
        self.assertEqual(payload["model"], "gpt-4o")
        self.assertIn("max_tokens", payload)

    def test_original_detail_is_forwarded_for_full_model(self):
        _, payload = self._run({
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_MODEL": "gpt-5.4",
            "VISION_DETAIL": "original",
        })
        detail = payload["messages"][0]["content"][0]["image_url"]["detail"]
        self.assertEqual(detail, "original")

    def test_original_detail_falls_back_for_mini_model(self):
        _, payload = self._run({
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_MODEL": "gpt-5.4-mini",
            "VISION_DETAIL": "original",
        })
        detail = payload["messages"][0]["content"][0]["image_url"]["detail"]
        self.assertEqual(detail, "high")

    def test_invalid_detail_defaults_to_high(self):
        _, payload = self._run({
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_MODEL": "gpt-5.4-mini",
            "VISION_DETAIL": "full-blast",
        })
        detail = payload["messages"][0]["content"][0]["image_url"]["detail"]
        self.assertEqual(detail, "high")


if __name__ == "__main__":
    unittest.main()
