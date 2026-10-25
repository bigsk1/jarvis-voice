"""Select a trusted webhook route before making a single POST attempt.

Webhook delivery must not use the general HTTP client's retry/failover loop:
an uncertain result can still mean the destination performed the action.
"""

from urllib.parse import urlsplit

import requests
from config_loader import get_config_value
from http_client import get_proxy_url_chain, select_reachable_proxy_url
from requests.adapters import HTTPAdapter

_POLICIES = ("off", "prefer", "require")


class WebhookProxyUnavailable(ValueError):
    """A required proxy route could not be selected before delivery."""


def policy_for_webhook(config: dict) -> str:
    """Only operator-managed registry entries can opt into proxy routing."""
    policy = config.get("proxy_policy", "off")
    if not isinstance(policy, str):
        raise ValueError("Invalid webhook proxy_policy; expected off, prefer, or require")
    policy = policy.strip().lower()
    if policy not in _POLICIES:
        raise ValueError("Invalid webhook proxy_policy; expected off, prefer, or require")
    return policy


def _select_webhook_proxy(chain: list[str]) -> tuple[str, str] | None:
    """A malformed primary must not hide a usable secondary before delivery."""
    for index, proxy_url in enumerate(chain):
        try:
            parsed = urlsplit(proxy_url)
            if (parsed.scheme not in {"http", "https", "socks4", "socks4a", "socks5", "socks5h"}
                    or not parsed.hostname):
                raise ValueError("Invalid proxy URL")
            # Accessing port also validates its numeric value and range.
            _ = parsed.port
            selected = select_reachable_proxy_url([proxy_url])
        except (ValueError, OSError):
            continue
        if selected:
            return selected[0], "LOCAL_PROXY2" if index == 1 else "LOCAL_PROXY"
    return None


def prepare_webhook_route(policy: str) -> tuple[dict[str, str], dict]:
    """Probe proxy listeners before delivery; never fail over after a POST."""
    policy = policy_for_webhook({"proxy_policy": policy})
    metadata = {"policy": policy, "used": False, "basis": "webhook_route"}
    if policy == "off":
        return {}, {**metadata, "direct_reason": "policy_off"}

    try:
        chain = get_proxy_url_chain(respect_policy=False)
        selected = _select_webhook_proxy(chain)
    except (ValueError, OSError) as from_error:
        # Proxy parser errors can include credentials; expose only a safe message.
        raise ValueError("Invalid webhook proxy configuration; no webhook was sent") from from_error
    if selected:
        proxy_url, slot = selected
        # The shared selector labels positions in a filtered chain; when only
        # LOCAL_PROXY2 is configured its first position still means secondary.
        primary = (get_config_value("LOCAL_PROXY", "") or "").strip()
        secondary = (get_config_value("LOCAL_PROXY2", "") or "").strip()
        if proxy_url == secondary and proxy_url != primary:
            slot = "LOCAL_PROXY2"
        return {"http": proxy_url, "https": proxy_url}, {**metadata, "used": True, "slot": slot}
    if policy == "require":
        raise WebhookProxyUnavailable("Webhook requires a reachable proxy; no webhook was sent")
    return {}, {**metadata, "direct_reason": "no_reachable_proxy"}


def webhook_response_receipt(status_code: int, proxy: dict) -> dict:
    """Describe HTTP evidence without assuming a proxy response reached origin."""
    proxied = bool(proxy.get("used"))
    receipt = {"status_code": status_code, "response_received": True, "proxy": dict(proxy)}
    if 200 <= status_code < 300:
        receipt.update(request_sent=True, delivery_status="accepted")
    elif 300 <= status_code < 400:
        receipt.update(request_sent=None if proxied else True, delivery_status="redirect_refused",
                       redirect_blocked=True, retry_safe=False)
    elif proxied and status_code == 407:
        receipt.update(request_sent=False, delivery_status="proxy_rejected", retry_safe=False)
    elif proxied:
        receipt.update(request_sent=None, delivery_status="unknown", retry_safe=False)
    else:
        receipt.update(request_sent=True, delivery_status="rejected", retry_safe=False)
    return receipt


def post_webhook(url: str, *, data: dict, headers: dict, proxies: dict, timeout: int = 15) -> requests.Response:
    """Send once through the selected route, ignoring ambient proxy settings."""
    ca_bundle = get_config_value("REQUESTS_CA_BUNDLE") or get_config_value("CURL_CA_BUNDLE")
    with requests.Session() as session:
        # Ignore HTTP(S)_PROXY, ALL_PROXY, NO_PROXY, and implicit .netrc auth.
        # Preserve explicit CA bundles because trust_env also disables that merge.
        session.trust_env = False
        session.mount("http://", HTTPAdapter(max_retries=0))
        session.mount("https://", HTTPAdapter(max_retries=0))
        return session.post(
            url, json=data, headers=headers, proxies=proxies, timeout=timeout,
            allow_redirects=False, verify=ca_bundle or True,
        )
