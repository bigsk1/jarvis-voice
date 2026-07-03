#!/usr/bin/env python3
"""
Credential-aware tool availability evaluator.

Tools declare optional hard configuration requirements in their manifest
(skills/*.tool.json or skills/auto-tools/*.tool.json) under an "availability"
key. This module evaluates those requirements against the active config scope
(cloud.env / local.env via config_loader) WITHOUT ever reading or exposing
secret values — only presence/non-blankness is checked, and results contain
requirement names or safe config-file paths only.

Manifest schema (all keys optional; no "availability" block = always available):

  "availability": {
    "all_of_env": ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"],
    "any_of_env": ["BRAVE_API_KEY", "BRAVE_SEARCH_API_KEY"],
    "config_files": ["data/.spotify_cache"],
    "webhook_registry": ["send_email"],
    "provider_setting": "IMAGE_TOOL_PROVIDER",
    "provider_default": "gemini",
    "provider_requirements": {
      "gemini": {"all_of_env": ["GEMINI_API_KEY"]},
      "openai": {"all_of_env": ["OPENAI_API_KEY"]},
      "xai":    {"all_of_env": ["XAI_API_KEY"]}
    },
    "setup_hint": "Add the key to config/<mode>.env and re-run sync-tools."
  }

Semantics:
  - all_of_env: every named key must be present and non-blank
  - any_of_env: at least one named key must be present and non-blank
  - config_files: every project-relative (or absolute/~) path must be a
    non-empty regular file; contents are never read
  - webhook_registry: each named entry in config/webhook_registry.json must
    exist, not be explicitly disabled, and have a non-blank URL after ${ENV_VAR}
    substitution (values never logged)
  - provider_requirements: the tool is available when at least ONE provider's
    requirements are met. The result carries selected/configured provider
    detail so callers (e.g. media tool preflight) can produce clear errors
    without auto-switching providers.
  - Malformed availability blocks FAIL CLOSED for that tool only (status
    "unavailable" with a diagnostic marker) and never raise.

Evaluation must run inside the caller's config context (load_config(mode) or
config_scope(mode)) so cloud/local isolation follows get_config_value
precedence.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from config_loader import get_config_value, get_project_root

AvailabilityStatus = Literal["available", "unavailable", "unknown"]

# Diagnostic marker used in `missing` when the availability block itself is
# invalid. Angle brackets make it impossible to confuse with an env var name.
MALFORMED_MARKER = "<invalid availability metadata>"


@dataclass
class AvailabilityResult:
    status: AvailabilityStatus
    missing: list[str] = field(default_factory=list)  # requirement names only, never values
    setup_hint: str | None = None
    # Multi-provider detail (empty/None for single-requirement tools)
    selected_provider: str | None = None
    configured_providers: list[str] = field(default_factory=list)
    provider_availability: dict[str, bool] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.status == "available"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "missing": list(self.missing),
            "setup_hint": self.setup_hint,
            "selected_provider": self.selected_provider,
            "configured_providers": list(self.configured_providers),
            "provider_availability": dict(self.provider_availability),
        }


def is_env_configured(key: str) -> bool:
    """True when the config value for `key` is present and non-blank.

    Only presence is checked; the value itself is never returned or logged.
    Blank/missing detection only — no placeholder heuristics (first release
    decision: broad pattern rejection risks disabling valid keys).
    """
    value = get_config_value(key, "")
    if value is None:
        return False
    return str(value).strip() != ""


def _validate_env_names(names: Any) -> list[str] | None:
    """Return a clean list of env var names, or None if the shape is invalid."""
    if not isinstance(names, list) or not names:
        return None
    out: list[str] = []
    for name in names:
        if not isinstance(name, str) or not name.strip():
            return None
        out.append(name.strip())
    return out


def _validate_config_files(paths: Any) -> list[str] | None:
    """Return clean manifest paths, or None when the shape is invalid."""
    if not isinstance(paths, list) or not paths:
        return None
    out: list[str] = []
    for path in paths:
        if not isinstance(path, str) or not path.strip():
            return None
        out.append(path.strip())
    return out


def is_config_file_ready(path_value: str) -> bool:
    """Check file presence without opening or exposing its contents."""
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = get_project_root() / path
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _validate_webhook_registry(names: Any) -> list[str] | None:
    """Return clean webhook entry names, or None when the shape is invalid."""
    if not isinstance(names, list) or not names:
        return None
    out: list[str] = []
    for name in names:
        if not isinstance(name, str) or not name.strip():
            return None
        out.append(name.strip())
    return out


def _resolve_registry_url(raw: str) -> str:
    """Expand ${ENV_VAR} placeholders in a webhook URL (never logged).

    Matches send_webhook.substitute_env_vars: missing vars keep ${NAME} so
    partially-resolved URLs are treated as not configured.
    """
    if not raw:
        return ""

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        val = get_config_value(key, "")
        if val is None or str(val).strip() == "":
            val = os.environ.get(key, "")
        if val is None or str(val).strip() == "":
            return match.group(0)
        return str(val).strip()

    resolved = re.sub(r"\$\{([^}]+)\}", repl, str(raw)).strip()
    if not resolved or "${" in resolved:
        return ""
    return resolved


def _check_webhook_registry_entries(entry_names: list[str]) -> list[str]:
    """Return missing webhook requirement labels (no secret values)."""
    registry_rel = "config/webhook_registry.json"
    if not is_config_file_ready(registry_rel):
        return [f"file: {registry_rel}"]

    registry_path = get_project_root() / registry_rel
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return [f"file: {registry_rel} (invalid)"]

    webhooks = data.get("webhooks", {})
    if not isinstance(webhooks, dict):
        return ["webhook_registry: invalid webhooks section"]

    missing: list[str] = []
    for name in entry_names:
        entry = webhooks.get(name)
        if not isinstance(entry, dict):
            missing.append(f"webhook: {name}")
            continue
        if entry.get("enabled") is False:
            missing.append(f"webhook: {name} (disabled)")
            continue
        if not _resolve_registry_url(str(entry.get("url", "") or "")):
            missing.append(f"webhook: {name} (url not configured)")
    return missing


def _malformed(setup_hint: str | None = None) -> AvailabilityResult:
    return AvailabilityResult(
        status="unavailable",
        missing=[MALFORMED_MARKER],
        setup_hint=setup_hint,
    )


def check_availability_block(block: Any) -> AvailabilityResult:
    """Evaluate a single `availability` block against the active config scope."""
    if block is None:
        return AvailabilityResult(status="available")
    if not isinstance(block, dict):
        return _malformed()

    setup_hint = block.get("setup_hint")
    if setup_hint is not None and not isinstance(setup_hint, str):
        setup_hint = None

    known_keys = {
        "all_of_env", "any_of_env", "config_files", "webhook_registry",
        "provider_setting", "provider_default", "provider_requirements",
        "setup_hint",
    }
    requirement_keys = {
        "all_of_env", "any_of_env", "config_files", "webhook_registry",
        "provider_requirements",
    }
    present = set(block.keys())
    if not (present & requirement_keys):
        # setup_hint-only or unknown-only blocks: nothing enforceable.
        # Unknown keys alone are treated as malformed (fail closed) so typos
        # like "allof_env" don't silently make a tool unconditionally available.
        if present - known_keys:
            return _malformed(setup_hint)
        return AvailabilityResult(status="available", setup_hint=setup_hint)

    missing: list[str] = []

    all_of = block.get("all_of_env")
    if all_of is not None:
        names = _validate_env_names(all_of)
        if names is None:
            return _malformed(setup_hint)
        missing.extend(name for name in names if not is_env_configured(name))

    any_of = block.get("any_of_env")
    if any_of is not None:
        names = _validate_env_names(any_of)
        if names is None:
            return _malformed(setup_hint)
        if not any(is_env_configured(name) for name in names):
            missing.append(f"any of: {', '.join(names)}")

    config_files = block.get("config_files")
    if config_files is not None:
        paths = _validate_config_files(config_files)
        if paths is None:
            return _malformed(setup_hint)
        missing.extend(
            f"file: {path}" for path in paths if not is_config_file_ready(path)
        )

    webhook_registry = block.get("webhook_registry")
    if webhook_registry is not None:
        names = _validate_webhook_registry(webhook_registry)
        if names is None:
            return _malformed(setup_hint)
        missing.extend(_check_webhook_registry_entries(names))

    result = AvailabilityResult(
        status="available",
        missing=missing,
        setup_hint=setup_hint,
    )

    provider_reqs = block.get("provider_requirements")
    if provider_reqs is not None:
        if not isinstance(provider_reqs, dict) or not provider_reqs:
            return _malformed(setup_hint)

        provider_ok: dict[str, bool] = {}
        for provider, reqs in provider_reqs.items():
            if not isinstance(provider, str) or not isinstance(reqs, dict):
                return _malformed(setup_hint)
            names = _validate_env_names(reqs.get("all_of_env"))
            if names is None:
                return _malformed(setup_hint)
            provider_ok[provider] = all(is_env_configured(name) for name in names)

        configured = sorted(p for p, ok in provider_ok.items() if ok)
        result.provider_availability = provider_ok
        result.configured_providers = configured

        provider_setting = block.get("provider_setting")
        if provider_setting is not None and isinstance(provider_setting, str):
            provider_default = block.get("provider_default")
            selected = get_config_value(
                provider_setting,
                provider_default if isinstance(provider_default, str) else None,
            )
            if selected:
                result.selected_provider = str(selected).strip().lower()

        if not configured:
            missing.append(
                "any provider of: " + ", ".join(sorted(provider_reqs.keys()))
            )

    if missing:
        result.status = "unavailable"
    return result


def check_tool_availability(manifest: dict[str, Any]) -> AvailabilityResult:
    """Evaluate a tool manifest's availability block. Never raises."""
    try:
        return check_availability_block(manifest.get("availability"))
    except Exception:
        # Fail closed for this tool only; never crash registry construction.
        return _malformed()


