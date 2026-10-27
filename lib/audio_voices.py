"""Read-only, bounded voice discovery for reusable spoken-audio generation."""

from __future__ import annotations

import base64
import ipaddress
import json
import re
import time
from urllib.parse import urlsplit, urlunsplit

import requests
from audio_generation import (
    _OPENAI_VOICES,
    PROVIDERS,
    _config,
    _credential,
    _local_url,
    get_audio_delivery_capabilities,
)
from http_client import get_session
from requests.adapters import HTTPAdapter

MAX_CATALOG_BYTES = 2 * 1024 * 1024
_PAGE_SIZE = 50
_ID = re.compile(r"^[A-Za-z0-9_. -]{1,160}$")
_LEGACY_OPENAI_VOICES = {"alloy", "ash", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer"}
_ELEVEN_MODELS = {
    "eleven_v3", "eleven_v4", "eleven_v4_turbo", "eleven_multilingual_v2",
    "eleven_multilingual_v1", "eleven_flash_v2_5", "eleven_turbo_v2_5",
    "eleven_flash_v2", "eleven_turbo_v2", "eleven_monolingual_v1",
}


class AudioVoiceCatalogError(RuntimeError):
    """A safe HTTP error with no response body, URL, or credentials attached."""

    def __init__(self, status: int):
        super().__init__(f"Voice catalog returned HTTP {status}")
        self.status = status


def _get_json(url: str, headers: dict, params: dict | None = None):
    session = get_session(use_proxy=False, retries=0)
    session.trust_env = False
    session.mount("http://", HTTPAdapter(max_retries=0))
    session.mount("https://", HTTPAdapter(max_retries=0))
    response = None
    deadline = time.monotonic() + 20
    try:
        response = session.get(url, headers=headers, params=params or {}, stream=True,
                               timeout=(5, 15), allow_redirects=False)
        if response.status_code != 200:
            raise AudioVoiceCatalogError(response.status_code)
        try:
            declared = int(response.headers.get("Content-Length", "0"))
        except ValueError:
            declared = 0
        if declared > MAX_CATALOG_BYTES:
            raise RuntimeError("Voice catalog exceeds the 2 MiB response limit")
        body = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            if time.monotonic() > deadline:
                raise RuntimeError("Voice catalog exceeded its time budget")
            if len(body) + len(chunk) > MAX_CATALOG_BYTES:
                raise RuntimeError("Voice catalog exceeds the 2 MiB response limit")
            body.extend(chunk)
        try:
            return json.loads(body)
        except (ValueError, UnicodeDecodeError):
            raise RuntimeError("Voice catalog returned unreadable JSON") from None
    except requests.RequestException:
        raise RuntimeError("Voice catalog connection failed; no audio was generated") from None
    finally:
        if response is not None:
            response.close()
        session.close()


def _text(value, maximum: int = 500) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:maximum]


def _preview_url(value) -> str | None:
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 32 for c in value):
        return None
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.fragment:
            return None
        if parsed.port not in (None, 443):
            return None
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host or host.lower().endswith((".local", ".internal", ".localhost", ".test", ".invalid")):
                return None
        else:
            if not address.is_global:
                return None
        return value
    except ValueError:
        return None


def _normalize(raw, provider: str, kind: str = "") -> list[dict]:
    if isinstance(raw, dict):
        for key in ("voices", "data", "speakers"):
            if key in raw:
                raw = raw[key]
                break
    if not isinstance(raw, list):
        raise RuntimeError("Voice catalog returned an unsupported voice list")
    result = []
    seen = set()
    for row in raw:
        if isinstance(row, str):
            row = {"id": row, "name": row}
        if not isinstance(row, dict):
            continue
        identifier = row.get("voice_id") or row.get("id") or row.get("speaker")
        if not isinstance(identifier, str) or identifier in seen:
            continue
        if provider in {"qwen3-tts", "kokoro"}:
            # These servers use configured voice names as IDs, including Unicode.
            # Match the generator's bounds without changing the returned name.
            if not identifier.strip() or len(identifier) > 160 or any(ord(c) < 32 for c in identifier):
                continue
        elif not _ID.fullmatch(identifier):
            continue
        seen.add(identifier)
        entry = {"provider": provider, "id": identifier, "voice_id": identifier,
                 "name": _text(row.get("name"), 200) or identifier}
        if kind:
            entry["kind"] = kind
        labels = row.get("labels") if isinstance(row.get("labels"), dict) else {}
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        for key in ("language", "accent", "gender"):
            value = _text(row.get(key) or labels.get(key) or metadata.get(key), 100)
            if value:
                entry[key] = value
        description = _text(row.get("description"))
        if description:
            entry["description"] = description
        preview = _preview_url(row.get("preview_url"))
        if preview:
            entry["preview_url"] = preview
        result.append(entry)
    return result


