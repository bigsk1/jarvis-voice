"""Declarative environment policy for local tool subprocesses.

This narrows accidental environment inheritance. It is not a sandbox: a child
running as the Jarvis user can still read files accessible to that user.
"""

from __future__ import annotations

import re
from typing import Any


RESTRICTED_ENV_MARKER = "JARVIS_RESTRICTED_TOOL_ENV"

# Runtime plumbing is shared by every restricted tool. Tool manifests declare
# only the config names they need; they never repeat PATH or TLS settings.
RUNTIME_ENV_KEYS = frozenset({
    "PATH", "PYTHONPATH", "VIRTUAL_ENV", "LANG", "LC_ALL", "LC_CTYPE", "TZ",
    "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE", "JARVIS_MODE", "JARVIS_SESSION_ID",
    "JARVIS_WEB_CONVERSATION_ID", "JARVIS_BACKGROUND_DEADLINE",
    "JARVIS_BACKGROUND_MAX_INPUT_BYTES", "JARVIS_TOOL_PROXY_POLICY",
})
PROXY_ENV_KEYS = frozenset({
    "LOCAL_PROXY", "LOCAL_PROXY2", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy",
})
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def _env_names(values: Any, label: str) -> set[str]:
    if not isinstance(values, list):
        raise ValueError(f"{label} must be a list of environment variable names")
    names: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not _ENV_NAME.fullmatch(value):
            raise ValueError(f"{label} contains an invalid environment variable name")
        if value.startswith("JARVIS_OVERRIDE_") or value == RESTRICTED_ENV_MARKER:
            raise ValueError(f"{label} cannot include internal override names")
        names.add(value)
    return names


def parse_child_environment_policy(
    raw: Any,
    availability: dict[str, Any] | None = None,
) -> frozenset[str] | None:
    """Return selected config names, or None for legacy full-env inheritance.

    Required env declarations can be reused. Optional settings need explicit
    `allow` entries because availability only describes hard prerequisites.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict) or raw.get("mode") != "restricted":
        raise ValueError("child_environment.mode must be restricted")
    if set(raw) - {"mode", "from_availability", "allow"}:
        raise ValueError("Unknown child_environment field")
    if not isinstance(raw.get("from_availability", False), bool):
        raise ValueError("child_environment.from_availability must be boolean")

    names = _env_names(raw.get("allow", []), "child_environment.allow")
    if raw.get("from_availability"):
        requirements = availability or {}
        if requirements.get("provider_requirements"):
            raise ValueError("Provider-specific availability needs explicit child env names")
        declared = set()
        for field in ("all_of_env", "any_of_env"):
            if field in requirements:
                declared.update(_env_names(requirements[field], f"availability.{field}"))
        if not declared:
            raise ValueError("from_availability requires declared environment names")
        names.update(declared)
    return frozenset(names)


def restrict_child_environment(
    source: dict[str, str],
    names: frozenset[str],
    *,
    home: str,
    proxy_policy: str = "inherit",
) -> dict[str, str]:
    """Build a small child env with effective selected-mode config values."""
    restricted = {key: value for key, value in source.items() if key in RUNTIME_ENV_KEYS}
    allowed = names | {"JARVIS_TOOL_PROXY_POLICY"}
    if proxy_policy != "off":
        allowed |= PROXY_ENV_KEYS
    for name in allowed:
        override = f"JARVIS_OVERRIDE_{name}"
        if override in source:
            restricted[name] = source[override]
        elif name in source:
            restricted[name] = source[name]
    # A private scratch HOME avoids implicit ~/.netrc and user cache reads.
    restricted["HOME"] = home
    restricted[RESTRICTED_ENV_MARKER] = "1"
    return restricted
