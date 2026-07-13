#!/usr/bin/env python3
"""Regression tests that xAI chat-only options do not leak into media tools."""

import base64
import os
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "skills"))
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

import generate_image
import generate_video
import vision_provider


CHAT_ONLY_KEYS = {
    "messages",
    "tools",
    "metadata",
    "reasoning_effort",
    "previous_response_id",
    "prompt_cache_key",
    "store_messages",
    "temperature",
    "max_tokens",
    "max_output_tokens",
}

CACHE_AND_REASONING_KEYS = {
    "metadata",
    "reasoning_effort",
    "previous_response_id",
    "prompt_cache_key",
    "store_messages",
    "temperature",
    "tools",
    "max_output_tokens",
}


class _FakeImageResponse:
    status_code = 200
    text = "{}"

    def json(self):
        encoded = base64.b64encode(b"fake-png").decode("utf-8")
        return {"data": [{"b64_json": encoded}]}


class _FakeVisionResponse:
    status_code = 200
    text = "{}"

    def json(self):
        return {"choices": [{"message": {"content": "vision ok"}}]}


class XAIMediaPayloadTests(unittest.TestCase):
    def test_commented_out_video_model_env_uses_catalog_default(self):
        with patch.object(generate_video, "get_config_value", side_effect=lambda _key, default=None: default):
            model = generate_video._resolve_configured_video_model("xai")

        self.assertEqual(model, "grok-imagine-video")

    def test_image_generation_uses_media_payload_only(self):
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers or {}
            captured["payload"] = json or {}
            captured["timeout"] = timeout
            return _FakeImageResponse()

        def fake_config(name, default=None):
            values = {
                "XAI_API_KEY": "xai-test-key",
                "XAI_IMAGE_MODEL": "grok-imagine-image",
            }
            return values.get(name, default)

        with patch.dict(
            os.environ,
            {
                "XAI_REASONING_EFFORT": "low",
                "XAI_PROMPT_CACHE_KEY": "conv_media_should_not_leak",
            },
            clear=True,
        ), patch.object(generate_image, "get_config_value", side_effect=fake_config), patch.object(
            generate_image.requests,
            "post",
            side_effect=fake_post,
        ):
            result = generate_image.generate_image_xai("make a clean test image", aspect_ratio="landscape")

        self.assertEqual(result["provider"], "xai")
        self.assertEqual(captured["url"], generate_image.XAI_API_BASE)
        self.assertEqual(
            captured["headers"],
            {
                "Authorization": "Bearer xai-test-key",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(
            captured["payload"],
            {
                "model": "grok-imagine-image",
                "prompt": "make a clean test image",
                "n": 1,
                "response_format": "b64_json",
                "aspect_ratio": "16:9",
            },
        )
        self.assertFalse(CHAT_ONLY_KEYS.intersection(captured["payload"]))
        self.assertNotIn("x-grok-conv-id", captured["headers"])

    def test_vision_analysis_uses_minimal_chat_payload_without_cache_or_reasoning(self):
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers or {}
            captured["payload"] = json or {}
            captured["timeout"] = timeout
            return _FakeVisionResponse()

        def fake_config(name, default=None):
            values = {
                "XAI_API_KEY": "xai-test-key",
                "VISION_MODEL": "grok-4.3",
                "XAI_MODEL": "grok-4.3",
            }
            return values.get(name, default)

        with patch.dict(
            os.environ,
            {
                "XAI_REASONING_EFFORT": "low",
                "XAI_PROMPT_CACHE_KEY": "conv_vision_should_not_leak",
            },
            clear=True,
        ), patch.object(vision_provider, "get_config_value", side_effect=fake_config), patch.object(
            vision_provider.requests,
            "post",
            side_effect=fake_post,
        ):
            result = vision_provider.analyze_images(
                ["fake-image-base64"],
                "what is in this image?",
                mode="cloud",
                provider="xai",
                model="grok-4.3",
            )

        self.assertEqual(result, "vision ok")
        self.assertEqual(captured["url"], "https://api.x.ai/v1/chat/completions")
        self.assertEqual(
            set(captured["payload"].keys()),
            {"model", "messages", "max_tokens"},
        )
        self.assertEqual(captured["payload"]["model"], "grok-4.3")
        self.assertEqual(captured["payload"]["max_tokens"], 2048)
        self.assertFalse(CACHE_AND_REASONING_KEYS.intersection(captured["payload"]))
        self.assertNotIn("x-grok-conv-id", captured["headers"])

    def test_video_generation_uses_media_kwargs_only(self):
        captured = {}

        class FakeVideoClient:
            def generate(self, **kwargs):
                captured["generate_kwargs"] = kwargs
                return SimpleNamespace(url="https://example.test/video.mp4", duration=5)

        class FakeClient:
            def __init__(self, **kwargs):
                captured["client_kwargs"] = kwargs
                self.video = FakeVideoClient()

        fake_xai_sdk = types.ModuleType("xai_sdk")
        fake_xai_sdk.Client = FakeClient

        def fake_config(name, default=None):
            values = {
                "XAI_API_KEY": "xai-test-key",
                "XAI_VIDEO_MODEL": "grok-imagine-video",
            }
            return values.get(name, default)

        with patch.dict(sys.modules, {"xai_sdk": fake_xai_sdk}), patch.dict(
            os.environ,
            {
                "XAI_REASONING_EFFORT": "low",
                "XAI_PROMPT_CACHE_KEY": "conv_media_should_not_leak",
            },
            clear=True,
        ), patch.object(generate_video, "get_config_value", side_effect=fake_config):
            result = generate_video.generate_video_xai(
                "make a short clean test video",
                duration=5,
                aspect_ratio="16:9",
                resolution="720p",
                image_url="",
            )

        self.assertEqual(result["provider"], "xai")
        self.assertFalse(result["from_image"])
        self.assertEqual(captured["client_kwargs"], {"api_key": "xai-test-key"})
        self.assertEqual(
            captured["generate_kwargs"],
            {
                "prompt": "make a short clean test video",
                "model": "grok-imagine-video",
                "duration": 5,
                "aspect_ratio": "16:9",
                "resolution": "720p",
            },
        )
        self.assertFalse(CHAT_ONLY_KEYS.intersection(captured["generate_kwargs"]))


if __name__ == "__main__":
    unittest.main()
