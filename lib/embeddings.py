#!/usr/bin/env python3
"""Jarvis Embedding served by configured Ollama daemon hosts.

Jarvis intentionally has one embedding contract for both cloud and local data:
the versioned Jarvis Embedding BF16 artifact, 768 dimensions, and Google's
EmbeddingGemma asymmetric prompt formats. Chat provider selection is unrelated
to this module.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Literal, Sequence

from config_loader import get_config_value, get_int
from ollama_utils import get_ollama_base_urls, request_ollama

logger = logging.getLogger(__name__)

EMBEDDING_PROVIDER = "ollama"
EMBEDDING_MODEL_FAMILY = "embeddinggemma"
EMBEDDING_MODEL_DEFAULT = "bigsk1/jarvis-embedding:bf16-v1"
EMBEDDING_DIMENSIONS = 768
EMBEDDING_PROMPT_PROFILE = "embeddinggemma-official-v1"
EMBEDDING_CONTEXT_WINDOW = 2048

# Jarvis-owned Ollama tag copied from the official EmbeddingGemma BF16 manifest.
# Changing this value or its tag requires rebuilding every persisted namespace.
EMBEDDING_MODEL_DIGEST_DEFAULT = (
    "85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1"
)

EmbeddingRole = Literal["query", "document", "similarity"]


class EmbeddingError(RuntimeError):
    """Base error for the unified embedding contract."""


class EmbeddingConfigurationError(EmbeddingError):
    """Raised when the configured model violates the Jarvis contract."""


class EmbeddingRuntimeError(EmbeddingError):
    """Raised when no verified Ollama host can serve the configured artifact."""


class PersistentEmbeddingError(EmbeddingError):
    """Raised when a real provider embedding cannot be produced for storage."""


@dataclass(frozen=True)
class EmbeddingRuntime:
    """Verified Ollama hosts for the configured immutable model artifact."""

    model: str
    digest: str
    base_urls: tuple[str, ...]
    unavailable_hosts: tuple[str, ...] = ()
    missing_model_hosts: tuple[str, ...] = ()


_RUNTIME_CACHE_LOCK = threading.Lock()
_RUNTIME_CACHE: dict[tuple, tuple[float, EmbeddingRuntime]] = {}
_RUNTIME_CACHE_SECONDS = 300.0


def get_effective_embedding_provider(mode: str | None = None) -> str:
    """Return the single supported embedding provider."""
    del mode
    return EMBEDDING_PROVIDER


def get_embedding_model() -> str:
    """Return and validate the configured Jarvis Embedding model tag."""
    model = str(
        get_config_value("OLLAMA_EMBEDDING_MODEL", EMBEDDING_MODEL_DEFAULT)
        or EMBEDDING_MODEL_DEFAULT
    ).strip()
    if model != EMBEDDING_MODEL_DEFAULT:
        raise EmbeddingConfigurationError(
            "Jarvis supports only its pinned embedding artifact. Set "
            f"OLLAMA_EMBEDDING_MODEL={EMBEDDING_MODEL_DEFAULT} and rebuild "
            "the databases."
        )
    return model


def get_embedding_model_digest() -> str:
    """Return the explicitly expected Ollama artifact digest."""
    digest = str(
        get_config_value(
            "OLLAMA_EMBEDDING_MODEL_DIGEST",
            EMBEDDING_MODEL_DIGEST_DEFAULT,
        )
        or ""
    ).strip().lower()
    if digest.startswith("sha256:"):
        digest = digest[7:]
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise EmbeddingConfigurationError(
            "OLLAMA_EMBEDDING_MODEL_DIGEST must be a 64-character SHA-256 digest."
        )
    return digest


def get_embedding_fingerprint(role: EmbeddingRole) -> dict[str, str | int]:
    """Return the complete configured fingerprint for one embedding role."""
    if role not in {"query", "document", "similarity"}:
        raise EmbeddingConfigurationError(f"Unsupported embedding role: {role!r}")
    return {
        "provider": EMBEDDING_PROVIDER,
        "model_family": EMBEDDING_MODEL_FAMILY,
        "model": get_embedding_model(),
        "model_digest": get_embedding_model_digest(),
        "dimensions": EMBEDDING_DIMENSIONS,
        "prompt_profile": EMBEDDING_PROMPT_PROFILE,
        "prompt_role": role,
    }


def format_embedding_input(
    text: str,
    *,
    role: EmbeddingRole,
    title: str | None = None,
) -> str:
    """Apply Google's official EmbeddingGemma prompt for the input role."""
    content = str(text or "").strip()
    if not content:
        raise ValueError("Embedding input cannot be empty")
    if role == "query":
        return f"task: search result | query: {content}"
    if role == "similarity":
        return f"task: sentence similarity | query: {content}"
    if role == "document":
        clean_title = " ".join(str(title or "none").split()) or "none"
        return f"title: {clean_title} | text: {content}"
    raise EmbeddingConfigurationError(f"Unsupported embedding role: {role!r}")


