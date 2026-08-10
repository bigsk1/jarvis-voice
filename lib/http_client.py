#!/usr/bin/env python3
"""
HTTP Client with Optional Proxy Support

Provides a consistent way to make HTTP requests across Jarvis tools
with optional proxy support and automatic fallback.

Usage:
    from http_client import http_request, get_session
    
    # Simple request (uses proxy if configured)
    response = http_request('GET', url, params=params, headers=headers)
    
    # Get a session for multiple requests
    session = get_session()
    response = session.get(url, params=params)

Config:
    LOCAL_PROXY=http://user:pass@host:port   # Primary proxy (cloud.env or local.env)
    LOCAL_PROXY2=http://user:pass@host:port # Optional second proxy; used if LOCAL_PROXY fails
    # http_request tries LOCAL_PROXY → LOCAL_PROXY2 → direct connection (if fallback enabled).
    JARVIS_HTTP_LOG_DIRECT=true  # Optional: log proxy_used=false when no proxy (default DEBUG only)
"""

import logging
import os
import socket
import sys
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Add lib to path for config_loader
sys.path.insert(0, os.path.dirname(__file__))
from config_loader import get_config_value
from security_utils import redact_sensitive_text

# Configure logging
logger = logging.getLogger(__name__)

# HTTP statuses that usually mean the proxy CONNECT/tunnel failed (not the origin API).
# Without this, requests returns a Response and fallback-to-next-proxy never runs.
_PROXY_TUNNEL_RETRY_STATUSES = frozenset({407, 502, 503, 504})
PROXY_POLICY_ENV = "JARVIS_TOOL_PROXY_POLICY"
VALID_PROXY_POLICIES = frozenset({"inherit", "off", "prefer", "require"})
STANDARD_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def _proxy_dict(proxy_url: str) -> dict[str, str]:
    """Build requests proxies dict from a URL string."""
    return {'http': proxy_url, 'https': proxy_url}


def normalize_proxy_policy(value: str | None, *, default: str = "inherit") -> str:
    """Normalize and validate a tool/server proxy policy."""
    policy = str(value or default).strip().lower()
    if policy not in VALID_PROXY_POLICIES:
        allowed = ", ".join(sorted(VALID_PROXY_POLICIES))
        raise ValueError(f"Invalid proxy_policy '{value}'. Expected one of: {allowed}")
    return policy


def get_proxy_policy() -> str:
    """Return the active tool subprocess proxy policy."""
    raw = get_config_value(PROXY_POLICY_ENV, "inherit")
    try:
        return normalize_proxy_policy(raw)
    except ValueError as exc:
        logger.warning("%s; preserving inherited proxy behavior", exc)
        return "inherit"


def resolve_proxy_behavior(
    *,
    use_proxy: bool = True,
    fallback_on_proxy_fail: bool = True,
) -> tuple[bool, bool]:
    """Apply the active proxy policy to one helper call's legacy options."""
    policy = get_proxy_policy()
    if policy == "off":
        return False, False
    if policy == "prefer":
        return True, True
    if policy == "require":
        return True, False
    return use_proxy, fallback_on_proxy_fail


def proxy_policy_allows_direct_fallback(*, default: bool) -> bool:
    """Whether a manual proxy-chain caller may attempt a direct connection."""
    policy = get_proxy_policy()
    if policy == "require":
        return False
    if policy in {"off", "prefer"}:
        return True
    return default


def get_proxy_chain(*, respect_policy: bool = True) -> list[dict[str, str]]:
    """
    Ordered list of proxy configs: LOCAL_PROXY, then LOCAL_PROXY2 (if set).

    Skips empty entries so a single-proxy setup is unchanged.
    """
    if respect_policy and get_proxy_policy() == "off":
        return []

    chain: list[dict[str, str]] = []
    for key in ('LOCAL_PROXY', 'LOCAL_PROXY2'):
        url = (get_config_value(key, '') or '').strip()
        if url:
            # Support http(s):// and socks5:// (requests + PySocks)
            chain.append(_proxy_dict(url))
    return chain


