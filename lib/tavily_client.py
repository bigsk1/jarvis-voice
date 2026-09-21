"""Small, credential-safe Tavily API client for Jarvis tools."""

from __future__ import annotations

from typing import Any

import requests

from config_loader import get_config_value
from http_client import http_request

BASE_URL = "https://api.tavily.com"


class TavilyError(Exception):
    """A safe message suitable for a tool result; never contains a credential."""


def request_tavily(endpoint: str, body: dict[str, Any], *, timeout: int = 40) -> dict[str, Any]:
    if endpoint not in {"search", "extract"}:
        raise ValueError("Unsupported Tavily endpoint")
    api_key = str(get_config_value("TAVILY_API_KEY", "") or "").strip()
    if not api_key:
        raise TavilyError("TAVILY_API_KEY is not configured in the active mode.")

    try:
        response = http_request(
            "POST",
            f"{BASE_URL}/{endpoint}",
            use_proxy=False,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=body,
        )
    except requests.RequestException as exc:
        raise TavilyError(f"Tavily {endpoint} request failed ({type(exc).__name__}).") from exc

    if response.status_code != 200:
        status = response.status_code
        if status == 401:
            message = "Check TAVILY_API_KEY in the active mode."
        elif status == 429:
            message = "Rate limit reached; retry later."
        elif status in {432, 433}:
            message = "Account usage limit reached."
        else:
            message = "Check the request parameters or Tavily service status."
        raise TavilyError(f"Tavily {endpoint} returned HTTP {status}. {message}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise TavilyError(f"Tavily {endpoint} returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise TavilyError(f"Tavily {endpoint} returned an unexpected response.")
    return payload


def compact_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def tool_result(ok: bool, speech: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": ok, "speech": speech}
    if ok:
        result["data"] = data or {}
    else:
        result["error"] = speech
    return result