def _normalized_model_name(model: str) -> str:
    normalized = model.strip().lower()
    return normalized if ":" in normalized else f"{normalized}:latest"


def clear_embedding_runtime_cache() -> None:
    """Clear cached host verification, primarily for health checks and tests."""
    with _RUNTIME_CACHE_LOCK:
        _RUNTIME_CACHE.clear()


def _resolve_embedding_runtime(*, force_refresh: bool = False) -> EmbeddingRuntime:
    """Verify model digests and return only compatible daemon hosts."""
    model = get_embedding_model()
    expected_digest = get_embedding_model_digest()
    base_urls = tuple(get_ollama_base_urls())
    cache_key = (model, expected_digest, base_urls)
    now = time.monotonic()

    with _RUNTIME_CACHE_LOCK:
        cached = _RUNTIME_CACHE.get(cache_key)
        if cached and not force_refresh and now - cached[0] < _RUNTIME_CACHE_SECONDS:
            return cached[1]

    wanted_name = _normalized_model_name(model)
    compatible: list[str] = []
    unavailable: list[str] = []
    missing: list[str] = []
    mismatches: list[tuple[str, str]] = []

    for base_url in base_urls:
        try:
            response, _ = request_ollama(
                "get",
                "/api/tags",
                base_url=base_url,
                include_localhost_fallback=False,
                timeout=5,
            )
        except Exception as exc:
            logger.warning("Embedding host unavailable during verification: %s (%s)", base_url, exc)
            unavailable.append(base_url)
            continue

        if response.status_code != 200:
            unavailable.append(base_url)
            continue

        found = None
        for entry in response.json().get("models", []):
            names = {
                _normalized_model_name(str(entry.get("name") or "")),
                _normalized_model_name(str(entry.get("model") or "")),
            }
            if wanted_name in names:
                found = entry
                break

        if not found:
            missing.append(base_url)
            continue

        actual_digest = str(found.get("digest") or "").lower().removeprefix("sha256:")
        if actual_digest != expected_digest:
            mismatches.append((base_url, actual_digest or "missing"))
            continue
        compatible.append(base_url)

    if mismatches:
        details = ", ".join(f"{url}={digest}" for url, digest in mismatches)
        raise EmbeddingRuntimeError(
            "Configured Ollama hosts expose a different Jarvis Embedding artifact "
            f"than OLLAMA_EMBEDDING_MODEL_DIGEST ({details}). Semantic embeddings are disabled."
        )
    if not compatible:
        details = []
        if unavailable:
            details.append("unavailable: " + ", ".join(unavailable))
        if missing:
            details.append("model missing: " + ", ".join(missing))
        suffix = f" ({'; '.join(details)})" if details else ""
        raise EmbeddingRuntimeError(
            f"No configured Ollama host can serve {model}@{expected_digest}{suffix}"
        )

    runtime = EmbeddingRuntime(
        model=model,
        digest=expected_digest,
        base_urls=tuple(compatible),
        unavailable_hosts=tuple(unavailable),
        missing_model_hosts=tuple(missing),
    )
    with _RUNTIME_CACHE_LOCK:
        _RUNTIME_CACHE[cache_key] = (now, runtime)
    return runtime


