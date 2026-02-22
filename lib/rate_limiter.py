#!/usr/bin/env python3
"""
Simple in-memory rate limiter for API endpoints.
Per-IP sliding window. No external dependencies.
"""
import time
from collections import defaultdict
from threading import Lock


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
        cutoff = now - max_age_seconds
        with self._lock:
            for ip in list(self._requests):
                timestamps = self._requests[ip]
                timestamps[:] = [t for t in timestamps if t > now - self.window]
                if not timestamps:
                    del self._requests[ip]


# Global instance for /api/query - configured from env at first use
_query_limiter: RateLimiter | None = None


def get_query_rate_limiter() -> RateLimiter:
    """Get or create the query rate limiter (reads config on first call)."""
    global _query_limiter
    if _query_limiter is None:
        from lib.config_loader import get_int
        limit = get_int('QUERY_RATE_LIMIT_PER_MINUTE', 30)
        _query_limiter = RateLimiter(requests_per_minute=limit, window_seconds=60)
    return _query_limiter
