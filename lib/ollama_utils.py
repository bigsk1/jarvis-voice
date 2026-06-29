#!/usr/bin/env python3
"""Helpers for working with Ollama hosts and fallback requests."""

from __future__ import annotations

from typing import Iterable

from config_loader import get_config_value, get_active_config_mode


DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"


class OllamaModelError(ValueError):
    """Raised when no valid Ollama model can be resolved for the active mode."""


def is_ollama_cloud_model(model: "str | None") -> bool:
    """Recognize Ollama Cloud model identifiers.

    Cloud models appear in two official forms:

    - ``qwen3.5:cloud`` (``:cloud`` runtime suffix)
    - ``gpt-oss:120b-cloud`` (tag ending in ``-cloud``)

    Detection that only checks ``':cloud' in model`` misses the second form, so
    both are handled explicitly here.
    """
    if not model:
        return False
    normalized = str(model).strip().lower()
    if not normalized:
        return False
    tag = normalized.split(":", 1)[1] if ":" in normalized else ""
    if tag == "cloud" or tag.endswith("-cloud"):
        return True
    # Bare ``model-cloud`` form without a tag separator.
    if normalized.endswith("-cloud") and ":" not in normalized:
        return True
    return False


def get_effective_ollama_model(
    mode: "str | None" = None,
    model_override: "str | None" = None,
) -> str:
    """Resolve the effective Ollama model for the active execution mode.

    Resolution order:

    1. explicit request/Web/task ``model_override``;
    2. ``OLLAMA_CLOUD_MODEL`` when the active mode is cloud;
    3. ``OLLAMA_MODEL`` when the active mode is local;
    4. compatibility fallback: a cloud-tagged ``OLLAMA_MODEL`` is allowed in
       cloud mode;
    5. otherwise raise :class:`OllamaModelError`.

    The deployment mode is never inferred from the model name; cloud detection
    only affects request tuning and usage labels elsewhere.
    """
    if model_override and str(model_override).strip():
        return str(model_override).strip()

    resolved_mode = get_active_config_mode(mode)

    cloud_model = (get_config_value("OLLAMA_CLOUD_MODEL", "") or "").strip()
    local_model = (get_config_value("OLLAMA_MODEL", "") or "").strip()

    if resolved_mode == "cloud":
        if cloud_model:
            if not is_ollama_cloud_model(cloud_model):
                raise OllamaModelError(
                    "OLLAMA_CLOUD_MODEL must be a cloud-tagged Ollama model "
                    "(for example 'qwen3.5:cloud' or 'gpt-oss:120b-cloud'); "
                    f"got {cloud_model!r}."
                )
            return cloud_model
        # Compatibility: allow a legacy OLLAMA_MODEL only if already cloud-tagged.
        if local_model and is_ollama_cloud_model(local_model):
            return local_model
        raise OllamaModelError(
            "No cloud Ollama model configured. Set OLLAMA_CLOUD_MODEL to a "
            "cloud-tagged model (e.g. 'qwen3.5:cloud')."
        )

    if local_model:
        return local_model

    raise OllamaModelError(
        "No local Ollama model configured. Set OLLAMA_MODEL for local mode."
    )


def resolve_ollama_model(
    mode: "str | None" = None,
    model_override: "str | None" = None,
    local_fallback: "str | None" = "qwen3.5:latest",
) -> str:
    """Resolve the effective Ollama model with a safe local-mode fallback.

    Cloud mode still fails clearly (via :class:`OllamaModelError`) when no
    cloud-tagged model is available, but local mode falls back to
    ``local_fallback`` when ``OLLAMA_MODEL`` is unset, preserving existing
    behavior for auxiliary tasks (feedback, self-play, tool builder, etc.).
    """
    try:
        return get_effective_ollama_model(mode, model_override=model_override)
    except OllamaModelError:
        if get_active_config_mode(mode) == "cloud":
            raise
        if model_override and str(model_override).strip():
            return str(model_override).strip()
        return get_config_value("OLLAMA_MODEL", local_fallback)


