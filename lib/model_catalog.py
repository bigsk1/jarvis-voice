"""
Shared cloud model catalog.

This centralizes curated provider/model metadata used by:
- Web UI dropdowns and context labels
- Default/fallback model selection
- Cost estimation
- Context window reporting scripts

Runtime env selection still comes from OPENAI_MODEL / XAI_MODEL / ANTHROPIC_MODEL.
This catalog only provides metadata and curated defaults when env or overrides do
not specify a model.

Image and video model IDs follow the same rule: provider-specific env variables
are optional pins, while MEDIA_MODEL_CATALOG supplies curated defaults, known
retirement replacements, capabilities, and pricing metadata.
"""

from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger(__name__)

OPENAI_MODELS_SOURCE = "https://platform.openai.com/docs/api-reference/models/list"

XAI_MODELS_SOURCE = "https://docs.x.ai/developers/rest-api-reference/inference/models"
XAI_MODEL_AUDIT_IGNORES = {
    "grok-4.20-multi-agent-0309": (
        "Multi-agent execution is intentionally excluded until Jarvis has a reviewed integration path."
    ),
}

ANTHROPIC_MODELS_SOURCE = "https://platform.claude.com/docs/en/api/models/list"
ANTHROPIC_PRICING_SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing"
ANTHROPIC_PRICING_VERIFIED = "2026-07-01"
ANTHROPIC_CACHE_WRITE_5M_MULTIPLIER = 1.25
ANTHROPIC_CACHE_WRITE_1H_MULTIPLIER = 2.0
ANTHROPIC_MODEL_AUDIT_IGNORES = {
    "claude-opus-4-1-20250805": "Deprecated by Anthropic; intentionally excluded from Jarvis options.",
}

_ANTHROPIC_CAPABILITIES_ADAPTIVE_XHIGH = {
    "batch": {"supported": True},
    "citations": {"supported": True},
    "code_execution": {"supported": True},
    "context_management": {
        "clear_thinking_20251015": {"supported": True},
        "clear_tool_uses_20250919": {"supported": True},
        "compact_20260112": {"supported": True},
        "supported": True,
    },
    "effort": {
        "high": {"supported": True},
        "low": {"supported": True},
        "max": {"supported": True},
        "medium": {"supported": True},
        "supported": True,
        "xhigh": {"supported": True},
    },
    "image_input": {"supported": True},
    "pdf_input": {"supported": True},
    "structured_outputs": {"supported": True},
    "thinking": {
        "supported": True,
        "types": {"adaptive": {"supported": True}, "enabled": {"supported": False}},
    },
}

_ANTHROPIC_CAPABILITIES_ADAPTIVE_AND_ENABLED = {
    **_ANTHROPIC_CAPABILITIES_ADAPTIVE_XHIGH,
    "effort": {
        **_ANTHROPIC_CAPABILITIES_ADAPTIVE_XHIGH["effort"],
        "xhigh": {"supported": False},
    },
    "thinking": {
        "supported": True,
        "types": {"adaptive": {"supported": True}, "enabled": {"supported": True}},
    },
}

_ANTHROPIC_CAPABILITIES_ENABLED = {
    **_ANTHROPIC_CAPABILITIES_ADAPTIVE_XHIGH,
    "context_management": {
        **_ANTHROPIC_CAPABILITIES_ADAPTIVE_XHIGH["context_management"],
        "compact_20260112": {"supported": False},
    },
    "effort": {
        "high": {"supported": False},
        "low": {"supported": False},
        "max": {"supported": False},
        "medium": {"supported": False},
        "supported": False,
        "xhigh": {"supported": False},
    },
    "thinking": {
        "supported": True,
        "types": {"adaptive": {"supported": False}, "enabled": {"supported": True}},
    },
}

_ANTHROPIC_CAPABILITIES_ENABLED_WITH_EFFORT = {
    **_ANTHROPIC_CAPABILITIES_ENABLED,
    "effort": {
        "high": {"supported": True},
        "low": {"supported": True},
        "max": {"supported": False},
        "medium": {"supported": True},
        "supported": True,
        "xhigh": {"supported": False},
    },
}