def _local_catalog_url(provider: str) -> str:
    key = "QWEN3_TTS_URL" if provider == "qwen3-tts" else "KOKORO_TTS_URL"
    parsed = urlsplit(_local_url(key))
    suffix = "/v1/audio/speech"
    if not parsed.path.rstrip("/").endswith(suffix):
        raise ValueError(f"{key} must end with /v1/audio/speech for voice discovery")
    prefix = parsed.path.rstrip("/")[:-len(suffix)]
    endpoint = "/v1/voices" if provider == "qwen3-tts" else "/v1/audio/voices"
    # Retain reverse-proxy path prefixes, never speech query parameters.
    return urlunsplit((parsed.scheme, parsed.netloc, prefix + endpoint, "", ""))


def _cursor_encode(context: dict, phase: str, token: str, offset: int) -> str:
    data = {**context, "v": 1, "phase": phase, "token": token, "offset": offset}
    return base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode().rstrip("=")


def _cursor_decode(value: str, context: dict) -> tuple[str, str, int]:
    try:
        if len(value) > 12000 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError
        data = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        if not isinstance(data, dict) or data.get("v") != 1 or any(data.get(key) != val for key, val in context.items()):
            raise ValueError
        phase, token, offset = (data[key] for key in ("phase", "token", "offset"))
        if phase not in {"main", "builtin", "custom"} or not isinstance(token, str) or len(token) > 4096:
            raise ValueError
        if type(offset) is not int or not 0 <= offset <= 1_000_000:
            raise ValueError
        if context["provider"] != "xai" and phase != "main":
            raise ValueError
        if context["provider"] == "xai" and phase not in {"builtin", "custom"}:
            raise ValueError
        return phase, token, offset
    except (ValueError, KeyError, TypeError):
        raise ValueError("Invalid voice cursor or changed provider/search/model; start a new search") from None


def _token(value) -> str:
    if value is None or value == "":
        return ""
    if not isinstance(value, str) or len(value) > 4096:
        raise RuntimeError("Voice catalog returned an invalid pagination token")
    return value


def _eleven_matches(row, query: str) -> bool:
    """Filter extra default voices using only documented searchable metadata."""
    if not query:
        return True
    if not isinstance(row, dict):
        return False
    values = [_text(row.get(key)) for key in ("voice_id", "name", "description", "category")]
    labels = row.get("labels") if isinstance(row.get("labels"), dict) else {}
    values.extend(_text(labels.get(key)) for key in (
        "language", "accent", "gender", "age", "use_case", "descriptive",
    ))
    return query.casefold() in " ".join(values).casefold()


def _fetch_page(provider: str, phase: str, token: str, query: str, model: str) -> tuple[list[dict], str]:
    if provider == "openai":
        voices = _LEGACY_OPENAI_VOICES if model in {"tts-1", "tts-1-hd"} else _OPENAI_VOICES
        return _normalize(sorted(voices), provider, "builtin"), ""
    if provider == "elevenlabs":
        params = {"page_size": _PAGE_SIZE, "sort": "name", "sort_direction": "asc"}
        if query:
            params["search"] = query
        if token:
            params["next_page_token"] = token
        data = _get_json("https://api.elevenlabs.io/v2/voices", {"xi-api-key": _credential("ELEVENLABS_API_KEY")}, params)
        if not isinstance(data, dict):
            raise RuntimeError("Voice catalog returned an unsupported voice list")
        next_token = _token(data.get("next_page_token")) if data.get("has_more") else ""
        if data.get("has_more") and not next_token:
            raise RuntimeError("Voice catalog omitted its next-page token")
        rows = data.get("voices")
        if not isinstance(rows, list):
            raise RuntimeError("Voice catalog returned an unsupported voice list")
        return _normalize([row for row in rows if _eleven_matches(row, query)], provider), next_token
    if provider == "xai":
        headers = {"Authorization": "Bearer " + _credential("XAI_API_KEY")}
        if phase == "builtin":
            data = _get_json("https://api.x.ai/v1/tts/voices", headers)
            return _normalize(data, provider, "builtin"), ""
        params = {"limit": _PAGE_SIZE}
        if token:
            params["pagination_token"] = token
        data = _get_json("https://api.x.ai/v1/custom-voices", headers, params)
        if not isinstance(data, dict):
            raise RuntimeError("Voice catalog returned an unsupported custom voice list")
        return _normalize(data, provider, "custom"), _token(data.get("pagination_token"))
    data = _get_json(_local_catalog_url(provider), {})
    return _normalize(data, provider), ""