# Shared provider -> required env keys map for the media generation tools.
# Mirrors the provider_requirements blocks in generate_image/generate_video
# manifests; used for runtime preflight of the *selected* provider.
MEDIA_PROVIDER_ENV_KEYS: dict[str, list[str]] = {
    "gemini": ["GEMINI_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
    "xai": ["XAI_API_KEY"],
}


def media_provider_preflight(
    selected_provider: str,
    provider_env_keys: dict[str, list[str]] | None = None,
) -> str | None:
    """Check the selected media provider's credentials before any API call.

    Returns None when the provider is configured. Otherwise returns a clear,
    secret-free error message naming the missing key(s) and listing configured
    alternative providers. Never switches providers automatically — cost,
    policy, and output behavior differ per provider.
    """
    keys_map = provider_env_keys or MEDIA_PROVIDER_ENV_KEYS
    selected = (selected_provider or "").strip().lower()
    required = keys_map.get(selected)
    if required is None:
        # Unknown provider names are handled by the tool's own dispatch.
        return None
    missing = [key for key in required if not is_env_configured(key)]
    if not missing:
        return None
    configured = sorted(
        p for p, keys in keys_map.items()
        if p != selected and all(is_env_configured(k) for k in keys)
    )
    msg = (
        f"Provider '{selected}' is not configured "
        f"(missing: {', '.join(missing)})."
    )
    if configured:
        msg += (
            f" Configured alternatives: {', '.join(configured)}. "
            f"Pass provider explicitly or change the provider setting — "
            f"Jarvis will not switch providers automatically."
        )
    else:
        msg += " No alternative providers are configured either."
    return msg


def describe_missing(result: AvailabilityResult) -> str:
    """Safe one-line diagnostic (requirement names only, never values)."""
    parts = "; ".join(result.missing) if result.missing else "requirements not met"
    if result.setup_hint:
        return f"missing: {parts} — {result.setup_hint}"
    return f"missing: {parts}"
