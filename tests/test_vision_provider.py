"""Regression tests for shared local/cloud vision dispatch."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

import vision_provider
import xai_oauth
import analyze_image


class _Response:
    def __init__(self, payload=None, status_code=200, text=""):
        self._payload = (
            payload
            if payload is not None
            else {"response": "I can see the attached holographic figure."}
        )
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload


def test_cloud_ollama_vision_uses_cloud_model_and_images_payload():
    with patch.object(
        vision_provider, "resolve_ollama_model", return_value="minimax-m3:cloud"
    ) as resolve_model, patch.object(
        vision_provider, "get_ollama_request_urls", return_value=["http://ollama-host:11434"]
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
        vision_provider, "get_ollama_request_urls", return_value=["http://ollama-host:11434"]
    ), patch.object(
        vision_provider, "request_ollama", return_value=(_Response(), "http://ollama-host:11434")
    ) as request_ollama, patch.object(
        vision_provider, "resolve_ollama_model", return_value="qwen3.5:cloud"
    ) as resolve_model:
        vision_provider.analyze_images(
            ["base64-image"],
            "Describe this image.",
            mode="cloud",
            provider="ollama",
            model="qwen3.5:cloud",
        )

    resolve_model.assert_called_once_with("cloud", model_override="qwen3.5:cloud")
    assert request_ollama.call_args.kwargs["json"]["model"] == "qwen3.5:cloud"


def test_ollama_text_only_model_is_rejected_before_generation():
    show_response = _Response({"capabilities": ["completion", "tools"]})
    with patch.object(
        vision_provider, "get_ollama_request_urls", return_value=["http://ollama-host:11434"]
    ), patch.object(
        vision_provider,
        "request_ollama",
        return_value=(show_response, "http://ollama-host:11434"),
    ) as request_ollama:
        try:
            vision_provider.analyze_images(
                ["base64-image"],
                "Describe this image.",
                mode="cloud",
                provider="ollama",
                model="glm-5.2:cloud",
            )
        except vision_provider.VisionCapabilityError as exc:
            assert exc.provider == "Ollama"
            assert exc.model == "glm-5.2:cloud"
            assert "does not support image input" in str(exc)
        else:
            raise AssertionError("Expected a text-only model capability error")

    request_ollama.assert_called_once()
    assert request_ollama.call_args.args[1] == "/api/show"


def test_ollama_generate_error_is_classified_when_show_metadata_is_unavailable():
    show_response = _Response({}, status_code=404)
    generate_response = _Response(
        {"error": "this model does not support image input"},
        status_code=400,
    )
    with patch.object(
        vision_provider, "get_ollama_request_urls", return_value=["http://ollama-host:11434"]
    ), patch.object(
        vision_provider,
        "request_ollama",
        side_effect=[
            (show_response, "http://ollama-host:11434"),
            (generate_response, "http://ollama-host:11434"),
        ],
    ) as request_ollama:
        try:
            vision_provider.analyze_images(
                ["base64-image"],
                "Describe this image.",
                mode="cloud",
                provider="ollama",
                model="glm-5.2:cloud",
            )
        except vision_provider.VisionCapabilityError as exc:
            assert exc.detail == "this model does not support image input"
        else:
            raise AssertionError("Expected a classified generation capability error")

    assert request_ollama.call_count == 2
    assert request_ollama.call_args.args[1] == "/api/generate"


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


def test_analyze_image_honors_cloud_web_provider_and_model_override():
    values = {
        "LLM_PROVIDER": "ollama",
        "ANALYZE_IMAGE_LLM_PROVIDER": "xai",
        "ANALYZE_IMAGE_LLM_MODEL": "grok-4.5",
        "VISION_MODEL": "different-vision-default",
    }
    with patch.object(
        analyze_image,
        "get_config_value",
        side_effect=lambda key, default=None: values.get(key, default),
    ), patch.object(
        vision_provider, "analyze_images", return_value="xai vision result"
    ) as shared:
        result = analyze_image._analyze_with_vision(
            ["base64-image"],
            "Describe this image.",
            "cloud",
        )

    assert result == "xai vision result"
    shared.assert_called_once_with(
        ["base64-image"],
        "Describe this image.",
        mode="cloud",
        provider="xai",
        model="grok-4.5",
    )


def test_analyze_image_local_ignores_web_chat_model_and_uses_vision_pin():
    values = {
        "ANALYZE_IMAGE_LLM_PROVIDER": "xai",
        "ANALYZE_IMAGE_LLM_MODEL": "grok-4.5",
        "OLLAMA_VISION_MODEL": "gemma4",
    }
    with patch.object(
        analyze_image,
        "get_config_value",
        side_effect=lambda key, default=None: values.get(key, default),
    ), patch.object(
        vision_provider, "analyze_images", return_value="local vision result"
    ) as shared:
        result = analyze_image._analyze_with_vision(
            ["base64-image"],
            "Describe this image.",
            "local",
        )

    assert result == "local vision result"
    shared.assert_called_once_with(
        ["base64-image"],
        "Describe this image.",
        mode="local",
        provider="ollama",
        model=None,
    )


def test_analyze_image_surfaces_provider_failure_in_top_level_error():
    capability_error = vision_provider.VisionCapabilityError("Ollama", "glm-5.2:cloud")
    resolved = {
        "base64": "base64-image",
        "source_type": "file",
        "original_path": "/tmp/image.jpg",
    }
    with patch.object(analyze_image, "load_config"), patch.object(
        analyze_image, "_resolve_image", return_value=resolved
    ), patch.object(
        analyze_image, "_analyze_with_vision", side_effect=capability_error
    ):
        result = analyze_image.analyze_image(image="/tmp/image.jpg")

    assert result["ok"] is False
    assert "does not support image input" in result["error"]
    assert result["data"]["error"] == result["error"]


def test_xai_oauth_vision_uses_chat_proxy_without_api_key():
    captured = {}

    def fake_config(name, default=None):
        values = {
            "XAI_API_KEY": "",
            "XAI_AUTH_MODE": "oauth",
            "XAI_OAUTH_MODEL": "grok-4.5",
            "VISION_DETAIL": "high",
        }
        return values.get(name, default)

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers or {}
        captured["payload"] = json or {}
        captured["timeout"] = timeout
        return _Response({"choices": [{"message": {"content": "blue and red"}}]})

    with (
        patch.object(vision_provider, "get_config_value", side_effect=fake_config),
        patch.object(
            xai_oauth,
            "get_fresh_xai_oauth_credentials",
            return_value=SimpleNamespace(token="private-oauth-token"),
        ),
        patch.object(xai_oauth, "get_grok_cli_version", return_value="0.2.93"),
        patch.object(vision_provider.requests, "post", side_effect=fake_post),
    ):
        result = vision_provider.analyze_images(
            ["base64-image"],
            "What colors are visible?",
            mode="cloud",
            provider="xai",
            model="grok-4.5",
        )

    assert result == "blue and red"
    assert captured["url"] == f"{xai_oauth.XAI_OAUTH_BASE_URL}/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer private-oauth-token"
    assert captured["headers"]["X-XAI-Token-Auth"] == "xai-grok-cli"
    assert captured["headers"]["x-grok-model-override"] == "grok-4.5"
    assert captured["payload"]["model"] == "grok-4.5"
    assert captured["payload"]["max_tokens"] == 2048
    content = captured["payload"]["messages"][0]["content"]
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"] == "data:image/jpeg;base64,base64-image"
    assert content[1] == {"type": "text", "text": "What colors are visible?"}