_ANTHROPIC_CAPABILITIES_ENABLED_NO_CODE = {
    **_ANTHROPIC_CAPABILITIES_ENABLED,
    "code_execution": {"supported": False},
}


def _context_label(tokens: int) -> str:
    """Format a context window for display."""
    if tokens >= 1_000_000:
        millions = tokens / 1_000_000
        if millions.is_integer():
            return f"{int(millions)}M"
        return f"{millions:.2f}".rstrip("0").rstrip(".") + "M"
    if tokens >= 1000:
        return f"{int(tokens / 1000)}K"
    return str(tokens)


CLOUD_MODEL_CATALOG: dict[str, list[dict[str, Any]]] = {
    "xai": [
        {
            "id": "grok-4.3",
            "name": "Grok 4.3 (Default)",
            "context_tokens": 1_000_000,
            "input_modalities": ["text", "image"],
            "output_modalities": ["text"],
            "default": True,
            "pricing": {
                "input": 1.25,
                "output": 2.50,
                "cached": 0.20,
                "image_input": 1.25,
                "search": 0.0,
                "long_context": {
                    "threshold": 200_000,
                    "input": 2.50,
                    "output": 5.00,
                    "cached": 0.40,
                },
            },
            "reasoning_effort": True,
            "aliases": ["grok-4.3-latest", "grok-latest"],
        },
        {
            "id": "grok-build-0.1",
            "name": "Grok Build 0.1 (agentic)",
            "context_tokens": 256_000,
            "input_modalities": ["text", "image"],
            "output_modalities": ["text"],
            "pricing": {
                "input": 1.00,
                "output": 2.00,
                "cached": 0.20,
                "image_input": 1.00,
                "search": 0.0,
                "long_context": {
                    "threshold": 200_000,
                    "input": 2.00,
                    "output": 4.00,
                    "cached": 0.40,
                },
            },
            "reasoning_effort": False,
            "aliases": ["grok-build", "grok-code-fast-1", "grok-code-fast", "grok-code-fast-1-0825"],
        },
        {
            "id": "grok-4.20-0309-reasoning",
            "name": "Grok 4.20 Reasoning",
            "context_tokens": 1_000_000,
            "input_modalities": ["text", "image"],
            "output_modalities": ["text"],
            "pricing": {
                "input": 1.25,
                "output": 2.50,
                "cached": 0.20,
                "image_input": 1.25,
                "search": 0.0,
                "long_context": {
                    "threshold": 200_000,
                    "input": 2.50,
                    "output": 5.00,
                    "cached": 0.40,
                },
            },
            "reasoning_effort": False,
            "aliases": [
                "grok-4.20-reasoning-latest",
                "grok-4.20",
                "grok-4.20-reasoning",
                "grok-4.20-0309",
            ],
        },
        {
            "id": "grok-4.20-0309-non-reasoning",
            "name": "Grok 4.20 Non-Reasoning",
            "context_tokens": 1_000_000,
            "input_modalities": ["text", "image"],
            "output_modalities": ["text"],
            "pricing": {
                "input": 1.25,
                "output": 2.50,
                "cached": 0.20,
                "image_input": 1.25,
                "search": 0.0,
                "long_context": {
                    "threshold": 200_000,
                    "input": 2.50,
                    "output": 5.00,
                    "cached": 0.40,
                },
            },
            "reasoning_effort": False,
            "aliases": ["grok-4.20-non-reasoning", "grok-4.20-non-reasoning-latest"],
        },
    ],
    "anthropic": [
        {
            "id": "claude-sonnet-5",
            "name": "Claude Sonnet 5 (Default)",
            "context_tokens": 1_000_000,
            "max_output_tokens": 128_000,
            "capabilities": _ANTHROPIC_CAPABILITIES_ADAPTIVE_XHIGH,
            "default": True,
            "pricing": {"input": 2.00, "output": 10.00, "cached": 0.20},
            "pricing_verified": ANTHROPIC_PRICING_VERIFIED,
            "pricing_valid_until": "2026-08-31",
            "pricing_source": ANTHROPIC_PRICING_SOURCE,
            "aliases": ["sonnet-5"],
        },
        {
            "id": "claude-fable-5",
            "name": "Claude Fable 5",
            "context_tokens": 1_000_000,
            "max_output_tokens": 128_000,
            "capabilities": _ANTHROPIC_CAPABILITIES_ADAPTIVE_XHIGH,
            "pricing": {"input": 10.00, "output": 50.00, "cached": 1.00},
            "pricing_verified": ANTHROPIC_PRICING_VERIFIED,
            "pricing_source": ANTHROPIC_PRICING_SOURCE,
            "aliases": ["fable-5"],
        },
        {
            "id": "claude-sonnet-4-6",
            "name": "Claude Sonnet 4.6",
            "context_tokens": 1_000_000,
            "max_output_tokens": 128_000,
            "capabilities": _ANTHROPIC_CAPABILITIES_ADAPTIVE_AND_ENABLED,
            "pricing": {"input": 3.00, "output": 15.00, "cached": 0.30},
            "pricing_verified": ANTHROPIC_PRICING_VERIFIED,
            "pricing_source": ANTHROPIC_PRICING_SOURCE,
            "aliases": ["sonnet-4.6", "sonnet-4", "claude-sonnet-4-20250514"],
        },
        {
            "id": "claude-sonnet-4-5-20250929",
            "name": "Claude Sonnet 4.5",
            "context_tokens": 1_000_000,
            "max_output_tokens": 64_000,
            "capabilities": _ANTHROPIC_CAPABILITIES_ENABLED,
            "pricing": {"input": 3.00, "output": 15.00, "cached": 0.30},
            "pricing_verified": ANTHROPIC_PRICING_VERIFIED,
            "pricing_source": ANTHROPIC_PRICING_SOURCE,
            "aliases": ["claude-4-5", "sonnet-4.5"],
        },
        {
            "id": "claude-haiku-4-5-20251001",
            "name": "Claude Haiku 4.5",
            "context_tokens": 200_000,
            "max_output_tokens": 64_000,
            "capabilities": _ANTHROPIC_CAPABILITIES_ENABLED_NO_CODE,
            "pricing": {"input": 1.00, "output": 5.00, "cached": 0.10},
            "pricing_verified": ANTHROPIC_PRICING_VERIFIED,
            "pricing_source": ANTHROPIC_PRICING_SOURCE,
            "aliases": ["claude-haiku-4-5", "haiku-4.5"],
        },
        {
            "id": "claude-opus-4-8",
            "name": "Claude Opus 4.8",
            "context_tokens": 1_000_000,
            "max_output_tokens": 128_000,
            "capabilities": _ANTHROPIC_CAPABILITIES_ADAPTIVE_XHIGH,
            "pricing": {"input": 5.00, "output": 25.00, "cached": 0.50},
            "pricing_verified": ANTHROPIC_PRICING_VERIFIED,
            "pricing_source": ANTHROPIC_PRICING_SOURCE,
            "aliases": ["opus-4.8", "opus-4", "claude-opus-4-20250514", "claude-4-opus"],
        },
        {
            "id": "claude-opus-4-7",
            "name": "Claude Opus 4.7",
            "context_tokens": 1_000_000,
            "max_output_tokens": 128_000,
            "capabilities": _ANTHROPIC_CAPABILITIES_ADAPTIVE_XHIGH,
            "pricing": {"input": 5.00, "output": 25.00, "cached": 0.50},
            "pricing_verified": ANTHROPIC_PRICING_VERIFIED,
            "pricing_source": ANTHROPIC_PRICING_SOURCE,
            "aliases": ["opus-4.7"],
        },
        {
            "id": "claude-opus-4-6",
            "name": "Claude Opus 4.6",
            "context_tokens": 1_000_000,
            "max_output_tokens": 128_000,
            "capabilities": _ANTHROPIC_CAPABILITIES_ADAPTIVE_AND_ENABLED,
            "pricing": {"input": 5.00, "output": 25.00, "cached": 0.50},
            "pricing_verified": ANTHROPIC_PRICING_VERIFIED,
            "pricing_source": ANTHROPIC_PRICING_SOURCE,
            "aliases": ["opus-4.6"],
        },
        {
            "id": "claude-opus-4-5-20251101",
            "name": "Claude Opus 4.5",
            "context_tokens": 200_000,
            "max_output_tokens": 64_000,
            "capabilities": _ANTHROPIC_CAPABILITIES_ENABLED_WITH_EFFORT,
            "pricing": {"input": 5.00, "output": 25.00, "cached": 0.50},
            "pricing_verified": ANTHROPIC_PRICING_VERIFIED,
            "pricing_source": ANTHROPIC_PRICING_SOURCE,
            "aliases": ["claude-opus-4-5", "opus-4.5"],
        },
    ],
    "openai": [
        {
            "id": "gpt-5.5",
            "name": "GPT-5.5",
            "context_tokens": 1_050_000,
            "max_output_tokens": 128_000,
            "pricing": {"input": 5.00, "output": 30.00, "cached": 0.50},
            "aliases": ["gpt-5.5-2026-04-23"],
        },
        {
            "id": "gpt-5.4",
            "name": "GPT-5.4",
            "context_tokens": 1_050_000,
            "pricing": {"input": 2.50, "output": 15.00, "cached": 0.25},
        },
        {
            "id": "gpt-5.4-mini",
            "name": "GPT-5.4 Mini",
            "context_tokens": 400_000,
            "pricing": {"input": 0.75, "output": 4.50, "cached": 0.075},
        },
        {
            "id": "gpt-5.4-nano",
            "name": "GPT-5.4 Nano (Default)",
            "context_tokens": 400_000,
            "default": True,
            "pricing": {"input": 0.20, "output": 1.25, "cached": 0.02},
        },
        {
            "id": "gpt-5.2",
            "name": "GPT-5.2",
            "context_tokens": 400_000,
            "pricing": {"input": 1.75, "output": 14.00, "cached": 0.17},
            "aliases": ["gpt-5.2-2025-12-11", "gpt-5.2-chat-latest"],
        },
        {
            "id": "gpt-5.2-chat-latest",
            "name": "GPT-5.2 Chat Latest",
            "context_tokens": 400_000,
            "pricing": {"input": 1.75, "output": 14.00, "cached": 0.17},
        },
        {
            "id": "gpt-5.2-2025-12-11",
            "name": "GPT-5.2 (Dec 2025)",
            "context_tokens": 400_000,
            "pricing": {"input": 1.75, "output": 14.00, "cached": 0.17},
        },
        {
            "id": "gpt-5.1",
            "name": "GPT-5.1",
            "context_tokens": 128_000,
            "pricing": {"input": 1.25, "output": 10.00, "cached": 0.125},
            "aliases": ["gpt-5.1-2025-11-13"],
        },
        {
            "id": "gpt-5.1-chat-latest",
            "name": "GPT-5.1 Chat Latest",
            "context_tokens": 128_000,
            "pricing": {"input": 1.25, "output": 10.00, "cached": 0.125},
        },
        {
            "id": "gpt-5.1-codex",
            "name": "GPT-5.1 Codex",
            "context_tokens": 128_000,
            "pricing": {"input": 1.25, "output": 10.00, "cached": 0.125},
        },
        {
            "id": "gpt-5.1-codex-mini",
            "name": "GPT-5.1 Codex Mini",
            "context_tokens": 128_000,
            "pricing": {"input": 0.25, "output": 2.00, "cached": 0.025},
        },
        {
            "id": "gpt-5-mini",
            "name": "GPT-5 Mini",
            "context_tokens": 128_000,
            "pricing": {"input": 0.25, "output": 2.00, "cached": 0.025},
            "aliases": ["gpt-5-mini-2025-08-07"],
        },
        {
            "id": "gpt-5-codex",
            "name": "GPT-5 Codex",
            "context_tokens": 128_000,
            "pricing": {"input": 1.25, "output": 10.00, "cached": 0.125},
        },
        {
            "id": "gpt-5-nano-2025-08-07",
            "name": "GPT-5 Nano (Aug 2025)",
            "context_tokens": 128_000,
            "pricing": {"input": 0.05, "output": 0.40, "cached": 0.005},
            "aliases": ["gpt-5-nano"],
        },
        {
            "id": "gpt-4.1",
            "name": "GPT-4.1",
            "context_tokens": 128_000,
            "pricing": {"input": 3.00, "output": 12.00, "cached": 0.75},
            "aliases": ["gpt-4.1-2025-04-14"],
        },
        {
            "id": "gpt-4o-mini",
            "name": "GPT-4o Mini",
            "context_tokens": 128_000,
            "pricing": {"input": 0.15, "output": 0.60, "cached": 0.07},
            "aliases": ["gpt-4o-mini-2024-07-18"],
        },
    ],
}


