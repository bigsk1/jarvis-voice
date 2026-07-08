"""Allowlisted router system-prompt versions."""

from __future__ import annotations

import hashlib

from router_prompt_catalog import (
    DEFAULT_ROUTER_PROMPT_VERSION,
    available_router_prompt_versions,
    normalize_router_prompt_version,
)

from .v1 import (
    BASE_SYSTEM_PROMPT as V1_SYSTEM_PROMPT,
    BASE_SYSTEM_PROMPT_SHA256 as V1_SYSTEM_PROMPT_SHA256,
)
from .v2 import (
    BASE_SYSTEM_PROMPT as V2_SYSTEM_PROMPT,
    BASE_SYSTEM_PROMPT_SHA256 as V2_SYSTEM_PROMPT_SHA256,
)


_ROUTER_PROMPTS = {
    "v1": (V1_SYSTEM_PROMPT, V1_SYSTEM_PROMPT_SHA256),
    "v2": (V2_SYSTEM_PROMPT, V2_SYSTEM_PROMPT_SHA256),
}

if tuple(_ROUTER_PROMPTS) != available_router_prompt_versions():
    raise RuntimeError("Router prompt catalog and implementations are out of sync")


def _validate_router_prompt(version: str, prompt: str, expected_sha256: str) -> None:
    actual_sha256 = hashlib.sha256(prompt.encode()).hexdigest()
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f"Router prompt {version} failed integrity validation: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )


def _validate_router_prompts(prompts: dict[str, tuple[str, str]]) -> None:
    """Validate every supplied prompt (used by tests and maintenance tools)."""
    for version, (prompt, expected_sha256) in prompts.items():
        _validate_router_prompt(version, prompt, expected_sha256)


# v1 is the recovery baseline, so its integrity is always required. Experimental
# versions are checked only when selected; a stale unused v7 must not break v1.
_validate_router_prompt("v1", V1_SYSTEM_PROMPT, V1_SYSTEM_PROMPT_SHA256)


def get_router_system_prompt(version: str | None) -> tuple[str, str]:
    """Resolve one allowlisted prompt version and return ``(version, text)``."""
    normalized = normalize_router_prompt_version(version)
    prompt_record = _ROUTER_PROMPTS.get(normalized)
    if prompt_record is None:
        choices = ", ".join(available_router_prompt_versions())
        raise ValueError(
            f"Unsupported JARVIS_ROUTER_PROMPT_VERSION '{normalized}'. "
            f"Available versions: {choices}"
        )
    _validate_router_prompt(normalized, *prompt_record)
    return normalized, prompt_record[0]
