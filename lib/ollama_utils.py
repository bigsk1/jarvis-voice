#!/usr/bin/env python3
"""Helpers for working with Ollama hosts and fallback requests."""

from __future__ import annotations

from typing import Iterable

from config_loader import get_config_value, get_active_config_mode


DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_CLOUD_DIRECT_URL = "https://ollama.com"
OLLAMA_EXECUTION_LOCAL_DAEMON = "local_daemon"
OLLAMA_EXECUTION_SIGNED_IN_DAEMON_CLOUD = "signed_in_daemon_cloud"
OLLAMA_EXECUTION_DIRECT_CLOUD_API = "direct_cloud_api"


def get_ollama_api_key() -> str:
    """Return the configured Ollama cloud API key (never logged)."""
    return (get_config_value("OLLAMA_API_KEY", "") or "").strip()


def is_ollama_cloud_direct_url(url: str) -> bool:
    """True when the URL targets ollama.com's remote API host."""
    normalized = (url or "").strip().rstrip("/").lower()
    return normalized == OLLAMA_CLOUD_DIRECT_URL


def ollama_auth_headers_for_url(url: str) -> dict[str, str]:
    """Bearer auth for direct ollama.com API calls when OLLAMA_API_KEY is set."""
    if not is_ollama_cloud_direct_url(url):
        return {}
    key = get_ollama_api_key()
    if not key:
        return {}
    return {"Authorization": f"Bearer {key}"}


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


def allow_ollama_cloud_in_local(mode: "str | None" = None) -> bool:
    """Whether local mode may select cloud-tagged cards from its daemon."""
    if get_active_config_mode(mode) != "local":
        return False
    value = str(get_config_value("ALLOW_OLLAMA_CLOUD", "false") or "").strip().lower()
    return value in {"true", "1", "yes", "on"}


def get_ollama_execution_class(
    model: "str | None",
    mode: "str | None" = None,
) -> str:
    """Classify where an Ollama model executes independently of its raw ID."""
    resolved_mode = get_active_config_mode(mode)
    if resolved_mode == "cloud":
        if get_ollama_api_key():
            return OLLAMA_EXECUTION_DIRECT_CLOUD_API
        return OLLAMA_EXECUTION_SIGNED_IN_DAEMON_CLOUD
    if is_ollama_cloud_model(model):
        return OLLAMA_EXECUTION_SIGNED_IN_DAEMON_CLOUD
    return OLLAMA_EXECUTION_LOCAL_DAEMON


