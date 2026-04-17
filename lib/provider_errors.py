#!/usr/bin/env python3
"""Shared provider/API error classification and sanitization helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderErrorInfo:
    """Normalized provider error details safe for router/UI decisions."""

    kind: str
    friendly_message: str
    raw_preview: str


def _auth_or_key_error_signals(lowered: str) -> bool:
    """
    Phrases that appear in real provider auth failures — avoid a bare 'authentication'
    substring (normal Q&A about OAuth etc. must not match).
    """
    if any(
        phrase in lowered
        for phrase in (
            "invalid api key",
            "incorrect api key",
            "api key is invalid",
            "api key has expired",
            "expired api key",
            "authentication failed",
            "failed to authenticate",
            "could not authenticate",
            "missing api key",
            "no api key",
            "invalid_api_key",
        )
    ):
        return True
    # Typical HTTP / SDK shapes (narrower than a lone "401")
    if re.search(r"\b401\b", lowered) and (
        "error" in lowered
        or "code" in lowered
        or "status" in lowered
        or "http" in lowered
        or "unauthorized" in lowered
    ):
        return True
    return False


def _common_sdk_or_http_error_signals(lowered: str) -> bool:
    """
    Phrases that show up in OpenAI / Anthropic / xAI / Ollama SDK exceptions and JSON
    error bodies (often surfaced as Error: {str(e)}). Unlikely in normal Q&A prose.
    See also: lib/llm_provider.py (Error: ...), lib/embeddings.py (Ollama context).
    """
    if any(
        phrase in lowered
        for phrase in (
            # OpenAI-style error.type / JSON
            "insufficient_quota",
            "billing_hard_limit",
            "context_length_exceeded",
            "string_above_max_length",
            "rate_limit_exceeded",
            "invalid_request_error",
            "overloaded_error",
            "model_not_found",
            # Ollama / local (embeddings.py, llm_provider timeout string)
            "input length exceeds the context length",
            "input length exceeds context",
            "maximum context length",
            "context length exceeded",
            "model may be overloaded",
            # gRPC / Google-style
            "resource_exhausted",
            "resource exhausted",
            # HTTP proxy / upstream (often in requests exceptions)
            "bad gateway",
            "gateway timeout",
            "service unavailable",
            "econnrefused",
            "connection reset by peer",
        )
    ):
        return True
    # Anthropic overload and similar (narrow: require error-ish context)
    if re.search(r"\b529\b", lowered) and (
        "error" in lowered or "status" in lowered or "code" in lowered or "http" in lowered
    ):
        return True
    return False


def _looks_like_markdown_answer(text: str) -> bool:
    """
    Long structured answers (how-tos, research) often mention phrases we otherwise treat as
    SDK errors ('gateway timeout', 'rate limit', 'TCP timeouts'). Those are not errors.
    """
    if len(text) < 400:
        return False
    return (
        text.startswith("##")
        or text.startswith("# ")
        or "\n## " in text
        or text.startswith("###")
    )


def is_provider_error_text(text: str | None) -> bool:
    """Detect provider/API error text accidentally returned as normal model text."""
    if not text or not isinstance(text, str):
        return False
    value = text.strip()
    if not value:
        return False

    if _looks_like_markdown_answer(value):
        return False

    lowered = value.lower()
    return (
        value.startswith("Error:")
        or lowered.startswith("error code:")
        or "content violates usage guidelines" in lowered
        or "does not have permission to execute" in lowered
        or "caller does not have permission" in lowered
        or "safety_check_type_" in lowered
        or "rate limit" in lowered
        or "too many requests" in lowered
        or _auth_or_key_error_signals(lowered)
        or _common_sdk_or_http_error_signals(lowered)
        or "_InactiveRpcError" in value
        or "StatusCode.PERMISSION_DENIED" in value
        or "grpc_status:7" in value
    )


def sanitize_provider_error(text: str | None, max_chars: int = 500) -> str:
    """Remove IDs and secrets from raw provider errors before logs/UI display."""
    value = (text or "").strip()
    if not value:
        return ""

    replacements = [
        (r"Team:\s*[A-Za-z0-9-]+", "Team: [redacted]"),
        (r"API key ID:\s*[A-Za-z0-9-]+", "API key ID: [redacted]"),
        (r"sk-[A-Za-z0-9_-]+", "sk-[redacted]"),
        (r"xai-[A-Za-z0-9_-]+", "xai-[redacted]"),
    ]
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value)

    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > max_chars:
        value = value[:max_chars].rstrip() + "..."
    return value


def classify_provider_error(text: str | None) -> ProviderErrorInfo:
    """Classify a provider error into a stable kind and friendly message."""
    sanitized = sanitize_provider_error(text)
    lowered = sanitized.lower()

    if "content violates usage guidelines" in lowered or "safety_check_type_" in lowered:
        return ProviderErrorInfo(
            kind="safety",
            friendly_message="The LLM provider rejected the routing request with a safety check before any tool could run.",
            raw_preview=sanitized,
        )
    if "does not have permission" in lowered or "permission_denied" in lowered or "403" in lowered:
        return ProviderErrorInfo(
            kind="permission",
            friendly_message="The LLM provider rejected the routing request with a permission error before any tool could run.",
            raw_preview=sanitized,
        )
    if (
        "context_length_exceeded" in lowered
        or "string_above_max_length" in lowered
        or "input length exceeds" in lowered
        or "maximum context length" in lowered
        or "context length exceeded" in lowered
    ):
        return ProviderErrorInfo(
            kind="context",
            friendly_message="The LLM provider rejected the routing request because the prompt exceeded the model context limit.",
            raw_preview=sanitized,
        )
    if "insufficient_quota" in lowered or "billing_hard_limit" in lowered:
        return ProviderErrorInfo(
            kind="billing",
            friendly_message="The LLM provider rejected the routing request due to quota or billing limits.",
            raw_preview=sanitized,
        )
    if (
        "rate limit" in lowered
        or "too many requests" in lowered
        or "429" in lowered
        or "rate_limit_exceeded" in lowered
        or "overloaded_error" in lowered
        or ("overloaded" in lowered and "error" in lowered)
        or (
            re.search(r"\b529\b", lowered)
            and ("error" in lowered or "status" in lowered or "code" in lowered)
        )
    ):
        return ProviderErrorInfo(
            kind="rate_limit",
            friendly_message="The LLM provider rate-limited the routing request before any tool could run.",
            raw_preview=sanitized,
        )
    if _auth_or_key_error_signals(lowered):
        return ProviderErrorInfo(
            kind="authentication",
            friendly_message="The LLM provider rejected the routing request because authentication failed.",
            raw_preview=sanitized,
        )
    if "timeout" in lowered:
        return ProviderErrorInfo(
            kind="timeout",
            friendly_message="The LLM provider timed out before routing could finish.",
            raw_preview=sanitized,
        )

    return ProviderErrorInfo(
        kind="unknown",
        friendly_message="The LLM provider returned an error before any tool could run.",
        raw_preview=sanitized,
    )


def friendly_provider_error(text: str | None) -> str:
    """Return a stable, user-safe provider error message."""
    return classify_provider_error(text).friendly_message
