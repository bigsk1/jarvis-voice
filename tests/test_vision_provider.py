"""Regression tests for shared local/cloud vision dispatch."""

import sys
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

import vision_provider
import analyze_image


class _Response:
    status_code = 200
    text = ""

    @staticmethod
    def json():
        return {"response": "I can see the attached holographic figure."}


def test_cloud_ollama_vision_uses_cloud_model_and_images_payload():
    with patch.object(
        vision_provider, "resolve_ollama_model", return_value="minimax-m3:cloud"
    ) as resolve_model, patch.object(
        vision_provider, "get_ollama_base_urls", return_value=["http://ollama-host:11434"]
    ), patch.object(
        vision_provider, "request_ollama", return_value=(_Response(), "http://ollama-host:11434")
    ) as request_ollama:
        result = vision_provider.analyze_images(
            ["base64-image"],
            "Describe only what is visible.",
            mode="cloud",
            provider="ollama",
        )

    assert result == "I can see the attached holographic figure."
    resolve_model.assert_called_once_with("cloud")
    payload = request_ollama.call_args.kwargs["json"]
    assert payload["model"] == "minimax-m3:cloud"
    assert payload["images"] == ["base64-image"]
    assert payload["stream"] is False


def test_cloud_ollama_vision_honors_web_model_override():
    with patch.object(
        vision_provider, "get_ollama_base_urls", return_value=["http://ollama-host:11434"]
    ), patch.object(
        vision_provider, "request_ollama", return_value=(_Response(), "http://ollama-host:11434")
    ) as request_ollama, patch.object(vision_provider, "resolve_ollama_model") as resolve_model:
        vision_provider.analyze_images(
            ["base64-image"],
            "Describe this image.",
            mode="cloud",
            provider="ollama",
            model="qwen3.5:cloud",
        )

    resolve_model.assert_not_called()
    assert request_ollama.call_args.kwargs["json"]["model"] == "qwen3.5:cloud"


def test_analyze_image_uses_shared_ollama_cloud_dispatch():
    with patch.object(
        analyze_image,
        "get_config_value",
        side_effect=lambda key, default=None: "ollama" if key == "LLM_PROVIDER" else default,
    ), patch.object(
        vision_provider, "analyze_images", return_value="shared cloud vision result"
    ) as shared:
        result = analyze_image._analyze_with_vision(
            ["base64-image"],
            "Describe this image.",
            "cloud",
        )

    assert result == "shared cloud vision result"
    shared.assert_called_once_with(
        ["base64-image"],
        "Describe this image.",
        mode="cloud",
        provider="ollama",
        model=None,
    )