def get_embedding_runtime_status(*, force_refresh: bool = False) -> dict:
    """Return health details for the configured Ollama embedding hosts."""
    try:
        runtime = _resolve_embedding_runtime(force_refresh=force_refresh)
    except Exception as exc:
        # Health reporting must remain usable even when configuration parsing is
        # the failure we are trying to report.
        try:
            model = get_embedding_model()
        except Exception:
            model = str(
                get_config_value("OLLAMA_EMBEDDING_MODEL", EMBEDDING_MODEL_DEFAULT)
                or EMBEDDING_MODEL_DEFAULT
            ).strip()
        try:
            model_digest = get_embedding_model_digest()
        except Exception:
            model_digest = str(
                get_config_value(
                    "OLLAMA_EMBEDDING_MODEL_DIGEST",
                    EMBEDDING_MODEL_DIGEST_DEFAULT,
                )
                or ""
            ).strip()
        return {
            "ok": False,
            "model": model,
            "model_digest": model_digest,
            "compatible_hosts": [],
            "unavailable_hosts": [],
            "missing_model_hosts": [],
            "error": str(exc),
        }
    return {
        "ok": True,
        "model": runtime.model,
        "model_digest": runtime.digest,
        "compatible_hosts": list(runtime.base_urls),
        "unavailable_hosts": list(runtime.unavailable_hosts),
        "missing_model_hosts": list(runtime.missing_model_hosts),
        "error": None,
    }


def _compact_text_for_embedding(text: str, max_chars: int) -> str:
    """Trim oversized text while preserving both the start and end."""
    if len(text) <= max_chars:
        return text
    normalized = " ".join(text.split())
    if len(normalized) <= max_chars:
        return normalized
    if max_chars <= 32:
        return normalized[:max_chars]
    separator = " ... "
    available = max_chars - len(separator)
    head_chars = int(available * 0.7)
    tail_chars = max(0, available - head_chars)
    return f"{normalized[:head_chars].rstrip()}{separator}{normalized[-tail_chars:].lstrip()}"


def _is_ollama_context_length_error(error_text: str) -> bool:
    """Detect Ollama errors caused by oversized embedding input."""
    return "input length exceeds the context length" in (error_text or "").lower()


def _get_ollama_embedding_options() -> dict:
    """Return model-safe Ollama options without overriding GPU placement."""
    requested = get_int("OLLAMA_EMBEDDING_CONTEXT_WINDOW", EMBEDDING_CONTEXT_WINDOW)
    if requested <= 0:
        requested = EMBEDDING_CONTEXT_WINDOW
    return {"num_ctx": min(requested, EMBEDDING_CONTEXT_WINDOW)}


def _extract_ollama_embeddings(result: dict) -> list[list[float]]:
    embeddings = result.get("embeddings")
    if isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], list):
        return embeddings
    if isinstance(result.get("embedding"), list):
        return [result["embedding"]]
    raise KeyError("No embeddings found in Ollama response")


def _validate_vectors(vectors: Sequence[Sequence[float]], expected_count: int) -> list[list[float]]:
    if len(vectors) != expected_count:
        raise EmbeddingRuntimeError(
            f"Ollama returned {len(vectors)} embeddings for {expected_count} inputs"
        )
    result = [list(vector) for vector in vectors]
    wrong = [len(vector) for vector in result if len(vector) != EMBEDDING_DIMENSIONS]
    if wrong:
        raise EmbeddingRuntimeError(
            f"EmbeddingGemma returned invalid dimensions {wrong[:5]}; expected {EMBEDDING_DIMENSIONS}"
        )
    return result


