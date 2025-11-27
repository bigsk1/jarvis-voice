#!/usr/bin/env python3
"""
Embeddings Module - Generate vector embeddings for semantic search
Supports:
- OpenAI text-embedding-3-small (cloud mode)
- Ollama nomic-embed-text (local mode)
"""
import os
from typing import List
from config_loader import get_config_value


def get_embedding(text: str, provider: str = None) -> List[float]:
    """
    Generate embedding vector for text using configured provider.
    
    Args:
        text: Text to embed
        provider: Override provider ('openai' or 'ollama'), or None to auto-detect from config
        
    Returns:
        List of floats representing the embedding vector
    """
    # Auto-detect provider from config if not specified
    if provider is None:
        llm_provider = get_config_value("LLM_PROVIDER", "openai")
        # Use same provider as LLM unless explicitly configured differently
        provider = get_config_value("EMBEDDING_PROVIDER", llm_provider)
    
    if provider == "ollama":
        return _get_ollama_embedding(text)
    else:
        return _get_openai_embedding(text)


def _get_openai_embedding(text: str) -> List[float]:
    """Generate embedding using OpenAI with fallback to simple hash-based embedding."""
    try:
        from openai import OpenAI
    except ImportError:
        # Fallback if openai not installed
        return _get_fallback_embedding(text, dimensions=1536)
    
    # Get API key from config
    api_key = get_config_value("OPENAI_API_KEY")
    if not api_key:
        # Fallback if no API key
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
        return _get_fallback_embedding(text, dimensions=1536)


def _get_fallback_embedding(text: str, dimensions: int = 1536) -> List[float]:
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


def _get_ollama_embedding(text: str) -> List[float]:
    """Generate embedding using Ollama with nomic-embed-text, with fallback."""
    try:
        import requests
    except ImportError:
        # Fallback if requests not installed
        return _get_fallback_embedding(text, dimensions=768)
    
    # Get Ollama base URL from config
    base_url = get_config_value("OLLAMA_BASE_URL", "http://localhost:11434")
    
    # Use nomic-embed-text model (768 dimensions, fast, local)
    model = get_config_value("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
    
    try:
        response = requests.post(
            f"{base_url}/api/embeddings",
            json={
                "model": model,
                "prompt": text
            },
            timeout=30
        )
        
        if response.status_code != 200:
            raise Exception(f"Ollama API error: {response.text}")
        
        result = response.json()
        return result["embedding"]
    except Exception as e:
        # Fallback on any error (connection, timeout, etc.)
        import logging
        logging.getLogger(__name__).warning(f"Ollama embedding failed, using fallback: {e}")
        return _get_fallback_embedding(text, dimensions=768)


def get_embeddings_batch(texts: List[str], provider: str = None) -> List[List[float]]:
    """
    Generate embeddings for multiple texts (more efficient when supported).
    
    Args:
        texts: List of texts to embed
        provider: Override provider ('openai' or 'ollama'), or None to auto-detect
        
    Returns:
        List of embedding vectors
    """
    # Auto-detect provider
    if provider is None:
        llm_provider = get_config_value("LLM_PROVIDER", "openai")
        provider = get_config_value("EMBEDDING_PROVIDER", llm_provider)
    
    if provider == "ollama":
        # Ollama doesn't support batch, do one at a time
        return [_get_ollama_embedding(text) for text in texts]
    else:
        return _get_openai_embeddings_batch(texts)


def _get_openai_embeddings_batch(texts: List[str]) -> List[List[float]]:
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


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
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

