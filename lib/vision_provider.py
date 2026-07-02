"""Shared mode-aware vision provider dispatch for Jarvis surfaces.

Ollama vision model selection:
- cloud mode: OLLAMA_CLOUD_MODEL (or explicit model override from Web Settings)
- local mode: OLLAMA_VISION_MODEL, falling back to OLLAMA_MODEL

See docs/ollama/README.md § Vision and image analysis.
"""

from __future__ import annotations

from typing import Any

import requests

from config_loader import get_config_value
from model_catalog import get_provider_fallback_model
from ollama_utils import get_ollama_base_urls, request_ollama, resolve_ollama_model
from vision_multimodal import (
    build_anthropic_content,
    build_ollama_prompt,
    build_openai_style_content,
    openai_vision_detail,
)


class VisionProviderError(RuntimeError):
    """Raised when the selected vision provider cannot complete a request."""


def _response_error(provider: str, response: requests.Response) -> VisionProviderError:
    detail = (response.text or "")[:500]
    return VisionProviderError(f"{provider} vision failed ({response.status_code}): {detail}")


def _ollama_vision(images_base64: list[str], prompt: str, mode: str, model: str | None) -> str:
    if model:
        vision_model = model
    elif mode == "cloud":
        vision_model = resolve_ollama_model("cloud")
    else:
        vision_model = (
            get_config_value("OLLAMA_VISION_MODEL", "")
            or resolve_ollama_model("local")
        )

    response, _ = request_ollama(
        "post",
        "/api/generate",
        base_urls=get_ollama_base_urls(),
        json={
            "model": vision_model,
            "prompt": build_ollama_prompt(prompt, len(images_base64)),
            "images": images_base64,
            "stream": False,
        },
        timeout=120,
    )
    if response.status_code != 200:
        raise _response_error("Ollama", response)
    text = (response.json().get("response") or "").strip()
    if not text:
        raise VisionProviderError("Ollama vision returned an empty response")
    return text


def _anthropic_vision(images_base64: list[str], prompt: str, model: str | None) -> str:
    api_key = get_config_value("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise VisionProviderError("ANTHROPIC_API_KEY is not configured")
    selected_model = model or get_config_value(
        "ANTHROPIC_MODEL", get_provider_fallback_model("anthropic")
    )
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        json={
            "model": selected_model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": build_anthropic_content(images_base64, prompt)}],
        },
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        timeout=120,
    )
    if response.status_code != 200:
        raise _response_error("Anthropic", response)
    content = response.json().get("content") or []
    text = content[0].get("text", "").strip() if content else ""
    if not text:
        raise VisionProviderError("Anthropic vision returned an empty response")
    return text


def _openai_compatible_vision(
    provider: str,
    images_base64: list[str],
    prompt: str,
    model: str | None,
) -> str:
    is_xai = provider == "xai"
    api_key_name = "XAI_API_KEY" if is_xai else "OPENAI_API_KEY"
    api_key = get_config_value(api_key_name, "")
    if not api_key:
        raise VisionProviderError(f"{api_key_name} is not configured")

    if is_xai:
        selected_model = model or get_config_value("XAI_MODEL", get_provider_fallback_model("xai"))
        endpoint = "https://api.x.ai/v1/chat/completions"
        detail = str(get_config_value("VISION_DETAIL", "high") or "high").lower()
        if detail not in {"low", "high"}:
            detail = "high"
    else:
        selected_model = model or get_config_value(
            "OPENAI_MODEL", get_provider_fallback_model("openai")
        )
        endpoint = "https://api.openai.com/v1/chat/completions"
        detail = openai_vision_detail(selected_model, get_config_value("VISION_DETAIL", "high"))

    payload: dict[str, Any] = {
        "model": selected_model,
        "messages": [{
            "role": "user",
            "content": build_openai_style_content(images_base64, prompt, detail),
        }],
    }
    if not is_xai and str(selected_model).lower().startswith(("gpt-5", "o1", "o3", "o4")):
        payload["max_completion_tokens"] = 1024
    else:
        payload["max_tokens"] = 2048 if is_xai else 1024

    response = requests.post(
        endpoint,
        json=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=120,
    )
    if response.status_code != 200:
        raise _response_error("xAI" if is_xai else "OpenAI", response)
    choices = response.json().get("choices") or []
    text = choices[0].get("message", {}).get("content", "").strip() if choices else ""
    if not text:
        raise VisionProviderError(
            f"{'xAI' if is_xai else 'OpenAI'} vision returned an empty response"
        )
    return text


def analyze_images(
    images_base64: list[str],
    prompt: str,
    *,
    mode: str,
    provider: str | None = None,
    model: str | None = None,
) -> str:
    """Analyze images with the selected mode/provider, including Ollama Cloud."""
    if not images_base64:
        raise VisionProviderError("No images were supplied for vision analysis")

    selected_provider = "ollama" if mode == "local" else str(
        provider or get_config_value("LLM_PROVIDER", "xai")
    ).strip().lower()
    if selected_provider == "ollama":
        return _ollama_vision(images_base64, prompt, mode, model)
    if selected_provider == "anthropic":
        return _anthropic_vision(images_base64, prompt, model)
    if selected_provider in {"xai", "openai"}:
        return _openai_compatible_vision(
            selected_provider, images_base64, prompt, model
        )
    raise VisionProviderError(f"Unsupported vision provider: {selected_provider}")