def list_audio_voices(arguments: dict) -> dict:
    """List provider-scoped IDs without generating, cloning, or playing audio.

    Cursors carry a remote page start plus offset, so oversized provider pages
    (including ElevenLabs' extra default voices) are never silently truncated.
    No catalog or account response is cached or written to disk.
    """
    if not isinstance(arguments, dict) or set(arguments) - {"provider", "search", "limit", "cursor", "model"}:
        raise ValueError("Use only documented audio voice catalog arguments")
    for key in ("provider", "search", "cursor", "model"):
        if key in arguments and not isinstance(arguments[key], str):
            raise ValueError(f"{key} must be a string")
    current_provider = _config("AUDIO_TOOL_PROVIDER").lower()
    if current_provider not in PROVIDERS:
        raise ValueError("Set AUDIO_TOOL_PROVIDER to enable audio voice discovery")
    provider = arguments.get("provider", "").strip().lower() or current_provider
    if provider not in PROVIDERS:
        raise ValueError("Unsupported audio provider")
    limit = arguments.get("limit", 20)
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("Voice catalog limit must be an integer from 1 to 50")
    query = arguments.get("search", "").strip()
    if len(query) > 200:
        raise ValueError("Voice search must be at most 200 characters")
    model = arguments.get("model", "").strip()
    if not model and provider == current_provider:
        model = _config("AUDIO_TOOL_MODEL")
    if not model:
        if provider == "openai":
            model = _config("TTS_MODEL", "gpt-4o-mini-tts")
        elif provider == "elevenlabs":
            model = _config("ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2")
        else:
            model = {"xai": "grok-tts", "qwen3-tts": "tts-1", "kokoro": "kokoro"}[provider]
    if model and not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", model):
        raise ValueError("A valid speech model ID is required")
    if provider == "openai" and model not in {"tts-1", "tts-1-hd", "gpt-4o-mini-tts", "gpt-4o-mini-tts-2025-12-15"}:
        raise ValueError("Unsupported OpenAI speech model")
    if provider == "elevenlabs" and model not in _ELEVEN_MODELS:
        raise ValueError("Unsupported ElevenLabs speech model")
    service_models = {"xai": "grok-tts", "qwen3-tts": "tts-1", "kokoro": "kokoro"}
    if provider in service_models and model != service_models[provider]:
        raise ValueError("This speech service does not support selecting another model")
    # Validate selected credentials/endpoint even if this is a local builtin list.
    if provider in {"openai", "elevenlabs", "xai"}:
        _credential({"openai": "OPENAI_API_KEY", "elevenlabs": "ELEVENLABS_API_KEY", "xai": "XAI_API_KEY"}[provider])
    else:
        _local_catalog_url(provider)
    context = {"provider": provider, "search": query, "model": model}
    cursor = arguments.get("cursor", "")
    phase, token, offset = _cursor_decode(cursor, context) if cursor else ("builtin" if provider == "xai" else "main", "", 0)
    result = {"provider": provider, "current_provider": current_provider,
              "source": "documented_builtin" if provider == "openai" else "live_server" if provider in {"qwen3-tts", "kokoro"} else "live_account",
              "items": [], "count": 0, "has_more": False, "next_cursor": None,
              "delivery_capabilities": get_audio_delivery_capabilities(provider, model)}
    if model:
        result["model"] = model
    # At most three read-only pages per invocation; continuation stays explicit.
    items = []
    more = True
    for _ in range(3):
        try:
            page, next_token = _fetch_page(provider, phase, token, query, model)
        except AudioVoiceCatalogError as error:
            if provider != "xai" or phase != "custom" or error.status not in {403, 404}:
                raise
            result.update({"partial": True, "warning": f"Custom xAI voices are unavailable (HTTP {error.status}); built-in voices remain available"})
            more = False
            break
        while offset < len(page) and len(items) < limit:
            entry = page[offset]
            offset += 1
            searchable = " ".join(str(entry.get(key, "")) for key in (
                "id", "name", "description", "language", "accent", "gender",
            )).casefold()
            if provider == "elevenlabs" or not query or query.casefold() in searchable:
                items.append(entry)
        if offset < len(page):
            break
        if next_token:
            if next_token == token:
                raise RuntimeError("Voice catalog repeated its pagination token")
            token, offset = next_token, 0
        elif provider == "xai" and phase == "builtin":
            phase, token, offset = "custom", "", 0
        else:
            more = False
            break
        if len(items) >= limit:
            break
    result.update({"items": items, "count": len(items), "has_more": more,
                   "next_cursor": _cursor_encode(context, phase, token, offset) if more else None})
    return result
