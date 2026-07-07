#!/usr/bin/env python3
"""
Embeddings Module - Generate vector embeddings for semantic search
Supports:
- OpenAI text-embedding-3-small (cloud mode)
- Ollama nomic-embed-text (local mode)
"""
import logging
import threading
import time
from importlib.util import find_spec

from config_loader import get_config_value, get_int, get_active_config_mode
from ollama_utils import get_ollama_base_urls, request_ollama


_EMBEDDING_FALLBACK_STATE = threading.local()


class PersistentEmbeddingError(RuntimeError):
    """Raised when a real provider embedding cannot be produced for storage."""


def get_effective_embedding_provider(mode: "str | None" = None) -> str:
    """Resolve the embedding provider independently of the chat provider.

    Priority: explicit ``EMBEDDING_PROVIDER`` -> ``ollama`` for local mode ->
    ``openai`` for cloud mode. The chat ``LLM_PROVIDER`` is never used as the
    embedding fallback, so a cloud database keeps its OpenAI/1536-dim vectors
    even when chat uses Ollama.
    """
    explicit = (get_config_value("EMBEDDING_PROVIDER", "") or "").strip().lower()
    if explicit:
        return explicit
    return "ollama" if get_active_config_mode(mode) == "local" else "openai"


def reset_embedding_fallback_tracking():
    """Reset per-thread fallback tracking for the current operation."""
    _EMBEDDING_FALLBACK_STATE.events = []


def _record_embedding_fallback(provider: str, text: str, reason: str | None = None):
    """Record that a fallback embedding was used during the current operation."""
    events = list(getattr(_EMBEDDING_FALLBACK_STATE, "events", []))
    events.append({
        "provider": provider,
        "reason": (reason or "")[:300],
        "text_preview": (text or "")[:120],
    })
    _EMBEDDING_FALLBACK_STATE.events = events


def consume_embedding_fallback_tracking() -> dict:
    """Return and clear fallback tracking for the current operation."""
    events = list(getattr(_EMBEDDING_FALLBACK_STATE, "events", []))
    _EMBEDDING_FALLBACK_STATE.events = []
    providers = sorted({event.get("provider", "unknown") for event in events})
    return {
        "fallback_embeddings": True if events else None,
        "fallback_count": len(events),
        "fallback_providers": providers,
        "fallback_reasons": [event.get("reason", "") for event in events if event.get("reason")],
    }


def get_persistable_embedding(
    text: str,
    provider: str = None,
    *,
    max_attempts: int = 1,
    retry_delay_seconds: float = 1.0,
) -> list[float]:
    """Generate a real provider embedding, rejecting hash fallbacks.

    Query-time callers should continue using ``get_embedding`` so temporary
    fallback remains available. Database writers use this helper to prevent a
    provider outage from being persisted as a valid semantic vector.
    """
    attempts = max(1, int(max_attempts))
    delay = max(0.0, float(retry_delay_seconds))
    last_reason = "embedding provider unavailable"

    for attempt in range(1, attempts + 1):
        reset_embedding_fallback_tracking()
        try:
            embedding = get_embedding(text, provider=provider)
        except Exception as exc:
            consume_embedding_fallback_tracking()
            last_reason = f"{type(exc).__name__}: {exc}"
        else:
            diagnostics = consume_embedding_fallback_tracking()
            if not diagnostics.get("fallback_embeddings"):
                return embedding
            reasons = diagnostics.get("fallback_reasons") or []
            fallback_reason = "; ".join(reasons) or "provider unavailable"
            last_reason = f"fallback embedding returned: {fallback_reason}"

        if attempt < attempts:
            logging.getLogger(__name__).warning(
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
    lowered = (error_text or "").lower()
    return "input length exceeds the context length" in lowered


def _get_ollama_embedding_options() -> dict:
    """Get runtime options for Ollama embedding requests."""
    options = {}

    embedding_ctx = get_int("OLLAMA_EMBEDDING_CONTEXT_WINDOW", 0)
    if embedding_ctx <= 0:
        embedding_ctx = get_int("OLLAMA_CONTEXT_WINDOW", 0)

    if embedding_ctx > 0:
        options["num_ctx"] = embedding_ctx

    return options


def _extract_ollama_embedding(result: dict) -> list[float]:
    """Support both /api/embed and legacy /api/embeddings response shapes."""
    if "embedding" in result:
        return result["embedding"]

    embeddings = result.get("embeddings")
    if embeddings and isinstance(embeddings, list):
        first = embeddings[0]
        if isinstance(first, list):
            return first

    raise KeyError("No embedding found in Ollama response")


def get_embedding(text: str, provider: str = None) -> list[float]:
    """
    Generate embedding vector for text using configured provider.
    
    Args:
        text: Text to embed
        provider: Override provider ('openai' or 'ollama'), or None to auto-detect from config
        
    Returns:
        List of floats representing the embedding vector
    """
    # Resolve provider from embedding policy (mode-based), never chat provider.
    if provider is None:
        provider = get_effective_embedding_provider()
    
    if provider == "ollama":
        return _get_ollama_embedding(text)
    else:
        return _get_openai_embedding(text)


def _get_openai_embedding(text: str) -> list[float]:
    """Generate embedding using OpenAI with fallback to simple hash-based embedding."""
    try:
        from openai import OpenAI
    except ImportError:
        # Fallback if openai not installed
        _record_embedding_fallback("openai", text, "openai package not installed")
        return _get_fallback_embedding(text, dimensions=1536)
    
    # Get API key from config
    api_key = get_config_value("OPENAI_API_KEY")
    if not api_key:
        # Fallback if no API key
        _record_embedding_fallback("openai", text, "OPENAI_API_KEY missing")
        return _get_fallback_embedding(text, dimensions=1536)
    
    try:
        client = OpenAI(api_key=api_key)
        
        # Use text-embedding-3-small (cheapest, 1536 dimensions)
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
            encoding_format="float"
        )
        
        return response.data[0].embedding
    except Exception as e:
        # Fallback on any API error
        import logging
        logging.getLogger(__name__).warning(f"OpenAI embedding failed, using fallback: {e}")
        _record_embedding_fallback("openai", text, str(e))
        return _get_fallback_embedding(text, dimensions=1536)