def get_proxy_config(*, respect_policy: bool = True) -> dict[str, str] | None:
    """
    Primary proxy for callers that need a single sticky proxy (e.g. Session).

    Returns the first configured entry in order LOCAL_PROXY, LOCAL_PROXY2.
    """
    chain = get_proxy_chain(respect_policy=respect_policy)
    return chain[0] if chain else None


def proxy_response_indicates_tunnel_failure(response: requests.Response) -> bool:
    """HTTP status from a proxy path that should trigger the next proxy or direct fallback."""
    return response.status_code in _PROXY_TUNNEL_RETRY_STATUSES


def get_proxy_url_chain(*, respect_policy: bool = True) -> list[str]:
    """
    Ordered proxy URL strings for subprocess tools (yt-dlp, etc.).

    Same order as get_proxy_chain: LOCAL_PROXY, then LOCAL_PROXY2.
    """
    return [p["https"] for p in get_proxy_chain(respect_policy=respect_policy)]


def build_proxy_url_attempts(*, direct_fallback_default: bool) -> list[str | None]:
    """Build proxy/direct attempts for subprocess clients such as yt-dlp."""
    policy = get_proxy_policy()
    urls = get_proxy_url_chain()
    if policy == "require":
        if not urls:
            raise requests.exceptions.ProxyError(
                "proxy_policy=require but LOCAL_PROXY and LOCAL_PROXY2 are not configured"
            )
        return list(urls)
    if policy == "off":
        return [None]

    attempts: list[str | None] = list(urls)
    if not attempts or proxy_policy_allows_direct_fallback(default=direct_fallback_default):
        attempts.append(None)
    return attempts


def select_reachable_proxy_url(
    proxy_urls: list[str] | None = None,
    *,
    timeout: float = 0.75,
) -> tuple[str, str] | None:
    """Return the first proxy whose TCP listener is reachable.

    This is intended for clients that accept only one conventional proxy URL,
    such as an MCP container using ``HTTP_PROXY``/``HTTPS_PROXY``. Jarvis's
    normal request helper still performs full request-level chain fallback.
    """
    urls = proxy_urls if proxy_urls is not None else get_proxy_url_chain(respect_policy=False)
    for index, proxy_url in enumerate(urls):
        slot = _PROXY_SLOT_KEYS[index] if index < len(_PROXY_SLOT_KEYS) else f"proxy_{index}"
        parsed = urlsplit(proxy_url)
        host = parsed.hostname
        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme == "https" else 1080 if parsed.scheme.startswith("socks") else 80
        if not host:
            logger.warning("[PROXY] Skipping invalid %s URL", slot)
            continue
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return proxy_url, slot
        except OSError as exc:
            logger.warning(
                "[PROXY] %s listener unavailable (%s): %s",
                slot,
                _mask_proxy_url(proxy_url),
                type(exc).__name__,
            )
    return None


def standard_proxy_environment(proxy_url: str) -> dict[str, str]:
    """Build conventional proxy variables from one explicitly selected URL."""
    return {key: proxy_url for key in STANDARD_PROXY_ENV_KEYS}


_PROXY_SLOT_KEYS = ("LOCAL_PROXY", "LOCAL_PROXY2")


def _first_configured_proxy_slot() -> str | None:
    """Env key name for the primary proxy (first non-empty LOCAL_PROXY or LOCAL_PROXY2)."""
    for key in _PROXY_SLOT_KEYS:
        if (get_config_value(key, "") or "").strip():
            return key
    return None


def _emit_proxy_log_line(
    url: str,
    *,
    proxy_used: bool,
    proxy_slot: str | None = None,
    note: str | None = None,
) -> None:
    """
    Grep-friendly line for logs (stderr + logger) — e.g. proxy_used=true proxy_slot=LOCAL_PROXY.
    """
    parts = ["[HTTP]", f"proxy_used={'true' if proxy_used else 'false'}"]
    if proxy_slot:
        parts.append(f"proxy_slot={proxy_slot}")
    if note:
        parts.append(note)
    parts.append(f"url={_truncate_url(url, 120)}")
    line = " ".join(parts)
    logger.info(line)
    print(line, file=sys.stderr)