def _dedupe_urls(urls: Iterable[str]) -> list[str]:
    """Keep URL order stable while removing duplicates."""
    seen: set[str] = set()
    unique_urls: list[str] = []

    for url in urls:
        normalized = (url or "").strip().rstrip("/")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_urls.append(normalized)

    return unique_urls


def parse_ollama_base_urls(
    raw_value: str | list[str] | tuple[str, ...] | None,
    default: str = DEFAULT_OLLAMA_BASE_URL,
    include_localhost_fallback: bool = True,
) -> list[str]:
    """Parse a comma-separated Ollama URL list with optional localhost fallback."""
    candidates: list[str] = []

    if isinstance(raw_value, (list, tuple)):
        candidates.extend(str(item).strip() for item in raw_value)
    elif raw_value:
        candidates.extend(part.strip() for part in str(raw_value).split(","))

    if not candidates and default:
        candidates.append(default)

    if include_localhost_fallback and default:
        candidates.append(default)

    return _dedupe_urls(candidates)


def _localhost_fallback_is_default() -> bool:
    """Localhost fallback is local-mode-only by default.

    Cloud mode must not silently append or fail over to localhost when a
    configured remote host is down (container localhost is the Jarvis container,
    not the host Ollama daemon). An explicitly listed localhost is always kept.
    """
    try:
        return get_active_config_mode() == "local"
    except Exception:
        # If mode cannot be resolved, be conservative and do not inject localhost.
        return False


def get_ollama_base_urls(
    default: str = DEFAULT_OLLAMA_BASE_URL,
    include_localhost_fallback: "bool | None" = None,
) -> list[str]:
    """Return Ollama base URLs from config in fallback order.

    By default the localhost fallback is only added in local mode; callers may
    force it on/off explicitly.
    """
    if include_localhost_fallback is None:
        include_localhost_fallback = _localhost_fallback_is_default()
    return parse_ollama_base_urls(
        get_config_value("OLLAMA_BASE_URL", None),
        default=default,
        include_localhost_fallback=include_localhost_fallback,
    )


def get_primary_ollama_base_url(
    default: str = DEFAULT_OLLAMA_BASE_URL,
    include_localhost_fallback: "bool | None" = None,
) -> str:
    """Return the first configured Ollama URL."""
    return get_ollama_base_urls(
        default=default,
        include_localhost_fallback=include_localhost_fallback,
    )[0]


def _normalize_timeout(timeout):
    """Use a short connect timeout while preserving the caller's read timeout."""
    if timeout is None or isinstance(timeout, tuple):
        return timeout

    if isinstance(timeout, (int, float)):
        read_timeout = float(timeout)
        connect_timeout = min(3.0, max(1.0, read_timeout))
        return (connect_timeout, read_timeout)

    return timeout


def request_ollama(
    method: str,
    path: str,
    *,
    base_url: str | None = None,
    base_urls: list[str] | tuple[str, ...] | None = None,
    retry_statuses: tuple[int, ...] = (500, 502, 503, 504),
    timeout=None,
    **kwargs,
):
    """Send an Ollama request, falling back across configured hosts on outages."""
    import requests

    if base_urls is None and base_url is None:
        candidate_urls = get_ollama_base_urls()
    else:
        candidate_urls = parse_ollama_base_urls(
            base_urls if base_urls is not None else base_url,
            include_localhost_fallback=_localhost_fallback_is_default(),
        )
    if not candidate_urls:
        raise RuntimeError("No Ollama base URLs configured")

    normalized_path = "/" + path.lstrip("/")
    last_exception: Exception | None = None
    last_response = None
    last_response_url: str | None = None
    normalized_timeout = _normalize_timeout(timeout)

    for candidate in candidate_urls:
        try:
            response = requests.request(
                method,
                f"{candidate}{normalized_path}",
                timeout=normalized_timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            last_exception = exc
            continue

        if response.status_code in retry_statuses:
            last_response = response
            last_response_url = candidate
            continue

        return response, candidate

    if last_response is not None:
        return last_response, (last_response_url or candidate_urls[-1])

    if last_exception is not None:
        raise last_exception

    raise RuntimeError("Ollama request failed without a response")
