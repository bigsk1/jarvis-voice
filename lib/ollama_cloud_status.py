"""Read-only, sanitized Ollama account status for the Web settings card.

Account probes deliberately avoid model routing/failover: a daemon's account is
its own, and a cloud bearer must only reach the official cloud origin.
"""

import copy
import hashlib
import math
import threading
import time
from concurrent.futures import Future
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import requests

_CACHE: dict = {}
_LOCK = threading.Lock()
_INFLIGHT: dict[str, Future] = {}
_TTL = 60
_STATES = {401: "unauthorized", 403: "unauthorized", 404: "unsupported", 429: "rate_limited"}


def _number(value, *, integer=False, percent=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        if not math.isfinite(value) or value < 0 or (percent and value > 100):
            return None
    except OverflowError:
        return None
    if integer and (not isinstance(value, int) or value > 2**53 - 1):
        return None
    return value


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return None
        return stamp.astimezone(UTC).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError):
        return None


def _balance(data):
    if not isinstance(data, dict):
        return None
    result = {}
    included = data.get("included")
    if isinstance(included, dict):
        fields = {}
        for name in ("balance_usd", "allowance_usd"):
            value = _number(included.get(name))
            if value is not None:
                fields[name] = value
        period = included.get("period")
        if isinstance(period, dict):
            dates = {key: _timestamp(period.get(key)) for key in ("from", "until")}
            if all(dates.values()):
                fields["period"] = dates
        for name in ("session", "weekly"):
            window = included.get(name)
            if not isinstance(window, dict):
                continue
            remaining = _number(window.get("remaining_percent"), percent=True)
            if remaining is not None:
                fields[name] = {"remaining_percent": remaining}
                reset = _timestamp(window.get("resets_at"))
                if reset:
                    fields[name]["resets_at"] = reset
        if fields and any(key != "period" for key in fields):
            result["included"] = fields
    purchased = data.get("purchased")
    if isinstance(purchased, dict):
        value = _number(purchased.get("balance_usd"))
        if value is not None:
            result["purchased"] = {"balance_usd": value}
    return result or None


def _usage(data):
    if not isinstance(data, dict) or data.get("range") != "7d" or data.get("scope") != "self":
        return None
    totals = data.get("totals")
    if not isinstance(totals, dict):
        return None
    fields = {}
    for name in (
        "request_count",
        "usage_usd",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
    ):
        value = _number(totals.get(name), integer=name != "usage_usd")
        if value is not None:
            fields[name] = value
    if not fields:
        return None
    result = {"range": "7d", "scope": "self", "totals": fields}
    for key in ("from", "until"):
        stamp = _timestamp(data.get(key))
        if stamp:
            result[key] = stamp
    return result


def _retry_seconds(value):
    try:
        seconds = float(value)
    except (TypeError, ValueError, OverflowError):
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return _TTL
    return min(86400, max(_TTL, seconds)) if math.isfinite(seconds) else _TTL


def _probe(method, url, headers):
    """No redirects or retries: do not forward credentials or multiply polls."""
    try:
        response = getattr(requests, method)(
            url,
            headers=headers,
            timeout=(2, 4),
            allow_redirects=False,
        )
    except requests.RequestException:
        return "unavailable", None, False, _TTL
    status = _STATES.get(response.status_code, "unavailable")
    delay = _TTL
    if response.status_code == 429:
        delay = _retry_seconds(response.headers.get("Retry-After"))
    if response.status_code in (200, 401, 403):
        try:
            data = response.json()
        except (ValueError, requests.RequestException):
            return "invalid" if response.status_code == 200 else status, None, True, delay
        return "available" if response.status_code == 200 else status, data, True, delay
    return status, None, True, delay


