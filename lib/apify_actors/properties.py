"""Scalar and URL validation shared by property display adapters."""

from __future__ import annotations

import math
from collections.abc import Mapping
from urllib.parse import urlsplit

_MAX_SAFE_INTEGER = (1 << 53) - 1


def _mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, dict):
        return {key: item for key, item in value.items() if isinstance(key, str)}
    return {}


def _text(value: object, limit: int = 160) -> str | None:
    if not isinstance(value, str):
        return None
    clean = " ".join("".join(char if ord(char) >= 32 else " " for char in value).split())
    if not clean:
        return None
    return clean if len(clean) <= limit else clean[:limit - 1] + "…"


def _number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if 0 <= value <= _MAX_SAFE_INTEGER and math.isfinite(value) else None


def _identifier(value: object) -> str | None:
    if isinstance(value, str) and len(value) <= 128:
        return _text(value, 128)
    if type(value) is int and 0 <= value < 10 ** 128:
        return str(value)
    return None


def _url(value: object, hosts: frozenset[str]) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 2048:
        return None
    if "\\" in value or any(char.isspace() or ord(char) < 32 for char in value):
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.hostname not in hosts
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443)):
            return None
    except ValueError:
        return None
    return value


def _address(street: object, city: object, state: object, postal: object) -> str | None:
    parts = [_text(street, 160), _text(city, 100)]
    region = " ".join(part for part in (_text(state, 64), _text(postal, 24)) if part)
    if region:
        parts.append(region)
    joined = ", ".join(part for part in parts if part)
    return joined or None


def _compact(row: dict[str, object]) -> dict[str, object]:
    # Explicitly retain these unknowns so missing evidence cannot look like zero
    # days, an active sale, or a numeric price to a later model/workflow step.
    required = {"price", "listing_status", "days_on_zillow"}
    return {key: value for key, value in row.items() if value is not None or key in required}