def get_session(
    use_proxy: bool = True,
    retries: int = 3,
    backoff_factor: float = 0.3,
    timeout: int = 15
) -> requests.Session:
    """
    Create a requests Session with optional proxy and retry support.
    
    Args:
        use_proxy: Whether to use proxy if configured (default: True)
        retries: Number of retries for failed requests (default: 3)
        backoff_factor: Backoff factor for retries (default: 0.3)
        timeout: Default timeout in seconds (default: 15)
    
    Returns:
        Configured requests.Session
    """
    session = requests.Session()
    policy = get_proxy_policy()
    use_proxy, _ = resolve_proxy_behavior(
        use_proxy=use_proxy,
        fallback_on_proxy_fail=False,
    )
    if policy == "off":
        session.trust_env = False
    
    # Configure retries
    retry_strategy = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # Configure proxy if enabled and available
    if use_proxy:
        proxies = get_proxy_config()
        if proxies:
            session.proxies = proxies
            masked = _mask_proxy_url(proxies.get('https', ''))
            slot = _first_configured_proxy_slot() or "LOCAL_PROXY"
            logger.info(f"[PROXY] Session configured with proxy: {masked}")
            print(
                f"[HTTP] proxy_used=true proxy_slot={slot} session=1 proxy={masked}",
                file=sys.stderr,
            )
        elif policy == "require":
            raise requests.exceptions.ProxyError(
                "proxy_policy=require but LOCAL_PROXY and LOCAL_PROXY2 are not configured"
            )
    
    # Set default headers
    session.headers.update({
        'User-Agent': 'Jarvis-Voice-Assistant/1.0'
    })
    
    return session


def http_request(
    method: str,
    url: str,
    use_proxy: bool = True,
    fallback_on_proxy_fail: bool = True,
    timeout: int = 15,
    **kwargs
) -> requests.Response:
    """
    Make an HTTP request with optional proxy support and fallback.
    
    Args:
        method: HTTP method (GET, POST, etc.)
        url: Request URL
        use_proxy: Whether to use proxy chain if configured (default: True)
        fallback_on_proxy_fail: After LOCAL_PROXY and LOCAL_PROXY2 both fail, retry without proxy (default: True)
        timeout: Request timeout in seconds (default: 15)
        **kwargs: Additional arguments passed to requests (params, headers, json, data, etc.)
    
    Returns:
        requests.Response object
    
    Raises:
        requests.RequestException: If request fails (after fallback if enabled)
    """
    kwargs.setdefault('timeout', timeout)
    
    # Add default user agent if not specified
    headers = kwargs.get('headers', {})
    if 'User-Agent' not in headers:
        headers['User-Agent'] = 'Jarvis-Voice-Assistant/1.0'
        kwargs['headers'] = headers
    
    policy = get_proxy_policy()
    use_proxy, fallback_on_proxy_fail = resolve_proxy_behavior(
        use_proxy=use_proxy,
        fallback_on_proxy_fail=fallback_on_proxy_fail,
    )
    chain = get_proxy_chain() if use_proxy else []
    if policy == "require" and not chain:
        raise requests.exceptions.ProxyError(
            "proxy_policy=require but LOCAL_PROXY and LOCAL_PROXY2 are not configured"
        )
    last_error: requests.RequestException | None = None
    log_direct = (get_config_value("JARVIS_HTTP_LOG_DIRECT", "") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )

    for i, proxies in enumerate(chain):
        slot = _PROXY_SLOT_KEYS[i] if i < len(_PROXY_SLOT_KEYS) else f"proxy_{i}"
        try:
            kwargs['proxies'] = proxies
            response = requests.request(method, url, **kwargs)

            # CONNECT failures often surface as 502/503/504 (or 407 auth) without raising.
            if response.status_code in _PROXY_TUNNEL_RETRY_STATUSES:
                err = requests.exceptions.HTTPError(
                    f"{response.status_code} {response.reason} (proxy/tunnel — trying next)"
                )
                err.response = response
                last_error = err
                masked_proxy = _mask_proxy_url(proxies.get('https', ''))
                logger.warning(
                    f"[PROXY] ❌ Proxy returned {response.status_code} "
                    f"(treat as failed): {masked_proxy}"
                )
                print(
                    f"[PROXY] ❌ Proxy HTTP {response.status_code} ({masked_proxy}) — trying next proxy or direct",
                    file=sys.stderr,
                )
                response.close()
                continue

            masked_proxy = _mask_proxy_url(proxies.get('https', ''))
            _emit_proxy_log_line(url, proxy_used=True, proxy_slot=slot, note=f"proxy={masked_proxy}")
            logger.info(f"[PROXY] ✅ Request successful via proxy: {masked_proxy}")
            print(f"[PROXY] ✅ Request to {_truncate_url(url)} via proxy succeeded", file=sys.stderr)
            return response
        except requests.RequestException as e:
            last_error = e
            masked_proxy = _mask_proxy_url(proxies.get('https', ''))
            logger.warning(
                "[PROXY] ❌ Proxy request failed: %s",
                redact_sensitive_text(str(e)),
            )
            print(f"[PROXY] ❌ Proxy failed ({masked_proxy}): {type(e).__name__}", file=sys.stderr)

    kwargs.pop('proxies', None)

    if chain and last_error is not None:
        if not fallback_on_proxy_fail:
            raise last_error
        logger.info("[PROXY] 🔄 Falling back to direct connection...")
        print("[PROXY] 🔄 Falling back to direct connection...", file=sys.stderr)

    if policy in {"off", "prefer"}:
        # "off" and the final leg of "prefer" mean genuinely direct, even if
        # the host process exports conventional proxy variables.
        kwargs["proxies"] = {"http": None, "https": None, "all": None}
        response = requests.request(method, url, **kwargs)
    else:
        response = requests.request(method, url, **kwargs)

    if not chain:
        if log_direct:
            _emit_proxy_log_line(
                url, proxy_used=False, note="direct=no_proxy_config",
            )
        else:
            logger.debug(
                "[HTTP] proxy_used=false direct=no_proxy_config url=%s",
                _truncate_url(url, 120),
            )
    else:
        _emit_proxy_log_line(
            url, proxy_used=False, note="direct=fallback_after_proxy_failed",
        )
        logger.info(f"[PROXY] ✅ Fallback direct request succeeded")
        print("[PROXY] ✅ Direct fallback succeeded", file=sys.stderr)

    return response


