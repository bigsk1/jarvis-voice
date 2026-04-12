#!/usr/bin/env python3
"""Helpers for working with Ollama hosts and fallback requests."""

from __future__ import annotations

from typing import Iterable

from config_loader import get_config_value


DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"


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


def get_ollama_base_urls(
    default: str = DEFAULT_OLLAMA_BASE_URL,
    include_localhost_fallback: bool = True,
) -> list[str]:
    """Return Ollama base URLs from config in fallback order."""
    return parse_ollama_base_urls(
        get_config_value("OLLAMA_BASE_URL", None),
        default=default,
        include_localhost_fallback=include_localhost_fallback,
    )


def get_primary_ollama_base_url(
    default: str = DEFAULT_OLLAMA_BASE_URL,
    include_localhost_fallback: bool = True,
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

    candidate_urls = parse_ollama_base_urls(
        base_urls if base_urls is not None else base_url,
        include_localhost_fallback=True,
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
