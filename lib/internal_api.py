"""Helpers for Jarvis services that call the internal FastAPI server."""
from __future__ import annotations

from config_loader import get_bool, get_config_value


DEFAULT_API_BASE_URL = "http://localhost:8880"


def get_internal_api_base_url(default: str = DEFAULT_API_BASE_URL) -> str:
    """Return the server-side URL for jarvis-api without a trailing slash."""
    value = get_config_value("JARVIS_API_INTERNAL_URL", default)
    return (value or default).strip().rstrip("/")


def get_internal_api_headers() -> dict[str, str]:
    """Return auth headers for internal jarvis-api calls when API auth is on."""
    if not get_bool("JARVIS_API_AUTH", False):
        return {}

    api_key = (get_config_value("JARVIS_API_KEY", "") or "").strip()
    if not api_key:
        return {}

    return {"Authorization": f"Bearer {api_key}"}
