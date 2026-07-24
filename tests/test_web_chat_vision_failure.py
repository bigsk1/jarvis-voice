"""Regression tests for strict Web chat vision failure handling."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))

from server_package_utils import load_server_package


load_server_package("jarvis_web_vision_failure_test", PROJECT_ROOT / "jarvis-web" / "server")

from jarvis_web_vision_failure_test import config as web_config
from jarvis_web_vision_failure_test.sockets.chat import ChatHandler
from vision_provider import VisionCapabilityError, VisionProviderError


def test_process_vision_propagates_text_only_model_failure():
    handler = ChatHandler.__new__(ChatHandler)
    capability_error = VisionCapabilityError("Ollama", "glm-5.2:cloud")

    with patch.object(web_config, "load_jarvis_config"), patch.object(
        web_config,
        "load_web_config",
        return_value={
            "cloud": {"llm_provider": "ollama", "llm_model": "glm-5.2:cloud"}
        },
    ), patch(
        "vision_provider.analyze_images",
        side_effect=capability_error,
    ):
        with pytest.raises(VisionCapabilityError, match="does not support image input"):
            handler._process_vision(
                ["base64-image"],
                "What is in this image?",
                "cloud",
            )


def test_process_vision_grounds_prompt_and_accepts_visual_answer():
    handler = ChatHandler.__new__(ChatHandler)
    captured = {}

    def analyze(images, prompt, **kwargs):
        captured.update({"images": images, "prompt": prompt, **kwargs})
        return "The image shows a small green insect with long antennae on a leaf."

    with patch.object(web_config, "load_jarvis_config"), patch.object(
        web_config,
        "load_web_config",
        return_value={"cloud": {"llm_provider": "xai", "llm_model": "grok-4.5"}},
    ), patch("vision_provider.analyze_images", side_effect=analyze):
        result = handler._process_vision(
            ["base64-image"],
            "Identify this bug and update my garden file.",
            "cloud",
        )

    assert result.startswith("The image shows")
    assert captured["provider"] == "xai"
    assert captured["model"] == "grok-4.5"
    assert "using only the attached image pixels" in captured["prompt"]
    assert "Do not describe future actions" in captured["prompt"]
    assert captured["prompt"].endswith(
        "Identify this bug and update my garden file."
    )


def test_process_vision_rejects_plan_only_response():
    handler = ChatHandler.__new__(ChatHandler)
    plan = (
        "I'll identify the bug and update your bug Intel file. "
        "Let me start by examining the image and checking the computer for the file."
    )

    with patch.object(web_config, "load_jarvis_config"), patch.object(
        web_config,
        "load_web_config",
        return_value={"cloud": {"llm_provider": "xai", "llm_model": "grok-4.5"}},
    ), patch("vision_provider.analyze_images", return_value=plan):
        with pytest.raises(VisionProviderError, match="action plan"):
            handler._process_vision(
                ["base64-image"],
                "Identify this bug and update my garden file.",
                "cloud",
            )


def test_process_vision_accepts_answer_even_if_it_mentions_follow_up_action():
    handler = ChatHandler.__new__(ChatHandler)
    answer = (
        "I'll identify it now: this looks like a green katydid nymph based on "
        "the long antennae and enlarged jumping legs. Then the garden file can be updated."
    )

    with patch.object(web_config, "load_jarvis_config"), patch.object(
        web_config,
        "load_web_config",
        return_value={"cloud": {"llm_provider": "xai", "llm_model": "grok-4.5"}},
    ), patch("vision_provider.analyze_images", return_value=answer):
        result = handler._process_vision(
            ["base64-image"],
            "Identify this bug and update my garden file.",
            "cloud",
        )

    assert result == answer