def _collect(base_url, api_key):
    payload = {
        "provider": "ollama",
        "connection_mode": "api_key" if api_key else "signed_in_host",
        "reachable": False,
        "signed_in": "unknown",
        "plan": None,
        # Included allowance alone does not establish overall model availability.
        "quota_available": None,
        "dashboard_url": "https://ollama.com/settings",
        "signin_url": None,
    }
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    delay = _TTL
    throttled = False
    if not api_key:
        state, data, reached, delay = _probe("post", f"{base_url}/api/me", headers)
        payload["reachable"] = reached
        throttled = state == "rate_limited"
        if (
            state == "available"
            and isinstance(data, dict)
            and any(
                isinstance(data.get(key), str) and data[key]
                for key in ("plan", "id", "email", "name", "username")
            )
        ):
            payload["signed_in"] = True
            plan = data.get("plan")
            if isinstance(plan, str) and len(plan) <= 64:
                payload["plan"] = plan
        elif state == "unauthorized":
            payload["signed_in"] = False
            signin = data.get("signin_url") if isinstance(data, dict) else None
            if isinstance(signin, str) and len(signin) <= 2048:
                try:
                    parsed_signin = urlsplit(signin)
                    if parsed_signin.scheme == "https" and parsed_signin.netloc == "ollama.com":
                        payload["signin_url"] = signin
                except ValueError:
                    pass
    for name, normalize in (("balance", _balance), ("usage", _usage)):
        if throttled:
            payload[name] = {"status": "rate_limited", "data": None}
            continue
        suffix = "?range=7d&scope=self" if name == "usage" else ""
        state, raw, reached, retry = _probe("get", f"{base_url}/api/{name}{suffix}", headers)
        payload["reachable"] = payload["reachable"] or reached
        delay = max(delay, retry)
        throttled = state == "rate_limited"
        data = normalize(raw) if state == "available" else None
        if state == "available":
            if data is None:
                state = "invalid"
            else:
                payload["signed_in"] = True
        elif state == "unauthorized" and payload["signed_in"] is not True:
            payload["signed_in"] = False
        payload[name] = {"status": state, "data": data}
    payload["checked_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return payload, delay


def get_cloud_status(*, mode: str, base_url: str, api_key: str, effective_provider: str) -> dict:
    """Return bounded account status, cached for a minute per transport/account.

    Only cloud mode can use the key. Requests for one daemon never fail over to
    another account. The lock coalesces concurrent settings loads in this process.
    No credentials, account identities, or raw upstream errors reach the result.
    """
    key = api_key if mode == "cloud" else ""
    base = "https://ollama.com" if key else base_url.rstrip("/")
    try:
        parsed = urlsplit(base)
    except ValueError:
        return {"ok": False, "error": "Invalid Ollama host configuration"}
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return {"ok": False, "error": "Invalid Ollama host configuration"}
    fingerprint = hashlib.sha256(f"{mode}\0{base}\0{key}".encode()).hexdigest()
    with _LOCK:
        cached = _CACHE.get(fingerprint)
        if cached and time.monotonic() < cached["expires"]:
            payload = copy.deepcopy(cached["payload"])
            payload["effective_provider"] = effective_provider
            return payload
        future = _INFLIGHT.get(fingerprint)
        owns_probe = future is None
        if future is None:
            future = Future()
            _INFLIGHT[fingerprint] = future
    if owns_probe:
        try:
            payload, delay = _collect(base, key)
        except BaseException as exc:
            # Wake every waiter even if the probing request is interrupted.
            with _LOCK:
                _INFLIGHT.pop(fingerprint, None)
            future.set_exception(exc)
            raise
        with _LOCK:
            if len(_CACHE) >= 32:
                _CACHE.pop(next(iter(_CACHE)))
            _CACHE[fingerprint] = {"expires": time.monotonic() + delay, "payload": payload}
            _INFLIGHT.pop(fingerprint, None)
        future.set_result(payload)
    else:
        payload = future.result()
    result = copy.deepcopy(payload)
    result["effective_provider"] = effective_provider
    return result
