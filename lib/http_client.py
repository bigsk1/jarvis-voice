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
    LOCAL_PROXY=http://user:pass@host:port  # In cloud.env or local.env
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


def get_proxy_config() -> dict[str, str] | None:
    """
    Get proxy configuration from environment.
    
    Returns:
        Dict with 'http' and 'https' proxy URLs, or None if not configured.
    """
    proxy_url = get_config_value('LOCAL_PROXY', '')
    
    if not proxy_url:
        return None
    
    # Support both http:// and https:// proxy schemes
    # Also support socks5:// if user configures it (requests supports it with PySocks)
    return {
        'http': proxy_url,
        'https': proxy_url
    }


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
            logger.info(f"[PROXY] Session configured with proxy: {_mask_proxy_url(proxies.get('https', ''))}")
    
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
        use_proxy: Whether to use proxy if configured (default: True)
        fallback_on_proxy_fail: If proxy fails, retry without proxy (default: True)
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
    
    proxies = get_proxy_config() if use_proxy else None
    
    # Try with proxy first if configured
    if proxies:
        try:
            kwargs['proxies'] = proxies
            response = requests.request(method, url, **kwargs)
            
            # Log success
            masked_proxy = _mask_proxy_url(proxies.get('https', ''))
            logger.info(f"[PROXY] ✅ Request successful via proxy: {masked_proxy}")
            print(f"[PROXY] ✅ Request to {_truncate_url(url)} via proxy succeeded", file=sys.stderr)
            
            return response
            
        except requests.RequestException as e:
            masked_proxy = _mask_proxy_url(proxies.get('https', ''))
            logger.warning(f"[PROXY] ❌ Proxy request failed: {e}")
            print(f"[PROXY] ❌ Proxy failed ({masked_proxy}): {type(e).__name__}", file=sys.stderr)
            
            if not fallback_on_proxy_fail:
                raise
            
            # Remove proxy for fallback
            kwargs.pop('proxies', None)
            logger.info("[PROXY] 🔄 Falling back to direct connection...")
            print("[PROXY] 🔄 Falling back to direct connection...", file=sys.stderr)
    
    # Direct request (no proxy or fallback)
    response = requests.request(method, url, **kwargs)
    
    if not proxies:
        logger.debug(f"[HTTP] Direct request to {_truncate_url(url)}")
    else:
        logger.info(f"[PROXY] ✅ Fallback direct request succeeded")
        print(f"[PROXY] ✅ Direct fallback succeeded", file=sys.stderr)
    
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
    print(f"Proxy configured: {get_proxy_config() is not None}")
    
    if get_proxy_config():
        print(f"Proxy URL (masked): {_mask_proxy_url(get_proxy_config()['https'])}")
    
    # Test with a simple API call
    print("\nTesting CoinGecko ping...")
    try:
        response = get("https://api.coingecko.com/api/v3/ping")
        response.raise_for_status()
        print(f"Response: {response.json()}")
        print("✅ Test passed!")
    except Exception as e:
        print(f"❌ Test failed: {e}")

