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
"""

from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger(__name__)


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
            "id": "grok-4.20-reasoning",
            "name": "Grok 4.20 Reasoning",
            "context_tokens": 2_000_000,
            "pricing": {"input": 2.00, "output": 6.00, "cached": 0.20},
            "aliases": [
                "grok-4.20-reasoning-latest",
                "grok-4-20-reasoning",
                "grok-4-20-reasoning-latest",
            ],
        },
        {
            "id": "grok-4.20-non-reasoning-latest",
            "name": "Grok 4.20 Non-Reasoning",
            "context_tokens": 2_000_000,
            "pricing": {"input": 2.00, "output": 6.00, "cached": 0.20},
            "aliases": ["grok-4.20-non-reasoning", "grok-4-20-non-reasoning"],
        },
        {
            "id": "grok-4-1-fast-non-reasoning-latest",
            "name": "Grok 4.1 Fast (Default)",
            "context_tokens": 2_000_000,
            "default": True,
            "pricing": {"input": 0.20, "output": 0.50},
            "aliases": ["grok-4-1-fast-non-reasoning", "grok-4-1-fast"],
        },
        {
            "id": "grok-4-1-fast-reasoning-latest",
            "name": "Grok 4.1 Fast Reasoning",
            "context_tokens": 2_000_000,
            "pricing": {"input": 0.20, "output": 0.50},
            "aliases": ["grok-4-1-fast-reasoning", "grok-4-1-reasoning-latest"],
        },
    ],
    "anthropic": [
        {
            "id": "claude-sonnet-4-5-20250929",
            "name": "Claude Sonnet 4.5 (Default)",
            "context_tokens": 200_000,
            "default": True,
            "pricing": {"input": 3.00, "output": 15.00},
            "aliases": ["claude-4-5", "sonnet-4.5"],
        },
        {
            "id": "claude-opus-4-6",
            "name": "Claude Opus 4.6",
            "context_tokens": 200_000,
            "pricing": {"input": 15.00, "output": 75.00},
            "aliases": ["opus-4.6"],
        },
        {
            "id": "claude-opus-4-5",
            "name": "Claude Opus 4.5",
            "context_tokens": 200_000,
            "pricing": {"input": 15.00, "output": 75.00},
            "aliases": ["opus-4.5"],
        },
        {
            "id": "claude-4-opus",
            "name": "Claude 4 Opus",
            "context_tokens": 200_000,
            "pricing": {"input": 15.00, "output": 75.00},
            "aliases": ["opus-4"],
        },
        {
            "id": "claude-4-5",
            "name": "Claude 4.5",
            "context_tokens": 200_000,
            "pricing": {"input": 3.00, "output": 15.00},
        },
        {
            "id": "claude-sonnet-4-20250514",
            "name": "Claude Sonnet 4",
            "context_tokens": 200_000,
            "pricing": {"input": 3.00, "output": 15.00},
            "aliases": ["sonnet-4"],
        },
        {
            "id": "claude-3-5-sonnet-20241022",
            "name": "Claude 3.5 Sonnet",
            "context_tokens": 200_000,
            "pricing": {"input": 3.00, "output": 15.00},
        },
        {
            "id": "claude-3-opus-20240229",
            "name": "Claude 3 Opus",
            "context_tokens": 200_000,
            "pricing": {"input": 15.00, "output": 75.00},
        },
    ],
    "openai": [
        {
            "id": "gpt-5.4",
            "name": "GPT-5.4",
            "context_tokens": 1_050_000,
            "pricing": {"input": 2.50, "output": 15.00, "cached": 0.25},
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
            "id": "gpt-4o",
            "name": "GPT-4o",
            "context_tokens": 128_000,
            "pricing": {"input": 5.00, "output": 15.00, "cached": 0.75},
            "aliases": ["gpt-4o-2024-11-20", "gpt-4o-2024-08-06", "gpt-4o-2024-05-13"],
        },
    ],
}


def get_catalog_providers() -> list[str]:
    return list(CLOUD_MODEL_CATALOG.keys())


def get_provider_catalog(provider: str) -> list[dict[str, Any]]:
    return [dict(entry) for entry in CLOUD_MODEL_CATALOG.get(provider, [])]


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


def get_provider_model_options(provider: str) -> list[dict[str, str]]:
    """Return curated models for UI dropdowns in display order."""
    options = []
    for entry in CLOUD_MODEL_CATALOG.get(provider, []):
        options.append(
            {
                "id": entry["id"],
                "name": entry["name"],
                "context": _context_label(entry["context_tokens"]),
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

    first = entries
    return first[0]["id"] if first else ""


def get_provider_fallback_model(provider: str, *, local_default: str = "qwen3.5:latest") -> str:
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


def get_model_pricing(provider: str, model: str | None) -> dict[str, float] | None:
    metadata = get_model_metadata(provider, model)
    pricing = metadata.get("pricing") if metadata else None
    return dict(pricing) if pricing else None
