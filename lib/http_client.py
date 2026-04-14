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

import sys
import os
import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Add lib to path for config_loader
sys.path.insert(0, os.path.dirname(__file__))
from config_loader import get_config_value

# Configure logging
logger = logging.getLogger(__name__)

# HTTP statuses that usually mean the proxy CONNECT/tunnel failed (not the origin API).
# Without this, requests returns a Response and fallback-to-next-proxy never runs.
_PROXY_TUNNEL_RETRY_STATUSES = frozenset({407, 502, 503, 504})


def _proxy_dict(proxy_url: str) -> dict[str, str]:
    """Build requests proxies dict from a URL string."""
    return {'http': proxy_url, 'https': proxy_url}


def get_proxy_chain() -> list[dict[str, str]]:
    """
    Ordered list of proxy configs: LOCAL_PROXY, then LOCAL_PROXY2 (if set).

    Skips empty entries so a single-proxy setup is unchanged.
    """
    chain: list[dict[str, str]] = []
    for key in ('LOCAL_PROXY', 'LOCAL_PROXY2'):
        url = (get_config_value(key, '') or '').strip()
        if url:
            # Support http(s):// and socks5:// (requests + PySocks)
            chain.append(_proxy_dict(url))
    return chain


def get_proxy_config() -> dict[str, str] | None:
    """
    Primary proxy for callers that need a single sticky proxy (e.g. Session).

    Returns the first configured entry in order LOCAL_PROXY, LOCAL_PROXY2.
    """
    chain = get_proxy_chain()
    return chain[0] if chain else None


def proxy_response_indicates_tunnel_failure(response: requests.Response) -> bool:
    """HTTP status from a proxy path that should trigger the next proxy or direct fallback."""
    return response.status_code in _PROXY_TUNNEL_RETRY_STATUSES


def get_proxy_url_chain() -> list[str]:
    """
    Ordered proxy URL strings for subprocess tools (yt-dlp, etc.).

    Same order as get_proxy_chain: LOCAL_PROXY, then LOCAL_PROXY2.
    """
    return [p["https"] for p in get_proxy_chain()]


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
    
    chain = get_proxy_chain() if use_proxy else []
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
            logger.warning(f"[PROXY] ❌ Proxy request failed: {e}")
            print(f"[PROXY] ❌ Proxy failed ({masked_proxy}): {type(e).__name__}", file=sys.stderr)

    kwargs.pop('proxies', None)

    if chain and last_error is not None:
        if not fallback_on_proxy_fail:
            raise last_error
        logger.info("[PROXY] 🔄 Falling back to direct connection...")
        print("[PROXY] 🔄 Falling back to direct connection...", file=sys.stderr)

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

