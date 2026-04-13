#!/usr/bin/env python3
"""
Simple in-memory rate limiter for API endpoints.
Per-IP sliding window. No external dependencies.

- /api/query uses QUERY_RATE_LIMIT_PER_MINUTE (see also api/routes/query.py).
- Global middleware (APIRateLimitMiddleware) applies per-route buckets; see BUCKET_DEFAULTS.
"""
import os
import time
from collections import defaultdict
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class RateLimiter:
    """Per-IP rate limiter using sliding window."""

    def __init__(self, requests_per_minute: int = 30, window_seconds: int = 60):
        """
        Args:
            requests_per_minute: Max requests per window (0 = disabled)
            window_seconds: Sliding window size in seconds
        """
        self.limit = requests_per_minute
        self.window = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def is_allowed(self, client_ip: str) -> tuple[bool, int]:
        """
        Check if request is allowed. Call before processing.

        Returns:
            (allowed: bool, retry_after_seconds: int)
        """
        if self.limit <= 0:
            return True, 0

        now = time.time()
        cutoff = now - self.window

        with self._lock:
            timestamps = self._requests[client_ip]
            # Remove old entries
            timestamps[:] = [t for t in timestamps if t > cutoff]

            if len(timestamps) >= self.limit:
                retry_after = int(cutoff + self.window - now) + 1
                return False, max(0, retry_after)

            timestamps.append(now)
            return True, 0

    def cleanup_old_entries(self, max_age_seconds: int = 3600):
        """Remove stale IP entries to prevent memory growth."""
        if self.limit <= 0:
            return
        now = time.time()
        with self._lock:
            for ip in list(self._requests):
                timestamps = self._requests[ip]
                timestamps[:] = [t for t in timestamps if t > now - self.window]
                if not timestamps:
                    del self._requests[ip]


# --- Global API middleware: longest prefix wins --------------------------------

# Prefix match order: longest first (see _bucket_for_path).
_PREFIX_BUCKETS: list[tuple[str, str]] = [
    ("/api/generated-videos", "generated-videos"),
    ("/api/generated-images", "generated-images"),
    ("/api/scheduled-tasks", "scheduled-tasks"),
    ("/api/conversations", "conversations"),
    ("/api/intelligence", "intelligence"),
    ("/api/workflows", "workflows"),
    ("/api/reminders", "reminders"),
    ("/api/docs", "docs"),
    ("/api/query", "query"),
    ("/api/memory", "memory"),
    ("/api/intel", "intel"),
    ("/api/voice", "voice"),
    ("/api/alerts", "alerts"),
    ("/api/stash", "stash"),
    ("/api/canvas", "canvas"),
    ("/api/prices", "prices"),
    ("/api/config", "config"),
    ("/api/images", "images"),
]

# Default RPM per bucket when no API_RATE_LIMIT_<BUCKET>_PER_MINUTE override is set.
_BUCKET_DEFAULTS: dict[str, int] = {
    "docs": 3,
    "query": 30,
    "alerts": 60,
    "memory": 120,
    "intel": 60,
    "intelligence": 60,
    "conversations": 90,
    "voice": 60,
    "reminders": 90,
    "stash": 120,
    "canvas": 90,
    "prices": 60,
    "config": 120,
    "workflows": 60,
    "images": 30,
    "generated-images": 20,
    "generated-videos": 10,
    "scheduled-tasks": 60,
    "default": 120,
}

# Exact /api paths that skip rate limiting (probes, cheap docs helpers).
_EXCLUDED_EXACT_PATHS = frozenset(
    {
        "/api/health",
        "/api/status",
        "/api/docs/topics",
        "/api/docs/status",
    }
)

_EXCLUDED_PREFIXES = (
    "/docs",
)

# Same idea as APIAuthMiddleware: loopback is trusted (local scripts, n8n on host).
_TRUSTED_IPS = frozenset({"127.0.0.1", "::1", "localhost"})


def _api_rate_limit_enabled() -> bool:
    return os.environ.get("API_RATE_LIMIT_ENABLED", "true").lower() in ("1", "true", "yes")


def _rpm_for_bucket(bucket: str) -> int:
    """Resolve requests/minute for a bucket (0 = unlimited for that bucket)."""
    from lib.config_loader import get_int

    if bucket == "query":
        return get_int("QUERY_RATE_LIMIT_PER_MINUTE", _BUCKET_DEFAULTS["query"])
    if bucket == "docs":
        return get_int("DOCS_API_RATE_LIMIT_PER_MINUTE", _BUCKET_DEFAULTS["docs"])
    if bucket == "default":
        return get_int("API_RATE_LIMIT_DEFAULT_PER_MINUTE", _BUCKET_DEFAULTS["default"])

    env_key = f"API_RATE_LIMIT_{bucket.upper().replace('-', '_')}_PER_MINUTE"
    override = get_int(env_key, -1)
    if override >= 0:
        return override
    return _BUCKET_DEFAULTS.get(bucket, _BUCKET_DEFAULTS["default"])


def _bucket_for_path(path: str) -> str | None:
    """Return rate-limit bucket name, or None if this path is not limited."""
    if not path.startswith("/api"):
        return None
    for exact in _EXCLUDED_EXACT_PATHS:
        if path == exact:
            return None
    for prefix in _EXCLUDED_PREFIXES:
        if path.startswith(prefix):
            return None

    for prefix, bucket in _PREFIX_BUCKETS:
        if path == prefix or path.startswith(prefix + "/"):
            return bucket
    return "default"


_bucket_limiters: dict[str, RateLimiter] = {}


def _get_limiter_for_bucket(bucket: str) -> RateLimiter:
    if bucket not in _bucket_limiters:
        rpm = _rpm_for_bucket(bucket)
        _bucket_limiters[bucket] = RateLimiter(requests_per_minute=rpm, window_seconds=60)
    return _bucket_limiters[bucket]


def get_docs_search_rate_limit_per_minute() -> int:
    """RPM for /api/docs (semantic search); used by docs route status text."""
    return _rpm_for_bucket("docs")


class APIRateLimitMiddleware(BaseHTTPMiddleware):
    """
    Per-IP sliding window for /api/* by route bucket (separate limit per bucket).

    Skips health/status/metrics/docs UI, OPTIONS, and 127.0.0.1/::1/localhost.
    Disabled when API_RATE_LIMIT_ENABLED=false.
    """

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        if not _api_rate_limit_enabled():
            return await call_next(request)

        path = request.url.path
        bucket = _bucket_for_path(path)
        if bucket is None:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        if client_ip in _TRUSTED_IPS:
            return await call_next(request)
        limiter = _get_limiter_for_bucket(bucket)
        allowed, retry_after = limiter.is_allowed(client_ip)
        if not allowed:
            return JSONResponse(
                {
                    "error": "rate_limit_exceeded",
                    "detail": f"Too many requests for this API section. Try again in {retry_after} seconds.",
                    "bucket": bucket,
                },
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)


def get_query_rate_limiter() -> RateLimiter:
    """Same limiter as middleware uses for the query bucket (QUERY_RATE_LIMIT_PER_MINUTE)."""
    return _get_limiter_for_bucket("query")