MEDIA_MODEL_ENV_KEYS: dict[str, dict[str, str]] = {
    "image": {
        "xai": "XAI_IMAGE_MODEL",
        "gemini": "GEMINI_IMAGE_MODEL",
        "openai": "OPENAI_IMAGE_MODEL",
    },
    "video": {
        "xai": "XAI_VIDEO_MODEL",
        "gemini": "GEMINI_VIDEO_MODEL",
        "openai": "OPENAI_VIDEO_MODEL",
    },
}


MEDIA_MODEL_CATALOG: dict[str, dict[str, dict[str, Any]]] = {
    "image": {
        "xai": {
            "name": "xAI Grok",
            "models": [
                {
                    "id": "grok-imagine-image",
                    "name": "Grok Imagine Image",
                    "default": True,
                    "capabilities": ["generation", "editing", "batch"],
                    "pricing": {
                        "unit": "image",
                        "usd_by_size": {"1K": 0.02, "2K": 0.02},
                        "input_image_usd": 0.002,
                    },
                },
                {
                    "id": "grok-imagine-image-quality",
                    "name": "Grok Imagine Image Quality",
                    "capabilities": ["generation", "editing", "batch"],
                    "pricing": {
                        "unit": "image",
                        "usd_by_size": {"1K": 0.05, "2K": 0.07},
                        "input_image_usd": 0.01,
                    },
                },
            ],
        },
        "gemini": {
            "name": "Google Gemini",
            "models": [
                {
                    "id": "gemini-3.1-flash-image",
                    "name": "Gemini 3.1 Flash Image",
                    "default": True,
                    "replaces": [
                        "gemini-3.1-flash-image-preview",
                        "gemini-2.0-flash-preview-image-generation",
                    ],
                    "capabilities": ["generation", "editing", "grounding", "1K", "2K", "4K"],
                    "pricing": {
                        "unit": "image",
                        "usd_by_size": {"0.5K": 0.045, "1K": 0.067, "2K": 0.101, "4K": 0.151},
                        "grounding_usd_per_1000_queries": 14.0,
                    },
                },
                {
                    "id": "gemini-3-pro-image",
                    "name": "Gemini 3 Pro Image",
                    "replaces": ["gemini-3-pro-image-preview"],
                    "capabilities": ["generation", "editing", "grounding", "1K", "2K", "4K"],
                    "pricing": {
                        "unit": "image",
                        "usd_by_size": {"1K": 0.134, "2K": 0.134, "4K": 0.24},
                        "grounding_usd_per_1000_queries": 14.0,
                    },
                },
            ],
        },
        "openai": {
            "name": "OpenAI GPT Image",
            "models": [
                {
                    "id": "gpt-image-2",
                    "name": "GPT Image 2",
                    "default": True,
                    "aliases": ["gpt-image-2-2026-04-21"],
                    "capabilities": ["generation", "editing", "flexible_sizes"],
                    "pricing": {
                        "unit": "variable",
                        "note": "Token-, quality-, and output-size-based pricing",
                    },
                }
            ],
        },
    },
    "video": {
        "xai": {
            "name": "xAI Grok",
            "models": [
                {
                    "id": "grok-imagine-video",
                    "name": "Grok Imagine Video",
                    "default": True,
                    "capabilities": ["text_to_video", "image_to_video", "video_editing"],
                    "resolutions": ["720p", "480p"],
                    "pricing": {
                        "unit": "second",
                        "usd_by_resolution": {"480p": 0.05, "720p": 0.07},
                        "input_image_usd": 0.002,
                        "input_video_usd_per_second": 0.01,
                    },
                },
                {
                    "id": "grok-imagine-video-1.5",
                    "name": "Grok Imagine Video 1.5",
                    "capabilities": ["text_to_video", "image_to_video"],
                    "resolutions": ["1080p", "720p", "480p"],
                    "pricing": {
                        "unit": "second",
                        "usd_by_resolution": {"480p": 0.08, "720p": 0.14, "1080p": 0.25},
                        "input_image_usd": 0.01,
                    },
                },
            ],
        },
        "gemini": {
            "name": "Google Gemini",
            "models": [
                {
                    "id": "veo-3.1-fast-generate-preview",
                    "name": "Veo 3.1 Fast",
                    "default": True,
                    "api": "generate_videos",
                    "replaces": ["veo-3.0-fast-generate-001"],
                    "capabilities": ["text_to_video", "image_to_video", "audio", "4K"],
                    "resolutions": ["720p", "1080p", "4k"],
                    "pricing": {
                        "unit": "second",
                        "usd_by_resolution": {"720p": 0.10, "1080p": 0.12, "4k": 0.30},
                    },
                },
                {
                    "id": "veo-3.1-generate-preview",
                    "name": "Veo 3.1 Standard",
                    "api": "generate_videos",
                    "replaces": ["veo-3.0-generate-001"],
                    "capabilities": ["text_to_video", "image_to_video", "audio", "4K"],
                    "resolutions": ["720p", "1080p", "4k"],
                    "pricing": {
                        "unit": "second",
                        "usd_by_resolution": {"720p": 0.40, "1080p": 0.40, "4k": 0.60},
                    },
                },
                {
                    "id": "veo-3.1-lite-generate-preview",
                    "name": "Veo 3.1 Lite",
                    "api": "generate_videos",
                    "capabilities": ["text_to_video", "image_to_video", "audio"],
                    "resolutions": ["720p", "1080p"],
                    "pricing": {
                        "unit": "second",
                        "usd_by_resolution": {"720p": 0.05, "1080p": 0.08},
                    },
                },
                {
                    "id": "gemini-omni-flash-preview",
                    "name": "Gemini Omni Flash (Preview)",
                    "api": "interactions",
                    "capabilities": [
                        "text_to_video",
                        "image_to_video",
                        "reference_to_video",
                        "video_editing",
                        "conversational_editing",
                        "audio",
                    ],
                    "resolutions": ["720p"],
                    "aspect_ratios": ["16:9", "9:16"],
                    "duration_seconds": {"min": 3, "max": 10},
                    "pricing": {
                        "unit": "second",
                        "usd_by_resolution": {"720p": 0.10},
                    },
                },
            ],
        },
        "openai": {
            "name": "OpenAI Sora",
            "models": [
                {
                    "id": "sora-2",
                    "name": "Sora 2",
                    "default": True,
                    "aliases": ["sora-2-2025-10-06"],
                    "capabilities": ["text_to_video", "image_to_video", "audio"],
                    "resolutions": ["720p"],
                    "pricing": {"unit": "second", "usd_by_resolution": {"720p": 0.10}},
                },
                {
                    "id": "sora-2-pro",
                    "name": "Sora 2 Pro",
                    "capabilities": ["text_to_video", "image_to_video", "audio", "1080p"],
                    "resolutions": ["720p", "1080p"],
                    "pricing": {
                        "unit": "second",
                        "usd_by_resolution": {"720p": 0.30, "1080p": 0.50},
                    },
                },
            ],
        },
    },
}