def _request_embeddings(formatted_inputs: list[str]) -> list[list[float]]:
    runtime = _resolve_embedding_runtime()
    options = _get_ollama_embedding_options()
    prompt_variants = [formatted_inputs]
    for max_chars in (6000, 4000, 2500, 1500):
        compacted = [_compact_text_for_embedding(text, max_chars) for text in formatted_inputs]
        if compacted != prompt_variants[-1]:
            prompt_variants.append(compacted)

    for index, prompts in enumerate(prompt_variants):
        response, _ = request_ollama(
            "post",
            "/api/embed",
            base_urls=list(runtime.base_urls),
            include_localhost_fallback=False,
            json={
                "model": runtime.model,
                "input": prompts if len(prompts) > 1 else prompts[0],
                "dimensions": EMBEDDING_DIMENSIONS,
                "truncate": True,
                "options": options,
            },
            timeout=30,
        )

        if response.status_code == 200:
            return _validate_vectors(_extract_ollama_embeddings(response.json()), len(prompts))

        error_text = response.text
        if _is_ollama_context_length_error(error_text) and index < len(prompt_variants) - 1:
            logger.warning("Embedding input too long; retrying with compacted text")
            continue
        raise EmbeddingRuntimeError(f"Ollama embedding API error: {error_text}")

    raise EmbeddingRuntimeError("Ollama embedding input exceeded the supported context")


def _get_ollama_embedding(
    text: str,
    *,
    role: EmbeddingRole = "query",
    title: str | None = None,
) -> list[float]:
    """Generate one verified EmbeddingGemma vector through Ollama."""
    formatted = format_embedding_input(text, role=role, title=title)
    return _request_embeddings([formatted])[0]


def get_embedding(
    text: str,
    *,
    role: EmbeddingRole = "query",
    title: str | None = None,
) -> list[float]:
    """Generate one embedding using the unified Jarvis contract."""
    return _get_ollama_embedding(text, role=role, title=title)


def get_persistable_embedding(
    text: str,
    *,
    role: EmbeddingRole = "document",
    title: str | None = None,
    max_attempts: int = 1,
    retry_delay_seconds: float = 1.0,
) -> list[float]:
    """Generate a real embedding with bounded retry and no hash fallback."""
    attempts = max(1, int(max_attempts))
    delay = max(0.0, float(retry_delay_seconds))
    last_reason = "embedding runtime unavailable"
    for attempt in range(1, attempts + 1):
        try:
            return get_embedding(text, role=role, title=title)
        except Exception as exc:
            last_reason = f"{type(exc).__name__}: {exc}"
            if attempt < attempts:
                logger.warning(
                    "Persistent embedding attempt %s/%s failed: %s",
                    attempt,
                    attempts,
                    last_reason,
                )
                if delay:
                    time.sleep(delay * (2 ** (attempt - 1)))
    raise PersistentEmbeddingError(
        f"Could not generate a persistable embedding after {attempts} attempt(s): {last_reason}"
    )


def get_embeddings_batch(
    texts: list[str],
    *,
    role: EmbeddingRole = "document",
    titles: list[str | None] | None = None,
) -> list[list[float]]:
    """Generate an Ollama batch while preserving each input's prompt role."""
    if not texts:
        return []
    if titles is not None and len(titles) != len(texts):
        raise ValueError("titles must have the same length as texts")
    resolved_titles = titles or [None] * len(texts)
    formatted = [
        format_embedding_input(text, role=role, title=title)
        for text, title in zip(texts, resolved_titles)
    ]
    return _request_embeddings(formatted)


def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """Calculate cosine similarity and reject partial dimension comparisons."""
    if len(vec1) != len(vec2):
        raise ValueError(f"Embedding dimension mismatch: {len(vec1)} != {len(vec2)}")
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    magnitude1 = math.sqrt(sum(a * a for a in vec1))
    magnitude2 = math.sqrt(sum(b * b for b in vec2))
    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0
    return dot_product / (magnitude1 * magnitude2)
