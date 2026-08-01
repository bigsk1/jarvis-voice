"""Shared speech-to-text provider helpers.

This module intentionally keeps the OpenAI service and generic OpenAI-compatible
servers as separate providers.  A compatible server never inherits OpenAI's URL
or credentials implicitly.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Callable, Optional, TypeVar
from urllib.parse import urlparse

import requests


SUPPORTED_STT_PROVIDERS = ("faster-whisper", "openai", "openai-compatible")
RETRYABLE_HTTP_STATUSES = {408, 425, 429}


class STTProviderError(RuntimeError):
    """A provider failure with an explicit fallback classification."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        status_code: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


def normalize_stt_provider(provider: str) -> str:
    """Normalize and validate an STT provider name."""

    normalized = str(provider or "").strip().lower()
    if normalized not in SUPPORTED_STT_PROVIDERS:
        supported = ", ".join(SUPPORTED_STT_PROVIDERS)
        raise ValueError(f"Unsupported STT_PROVIDER '{provider}'. Expected one of: {supported}")
    return normalized


def default_model_for_provider(provider: str) -> str:
    """Return the provider-specific default used when a model is omitted."""

    provider = normalize_stt_provider(provider)
    if provider == "faster-whisper":
        return "small.en"
    if provider == "openai-compatible":
        return "parakeet-en"
    return "whisper-1"


def resolve_transcriptions_url(base_url: str) -> str:
    """Accept a server root, ``/v1`` base URL, or the full transcription URL."""

    value = str(base_url or "").strip().rstrip("/")
    if not value:
        raise ValueError("STT_BASE_URL is required for openai-compatible STT")

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("STT_BASE_URL must be an http:// or https:// URL")

    if value.endswith("/audio/transcriptions"):
        return value
    if value.endswith("/v1"):
        return f"{value}/audio/transcriptions"
    return f"{value}/v1/audio/transcriptions"


def parse_stt_timeout(value: object, default: float = 30.0) -> float:
    """Parse a positive STT request timeout."""

    if value in (None, ""):
        return default
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("STT_TIMEOUT_SECONDS must be a positive number") from exc
    if timeout <= 0:
        raise ValueError("STT_TIMEOUT_SECONDS must be a positive number")
    return timeout


def _response_error_message(response: requests.Response) -> str:
    # Do not surface an arbitrary upstream body into Jarvis logs or the UI.
    return f"STT endpoint returned HTTP {response.status_code}"


def transcribe_openai_compatible(
    audio_path: str,
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout: float = 30.0,
) -> str:
    """Transcribe one audio file through an OpenAI-compatible endpoint."""

    url = resolve_transcriptions_url(base_url)
    model = str(model or "").strip()
    if not model:
        raise ValueError("STT_MODEL must not be empty")

    path = Path(audio_path)
    if not path.is_file():
        raise ValueError(f"Audio file does not exist: {audio_path}")

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        with path.open("rb") as audio_file:
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if path.suffix.lower() == ".webm":
                content_type = "audio/webm"
            response = requests.post(
                url,
                headers=headers,
                files={"file": (path.name, audio_file, content_type)},
                data={"model": model, "response_format": "json"},
                timeout=parse_stt_timeout(timeout),
            )
    except (requests.Timeout, requests.ConnectionError) as exc:
        raise STTProviderError(
            f"STT endpoint is unavailable: {exc}", retryable=True
        ) from exc
    except requests.RequestException as exc:
        raise STTProviderError(f"STT request failed: {exc}", retryable=False) from exc

    if response.status_code != 200:
        retryable = (
            response.status_code in RETRYABLE_HTTP_STATUSES
            or response.status_code >= 500
        )
        raise STTProviderError(
            _response_error_message(response),
            retryable=retryable,
            status_code=response.status_code,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise STTProviderError(
            "STT endpoint returned invalid JSON", retryable=False
        ) from exc

    if not isinstance(payload, dict) or "text" not in payload:
        raise STTProviderError(
            "STT endpoint response did not contain 'text'", retryable=False
        )
    return str(payload.get("text") or "").strip()


T = TypeVar("T")


def run_with_stt_fallback(
    primary_provider: str,
    fallback_provider: str,
    transcriber: Callable[[str], T],
    *,
    on_fallback: Optional[Callable[[str, str, STTProviderError], None]] = None,
) -> T:
    """Run an optional fallback only for a retryable provider failure."""

    primary = normalize_stt_provider(primary_provider)
    fallback = str(fallback_provider or "").strip().lower()
    if fallback:
        fallback = normalize_stt_provider(fallback)
        if fallback == primary:
            raise ValueError("STT_FALLBACK_PROVIDER must differ from STT_PROVIDER")

    try:
        return transcriber(primary)
    except STTProviderError as exc:
        if not fallback or not exc.retryable:
            raise
        if on_fallback:
            on_fallback(primary, fallback, exc)
        return transcriber(fallback)
