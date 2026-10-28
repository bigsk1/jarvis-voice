#!/usr/bin/env python3
"""Prepare the optional Docker Ollama service without opening Jarvis databases."""

from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from embeddings import (  # noqa: E402
    EMBEDDING_CONTEXT_WINDOW,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL_DEFAULT,
    EMBEDDING_MODEL_DIGEST_DEFAULT,
    format_embedding_input,
)

DEFAULT_BASE_URL = "http://jarvis-ollama:11434"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class BootstrapError(RuntimeError):
    """The dedicated daemon cannot serve the pinned embedding artifact."""


class BootstrapHTTPError(BootstrapError):
    def __init__(self, path: str, status: int):
        self.status = status
        super().__init__(f"Ollama {path} returned HTTP {status}")


def _timeout_setting(name: str, default: int) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise BootstrapError(f"{name} must be between 1 and 7200 seconds") from exc
    if not math.isfinite(value) or not 1 <= value <= 7200:
        raise BootstrapError(f"{name} must be between 1 and 7200 seconds")
    return value


def _base_url() -> str:
    value = os.environ.get("OLLAMA_BASE_URL", DEFAULT_BASE_URL).strip()
    try:
        parsed = urlsplit(value)
        port = parsed.port
        valid = (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and parsed.path in {"", "/"}
            and not any(char.isspace() or char == "," for char in value)
            and (port is None or port > 0)
        )
    except ValueError:
        valid = False
    if not valid:
        raise BootstrapError("OLLAMA_BASE_URL must be one HTTP(S) daemon URL without credentials")
    return value.rstrip("/")


def create_session() -> requests.Session:
    session = requests.Session()
    # This service is deliberately private: no ambient proxies, netrc or keys.
    session.trust_env = False
    return session


def _request_json(session: requests.Session, base_url: str, method: str,
                  path: str, timeout: float, payload: dict | None = None) -> dict:
    deadline = time.monotonic() + timeout
    # Share the current budget between connect and read rather than allowing
    # each phase the full remaining startup window.
    connect_timeout = min(3.0, timeout / 2)
    with session.request(
        method, base_url + path, json=payload, stream=True,
        timeout=(connect_timeout, timeout - connect_timeout), allow_redirects=False,
    ) as response:
        if response.status_code != 200:
            raise BootstrapHTTPError(path, response.status_code)
        body = bytearray()
        for chunk in response.iter_content(chunk_size=8192):
            if time.monotonic() >= deadline:
                raise BootstrapError(f"Ollama {path} response exceeded its timeout")
            body.extend(chunk)
            if len(body) > MAX_RESPONSE_BYTES:
                raise BootstrapError(f"Ollama {path} response is too large")
        if time.monotonic() >= deadline:
            raise BootstrapError(f"Ollama {path} response exceeded its timeout")
        try:
            result = json.loads(body)
        except (ValueError, UnicodeError) as exc:
            raise BootstrapError(f"Ollama {path} returned invalid JSON") from exc
        if not isinstance(result, dict) or "error" in result:
            raise BootstrapError(f"Ollama {path} returned an invalid response")
        return result


def _has_pinned_model(tags: dict) -> bool:
    models = tags.get("models")
    if not isinstance(models, list):
        raise BootstrapError("Ollama /api/tags did not return a model list")
    found = []
    for entry in models:
        if not isinstance(entry, dict):
            raise BootstrapError("Ollama /api/tags returned an invalid model entry")
        names = [entry.get(key) for key in ("name", "model") if key in entry]
        if not names or any(not isinstance(name, str) or not name.strip() for name in names):
            raise BootstrapError("Ollama /api/tags returned an invalid model name")
        if len(set(names)) != 1:
            raise BootstrapError("Ollama /api/tags returned conflicting model names")
        if EMBEDDING_MODEL_DEFAULT in names:
            found.append(entry)
    if len(found) > 1:
        raise BootstrapError("Ollama /api/tags returned duplicate pinned model entries")
    if not found:
        return False
    digest = found[0].get("digest")
    if not isinstance(digest, str) or digest.lower().removeprefix("sha256:") != EMBEDDING_MODEL_DIGEST_DEFAULT:
        raise BootstrapError("The existing Jarvis embedding model has the wrong pinned digest; no model was replaced")
    return True