def is_ollama_cloud_execution(
    model: "str | None",
    mode: "str | None" = None,
) -> bool:
    """True for signed-daemon and direct-API cloud execution."""
    return get_ollama_execution_class(model, mode) != OLLAMA_EXECUTION_LOCAL_DAEMON


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
    resolved_mode = get_active_config_mode(mode)
    direct_cloud_api = ollama_uses_direct_cloud_api(resolved_mode)

    if model_override and str(model_override).strip():
        selected = str(model_override).strip()
        if resolved_mode == "cloud" and not direct_cloud_api and not is_ollama_cloud_model(selected):
            raise OllamaModelError(
                "Cloud-mode Ollama models must be cloud-tagged when using a signed-in daemon; "
                f"got {selected!r}."
            )
        if (
            resolved_mode == "local"
            and is_ollama_cloud_model(selected)
            and not allow_ollama_cloud_in_local(resolved_mode)
        ):
            raise OllamaModelError(
                "Cloud-tagged Ollama models are disabled in local mode. "
                "Set ALLOW_OLLAMA_CLOUD=true in config/local.env to enable them."
            )
        return selected

    cloud_model = (get_config_value("OLLAMA_CLOUD_MODEL", "") or "").strip()
    local_model = (get_config_value("OLLAMA_MODEL", "") or "").strip()

    if resolved_mode == "cloud":
        if cloud_model:
            if not direct_cloud_api and not is_ollama_cloud_model(cloud_model):
                raise OllamaModelError(
                    "OLLAMA_CLOUD_MODEL must be a cloud-tagged Ollama model when using a signed-in daemon "
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
        if is_ollama_cloud_model(local_model) and not allow_ollama_cloud_in_local(resolved_mode):
            raise OllamaModelError(
                "OLLAMA_MODEL is cloud-tagged but ALLOW_OLLAMA_CLOUD is disabled in local mode."
            )
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
        resolved_mode = get_active_config_mode(mode)
        rejected_model = str(model_override or get_config_value("OLLAMA_MODEL", "") or "").strip()
        if resolved_mode == "cloud" or (
            is_ollama_cloud_model(rejected_model)
            and not allow_ollama_cloud_in_local(resolved_mode)
        ):
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


def ollama_uses_direct_cloud_api(mode: "str | None" = None) -> bool:
    """True when cloud mode should talk to ollama.com via OLLAMA_API_KEY only."""
    if get_active_config_mode(mode) != "cloud":
        return False
    return bool(get_ollama_api_key())


def get_ollama_base_urls(
    default: str = DEFAULT_OLLAMA_BASE_URL,
    include_localhost_fallback: "bool | None" = None,
) -> list[str]:
    """Return configured Ollama daemon host URLs in fallback order."""
    if include_localhost_fallback is None:
        include_localhost_fallback = _localhost_fallback_is_default()
    return parse_ollama_base_urls(
        get_config_value("OLLAMA_BASE_URL", None),
        default=default,
        include_localhost_fallback=include_localhost_fallback,
    )


def get_ollama_request_urls(
    *,
    cloud_access: bool = False,
    base_url: "str | list[str] | tuple[str, ...] | None" = None,
    default: str = DEFAULT_OLLAMA_BASE_URL,
    include_localhost_fallback: "bool | None" = None,
) -> list[str]:
    """Resolve Ollama endpoint(s) for a request.

    Cloud-mode cloud-model access is either/or:

    - ``OLLAMA_API_KEY`` set → ``https://ollama.com`` only (Bearer auth)
    - no key → configured daemon host(s) from ``OLLAMA_BASE_URL`` only

    Local mode and non-cloud requests always use daemon hosts; the API key is
    ignored so local GPU inference is unaffected.
    """
    if cloud_access and ollama_uses_direct_cloud_api():
        return [OLLAMA_CLOUD_DIRECT_URL]
    if base_url is None:
        return get_ollama_base_urls(
            default=default,
            include_localhost_fallback=include_localhost_fallback,
        )
    if include_localhost_fallback is None:
        include_localhost_fallback = _localhost_fallback_is_default()
    return parse_ollama_base_urls(
        base_url,
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
    cloud_access: bool = False,
    include_localhost_fallback: "bool | None" = None,
    timeout=None,
    **kwargs,
):
    """Send an Ollama request, falling back across configured hosts on outages."""
    import requests

    if base_urls is None and base_url is None:
        candidate_urls = get_ollama_request_urls(cloud_access=cloud_access)
    else:
        if include_localhost_fallback is None:
            include_localhost_fallback = _localhost_fallback_is_default()
        candidate_urls = parse_ollama_base_urls(
            base_urls if base_urls is not None else base_url,
            include_localhost_fallback=include_localhost_fallback,
        )

    if not candidate_urls:
        raise RuntimeError("No Ollama base URLs configured")

    normalized_path = "/" + path.lstrip("/")
    last_exception: Exception | None = None
    last_response = None
    last_response_url: str | None = None
    normalized_timeout = _normalize_timeout(timeout)
    request_headers = dict(kwargs.pop("headers", {}) or {})

    for candidate in candidate_urls:
        headers = {**request_headers, **ollama_auth_headers_for_url(candidate)}
        try:
            response = requests.request(
                method,
                f"{candidate}{normalized_path}",
                timeout=normalized_timeout,
                headers=headers or None,
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