def _mask_proxy_url(url: str) -> str:
    """Mask password in proxy URL for logging."""
    if not url:
        return ""
    
    # Handle format: http://user:pass@host:port
    if '@' in url and ':' in url.split('@')[0]:
        # Split into scheme://user:pass and host:port
        scheme_auth, host = url.rsplit('@', 1)
        if ':' in scheme_auth:
            # Find the password portion
            parts = scheme_auth.split(':')
            if len(parts) >= 3:
                # scheme://user:pass -> scheme://user:****
                scheme = parts[0]
                user = parts[1].lstrip('/')
                return f"{scheme}://{user}:****@{host}"
    
    return url


def _truncate_url(url: str, max_len: int = 50) -> str:
    """Truncate URL for logging."""
    if len(url) <= max_len:
        return url
    return url[:max_len] + "..."


# Convenience functions for common HTTP methods
def get(url: str, **kwargs) -> requests.Response:
    """Make a GET request."""
    return http_request('GET', url, **kwargs)


def post(url: str, **kwargs) -> requests.Response:
    """Make a POST request."""
    return http_request('POST', url, **kwargs)


def put(url: str, **kwargs) -> requests.Response:
    """Make a PUT request."""
    return http_request('PUT', url, **kwargs)


def delete(url: str, **kwargs) -> requests.Response:
    """Make a DELETE request."""
    return http_request('DELETE', url, **kwargs)


# Test function
if __name__ == "__main__":
    
    # Load config
    from config_loader import load_config
    load_config()
    
    # Configure logging to see output
    logging.basicConfig(level=logging.INFO)
    
    print("Testing http_client with proxy support...")
    chain = get_proxy_chain()
    print(f"Proxy chain length: {len(chain)}")
    if get_proxy_config():
        print(f"Primary proxy (masked): {_mask_proxy_url(get_proxy_config()['https'])}")
    
    # Test with a simple API call
    print("\nTesting CoinGecko ping...")
    try:
        response = get("https://api.coingecko.com/api/v3/ping")
        response.raise_for_status()
        print(f"Response: {response.json()}")
        print("✅ Test passed!")
    except Exception as e:
        print(f"❌ Test failed: {e}")