def wait_for_tags(session: requests.Session, base_url: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            tags = _request_json(session, base_url, "GET", "/api/tags", min(5.0, remaining))
        except BootstrapHTTPError as exc:
            if exc.status not in {502, 503, 504}:
                raise
        except requests.RequestException:
            pass
        else:
            if time.monotonic() >= deadline:
                break
            # A responding but malformed service is not a missing-model signal.
            _has_pinned_model(tags)
            return tags
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(1.0, remaining))
    raise BootstrapError("Ollama did not become ready before the startup timeout")


def _verify_embedding(result: dict) -> None:
    vectors = result.get("embeddings")
    if (result.get("model") != EMBEDDING_MODEL_DEFAULT
            or not isinstance(vectors, list) or len(vectors) != 1
            or not isinstance(vectors[0], list) or len(vectors[0]) != EMBEDDING_DIMENSIONS):
        raise BootstrapError("Ollama did not return one pinned-model embedding with the required dimensions")
    values = vectors[0]
    try:
        valid = all(not isinstance(value, bool) and isinstance(value, (int, float))
                    and math.isfinite(value) for value in values)
    except OverflowError:
        valid = False
    if not valid or not any(value != 0 for value in values):
        raise BootstrapError("Ollama returned a non-finite, invalid, or zero embedding")


def bootstrap(base_url: str, *, ready_timeout: float = 120,
              pull_timeout: float = 900, embed_timeout: float = 180) -> None:
    with create_session() as session:
        tags = wait_for_tags(session, base_url, ready_timeout)
        if not _has_pinned_model(tags):
            print("Downloading the pinned Jarvis embedding model into the Ollama volume...", flush=True)
            pulled = _request_json(session, base_url, "POST", "/api/pull", pull_timeout,
                                   {"model": EMBEDDING_MODEL_DEFAULT, "stream": False})
            if pulled.get("status") != "success":
                raise BootstrapError("Ollama did not confirm a successful embedding model pull")
            tags = _request_json(session, base_url, "GET", "/api/tags", 5)
            if not _has_pinned_model(tags):
                raise BootstrapError("The pinned Jarvis embedding model is missing after its pull")
        result = _request_json(session, base_url, "POST", "/api/embed", embed_timeout, {
            "model": EMBEDDING_MODEL_DEFAULT,
            "input": format_embedding_input("Jarvis Docker embedding readiness", role="query"),
            "dimensions": EMBEDDING_DIMENSIONS,
            "truncate": False,
            "options": {"num_ctx": EMBEDDING_CONTEXT_WINDOW},
        })
        _verify_embedding(result)
    print("Pinned Jarvis embedding model verified and ready.", flush=True)


def main() -> int:
    try:
        base_url = _base_url()
        ready_timeout = _timeout_setting("JARVIS_OLLAMA_BOOTSTRAP_READY_TIMEOUT_SECONDS", 120)
        pull_timeout = _timeout_setting("JARVIS_OLLAMA_BOOTSTRAP_PULL_TIMEOUT_SECONDS", 900)
        embed_timeout = _timeout_setting("JARVIS_OLLAMA_BOOTSTRAP_EMBED_TIMEOUT_SECONDS", 180)
        bootstrap(base_url, ready_timeout=ready_timeout, pull_timeout=pull_timeout,
                  embed_timeout=embed_timeout)
    except BootstrapError as exc:
        print(f"Ollama bootstrap failed: {exc}", file=sys.stderr)
        return 1
    except requests.RequestException:
        print("Ollama bootstrap failed: daemon request failed or timed out; Jarvis was not started.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