def _get_fallback_embedding(text: str, dimensions: int = 1536) -> list[float]:
    """
    Fallback embedding using deterministic hash-based approach.
    Not semantically meaningful, but allows system to continue functioning.
    
    WARNING: This is used when real embedding APIs fail!
    - Same text → same embedding (deterministic)
    - Similar text → random similarity (NO semantic meaning)
    """
    import hashlib
    import math
    import logging
    
    logger = logging.getLogger(__name__)
    logger.warning(f"⚠️  FALLBACK EMBEDDING ACTIVE - semantic matching degraded! (text: '{text[:50]}...')")
    
    # Create deterministic hash
    text_bytes = text.lower().encode('utf-8')
    hash_bytes = hashlib.sha512(text_bytes).digest()
    
    # Expand hash to required dimensions using repeated hashing
    embedding = []
    seed = hash_bytes
    
    while len(embedding) < dimensions:
        # Hash the seed to get more bytes
        seed = hashlib.sha512(seed).digest()
        # Convert bytes to floats in range [-1, 1]
        for byte in seed:
            if len(embedding) >= dimensions:
                break
            # Map 0-255 to -1.0 to 1.0
            embedding.append((byte / 127.5) - 1.0)
    
    # Normalize to unit length (important for cosine similarity)
    magnitude = math.sqrt(sum(x*x for x in embedding))
    if magnitude > 0:
        embedding = [x / magnitude for x in embedding]
    
    return embedding


def _get_ollama_embedding(text: str) -> list[float]:
    """Generate embedding using Ollama with nomic-embed-text, with fallback."""
    if find_spec("requests") is None:
        _record_embedding_fallback("ollama", text, "requests package not installed")
        return _get_fallback_embedding(text, dimensions=768)
    
    base_urls = get_ollama_base_urls()
    
    # Use nomic-embed-text model (768 dimensions, fast, local)
    model = get_config_value("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
    options = _get_ollama_embedding_options()

    prompt_variants = [text]
    for max_chars in (6000, 4000, 2500, 1500):
        compacted = _compact_text_for_embedding(text, max_chars)
        if compacted != prompt_variants[-1]:
            prompt_variants.append(compacted)

    try:
        for idx, prompt in enumerate(prompt_variants):
            response, used_base_url = request_ollama(
                "post",
                "/api/embed",
                base_urls=base_urls,
                json={
                    "model": model,
                    "input": prompt,
                    "truncate": True,
                    "options": options,
                },
                    timeout=30
            )

            if response.status_code == 404:
                legacy_payload = {
                    "model": model,
                    "prompt": prompt,
                }
                if options:
                    legacy_payload["options"] = options
                response, _ = request_ollama(
                    "post",
                    "/api/embeddings",
                    base_url=used_base_url,
                    json=legacy_payload,
                    timeout=30
                )

            if response.status_code == 200:
                result = response.json()
                return _extract_ollama_embedding(result)

            error_text = response.text
            if _is_ollama_context_length_error(error_text) and idx < len(prompt_variants) - 1:
                import logging
                logging.getLogger(__name__).warning(
                    "Ollama embedding input too long; retrying with compacted text (%s -> %s chars)",
                    len(prompt),
                    len(prompt_variants[idx + 1]),
                )
                continue

            raise Exception(f"Ollama API error: {error_text}")
    except Exception as e:
        # Fallback on any error (connection, timeout, etc.)
        import logging
        logging.getLogger(__name__).warning(f"Ollama embedding failed, using fallback: {e}")
        _record_embedding_fallback("ollama", text, str(e))
        return _get_fallback_embedding(text, dimensions=768)


def get_embeddings_batch(texts: list[str], provider: str = None) -> list[list[float]]:
    """
    Generate embeddings for multiple texts (more efficient when supported).
    
    Args:
        texts: List of texts to embed
        provider: Override provider ('openai' or 'ollama'), or None to auto-detect
        
    Returns:
        List of embedding vectors
    """
    # Resolve provider from embedding policy (mode-based), never chat provider.
    if provider is None:
        provider = get_effective_embedding_provider()
    
    if provider == "ollama":
        # Ollama doesn't support batch, do one at a time
        return [_get_ollama_embedding(text) for text in texts]
    else:
        return _get_openai_embeddings_batch(texts)


def _get_openai_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """Generate embeddings batch using OpenAI."""
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("openai package required for embeddings. Run: pip install openai")
    
    api_key = get_config_value("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not found in config")
    
    client = OpenAI(api_key=api_key)
    
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=texts,
        encoding_format="float"
    )
    
    return [item.embedding for item in response.data]


def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """
    Calculate cosine similarity between two vectors.
    
    Args:
        vec1, vec2: Embedding vectors
        
    Returns:
        Similarity score (0 to 1, higher is more similar)
    """
    import math
    
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    magnitude1 = math.sqrt(sum(a * a for a in vec1))
    magnitude2 = math.sqrt(sum(b * b for b in vec2))
    
    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0
    
    return dot_product / (magnitude1 * magnitude2)