def get_catalog_providers() -> list[str]:
    return list(CLOUD_MODEL_CATALOG.keys())


def get_provider_catalog(provider: str) -> list[dict[str, Any]]:
    return [dict(entry) for entry in CLOUD_MODEL_CATALOG.get(provider, [])]


def get_media_model_env_key(media_type: str, provider: str) -> str:
    """Return the optional env/config key used to pin one media model."""
    return MEDIA_MODEL_ENV_KEYS.get(media_type, {}).get(provider, "")


def get_media_catalog_providers(media_type: str) -> list[str]:
    return list(MEDIA_MODEL_CATALOG.get(media_type, {}))


def get_media_model_catalog(media_type: str, provider: str) -> list[dict[str, Any]]:
    provider_entry = MEDIA_MODEL_CATALOG.get(media_type, {}).get(provider, {})
    return [dict(entry) for entry in provider_entry.get("models", [])]


def get_default_media_model_id(media_type: str, provider: str) -> str:
    models = get_media_model_catalog(media_type, provider)
    if not models:
        logger.warning(
            "[MODEL_CATALOG] Unknown %s provider requested for default model: %s",
            media_type,
            provider,
        )
        return ""
    defaults = [entry for entry in models if entry.get("default")]
    if len(defaults) > 1:
        logger.warning(
            "[MODEL_CATALOG] Multiple %s defaults configured for %s; using first: %s",
            media_type,
            provider,
            defaults[0]["id"],
        )
    return (defaults or models)[0]["id"]


def get_media_model_metadata(media_type: str, provider: str, model: str | None) -> dict[str, Any] | None:
    if not model:
        return None
    normalized = model.strip().lower()
    for entry in get_media_model_catalog(media_type, provider):
        known_ids = [entry.get("id"), *(entry.get("aliases") or [])]
        if normalized in {str(value).lower() for value in known_ids if value}:
            return entry
    return None


def resolve_media_model(media_type: str, provider: str, configured_model: str | None = None) -> str:
    """Resolve an optional media model pin against curated defaults/replacements.

    Unknown explicit IDs are intentionally preserved so newly released provider
    models remain usable before the catalog is updated. Known retired IDs are
    migrated to their declared replacement with an operator-visible warning.
    """
    configured = str(configured_model or "").strip()
    if not configured:
        return get_default_media_model_id(media_type, provider)

    normalized = configured.lower()
    for entry in get_media_model_catalog(media_type, provider):
        replacements = {str(value).lower() for value in entry.get("replaces", [])}
        if normalized in replacements:
            replacement = entry["id"]
            logger.warning(
                "[MODEL_CATALOG] Replacing retired %s model %s with %s for provider %s",
                media_type,
                configured,
                replacement,
                provider,
            )
            return replacement
    return configured


def get_media_provider_options(
    media_type: str,
    configured_models: dict[str, str | None] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return provider metadata for catalog defaults or optional model pins."""
    options = {}
    for provider, entry in MEDIA_MODEL_CATALOG.get(media_type, {}).items():
        configured_model = (configured_models or {}).get(provider)
        model = resolve_media_model(media_type, provider, configured_model)
        metadata = get_media_model_metadata(media_type, provider, model) or {}
        option = {
            "name": entry.get("name", provider),
            "model": model,
            "model_name": metadata.get("name", model),
        }
        for key in ("capabilities", "resolutions", "pricing"):
            if key in metadata:
                value = metadata[key]
                option[key] = dict(value) if isinstance(value, dict) else list(value)
        options[provider] = option
    return options


def get_media_model_pricing(media_type: str, provider: str, model: str | None) -> dict[str, Any] | None:
    metadata = get_media_model_metadata(media_type, provider, model)
    pricing = metadata.get("pricing") if metadata else None
    return dict(pricing) if pricing else None


def _candidate_model_ids(entry: dict[str, Any]) -> list[tuple[str, bool]]:
    candidates: list[tuple[str, bool]] = [(entry["id"], True)]
    candidates.extend((alias, False) for alias in entry.get("aliases", []))
    model_id = entry["id"]
    if model_id.endswith("-latest"):
        candidates.append((model_id[:-7], False))
    return [(candidate.lower(), is_id) for candidate, is_id in candidates]


def get_model_metadata(provider: str, model: str | None) -> dict[str, Any] | None:
    """Resolve catalog metadata for an exact or family-compatible model id."""
    if not model:
        return None
    if provider == "ollama":
        return None
    if provider not in CLOUD_MODEL_CATALOG:
        logger.warning("[MODEL_CATALOG] Unknown provider requested for model metadata: %s", provider)
        return None

    normalized = model.lower().strip()
    best_entry = None
    best_score: tuple[int, int] = (-1, -1)

    for entry in CLOUD_MODEL_CATALOG.get(provider, []):
        for candidate, is_id in _candidate_model_ids(entry):
            if normalized == candidate:
                score = (3 if is_id else 2, len(candidate))
            elif normalized.startswith(candidate + "-"):
                score = (1 if is_id else 0, len(candidate))
            else:
                continue

            if score > best_score:
                best_entry = entry
                best_score = score

    return dict(best_entry) if best_entry else None


def _model_option_capabilities(entry: dict[str, Any]) -> tuple[list[str], bool | None]:
    """Return conservative, UI-facing capabilities from catalog metadata."""
    # Every chat model admitted to this curated catalog is used through
    # Jarvis's tool-calling provider stack.
    tags: list[str] = ["tools"]
    vision: bool | None = None

    modalities = entry.get("input_modalities")
    if isinstance(modalities, list):
        vision = "image" in {str(value).strip().lower() for value in modalities}
    else:
        capabilities = entry.get("capabilities")
        if isinstance(capabilities, dict):
            image_input = capabilities.get("image_input")
            if isinstance(image_input, dict) and "supported" in image_input:
                vision = bool(image_input.get("supported"))
            thinking = capabilities.get("thinking")
            if isinstance(thinking, dict) and thinking.get("supported"):
                tags.append("thinking")

    if entry.get("reasoning_effort") or "reasoning" in str(entry.get("id", "")).lower():
        if "thinking" not in tags:
            tags.append("thinking")
    if vision:
        tags.insert(0, "vision")
    return tags, vision


def get_provider_model_options(provider: str) -> list[dict[str, Any]]:
    """Return curated models for UI dropdowns in display order."""
    options = []
    for entry in CLOUD_MODEL_CATALOG.get(provider, []):
        capabilities, vision = _model_option_capabilities(entry)
        options.append(
            {
                "id": entry["id"],
                "name": entry["name"],
                "context": _context_label(entry["context_tokens"]),
                "capabilities": capabilities,
                "vision": vision,
            }
        )
    return options


def get_default_model_id(provider: str) -> str:
    entries = CLOUD_MODEL_CATALOG.get(provider, [])
    if not entries:
        logger.warning("[MODEL_CATALOG] Unknown provider requested for default model: %s", provider)
        return ""

    defaults = [entry for entry in entries if entry.get("default")]
    if len(defaults) > 1:
        logger.warning(
            "[MODEL_CATALOG] Multiple defaults configured for %s; using first: %s",
            provider,
            defaults[0]["id"],
        )
    if defaults:
        return defaults[0]["id"]

    return entries[0]["id"]


def get_provider_fallback_model(provider: str, *, local_default: str = "gemma4") -> str:
    """Return a stable fallback model id when env/config does not specify one."""
    if provider == "ollama":
        return local_default
    return get_default_model_id(provider)


def get_model_context_window(provider: str, model: str | None) -> int | None:
    metadata = get_model_metadata(provider, model)
    return metadata.get("context_tokens") if metadata else None


def get_model_context_label(provider: str, model: str | None) -> str | None:
    tokens = get_model_context_window(provider, model)
    return _context_label(tokens) if tokens else None


def get_model_pricing(provider: str, model: str | None) -> dict[str, Any] | None:
    metadata = get_model_metadata(provider, model)
    pricing = metadata.get("pricing") if metadata else None
    return dict(pricing) if pricing else None


def get_model_supports_xai_reasoning_effort(provider: str, model: str | None) -> bool:
    """
    Whether XAI_REASONING_EFFORT may be sent for this model.

    Only grok-4.3 family supports the API parameter today; catalog is source of truth.
    """
    if provider != "xai":
        return False
    metadata = get_model_metadata(provider, model)
    if not metadata:
        return False
    return bool(metadata.get("reasoning_effort"))
