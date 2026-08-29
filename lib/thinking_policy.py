#!/usr/bin/env python3
"""Model-aware thinking request resolution independent of trace visibility."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from model_prompt_overrides import ModelThinkingOverride

logger = logging.getLogger(__name__)

_DISABLED_ALIASES = {"off", "false", "disabled", "none"}
_EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "max", "xhigh")


@dataclass(frozen=True)
class ThinkingRequest:
    """Resolved provider request value plus the separate trace-display policy."""

    value: bool | str | None
    show_trace: bool
    source: str
    profile_used: bool
    configured_level: str | None = None


def get_catalog_thinking_profile(
    provider: str,
    model: str,
) -> ModelThinkingOverride | None:
    """Translate audited catalog capabilities into the shared profile shape."""
    provider = (provider or "").strip().lower()
    if provider == "openai":
        from model_catalog import get_model_metadata

        metadata = get_model_metadata("openai", model) or {}
        if not metadata.get("reasoning_effort"):
            return None
        raw_levels = metadata.get("reasoning_effort_values")
        if not isinstance(raw_levels, list):
            return None
        levels = tuple(
            str(level).strip().lower()
            for level in raw_levels
            if str(level).strip()
        )
        if not levels:
            return None
        configured_default = str(
            metadata.get("reasoning_effort_default") or ""
        ).strip().lower()
        if configured_default not in levels:
            return None
        disable_supported = "none" in levels
        return ModelThinkingOverride(
            supported=True,
            disable_supported=disable_supported,
            levels=levels,
            default_level=configured_default,
            disabled_fallback_level=(None if disable_supported else levels[0]),
        )

    if provider == "xai":
        from model_catalog import (
            get_model_metadata,
            get_model_supports_xai_reasoning_effort,
            get_model_xai_reasoning_effort_values,
        )

        supports_effort = get_model_supports_xai_reasoning_effort("xai", model)
        if not supports_effort:
            return None
        levels = tuple(get_model_xai_reasoning_effort_values("xai", model))
        if not levels:
            return None
        metadata = get_model_metadata("xai", model) or {}
        configured_default = str(metadata.get("reasoning_effort_default") or "").strip().lower()
        default_level = configured_default if configured_default in levels else levels[-1]
        disable_supported = "none" in levels
        return ModelThinkingOverride(
            supported=True,
            # Omitting reasoning_effort selects the provider default; it does
            # not disable reasoning. Only models with an explicit ``none``
            # value can truthfully expose a disabled state.
            disable_supported=disable_supported,
            levels=levels,
            default_level=default_level,
            disabled_fallback_level=(None if disable_supported else levels[0]),
        )

    if provider == "anthropic":
        from model_catalog import get_model_metadata

        metadata = get_model_metadata("anthropic", model) or {}
        capabilities = metadata.get("capabilities", {})
        thinking = capabilities.get("thinking", {})
        if not isinstance(thinking, dict) or not thinking.get("supported"):
            return None
        effort = capabilities.get("effort", {})
        levels = tuple(
            level
            for level in _EFFORT_ORDER
            if isinstance(effort, dict)
            and effort.get(level, {}).get("supported")
        )
        return ModelThinkingOverride(
            supported=True,
            disable_supported=True,
            levels=levels,
            default_level=(levels[-1] if levels else None),
        )

    return None


def configured_thinking_effort() -> str | None:
    """Return the request-scoped generic effort override, if one was set."""
    from config_loader import get_config_value

    raw = str(get_config_value("JARVIS_THINKING_EFFORT", "") or "").strip().lower()
    return None if raw in {"", "auto"} else raw


def resolve_thinking_request(
    *,
    provider: str,
    model: str,
    profile: ModelThinkingOverride | None,
    show_trace: bool,
    force_disabled: bool = False,
    unprofiled_value: bool | str | None = None,
    legacy_level: str | None = None,
) -> ThinkingRequest:
    """Resolve a semantic thinking request without exposing hidden traces.

    ``JARVIS_THINKING_EFFORT`` has precedence over a provider's legacy effort
    setting. Generic effort values are only sent when the selected model has a
    validated profile declaring that value. Unknown models therefore retain
    their existing provider behavior.
    """
    trace_visible = bool(show_trace) and not force_disabled
    generic_level = configured_thinking_effort()
    requested_level = generic_level or (legacy_level or "").strip().lower() or None
    requested_source = "JARVIS_THINKING_EFFORT" if generic_level else "provider setting"

    if profile is None:
        if generic_level:
            logger.warning(
                "Ignoring JARVIS_THINKING_EFFORT=%r for unprofiled model %s/%s",
                generic_level,
                provider,
                model,
            )
        value = False if force_disabled else unprofiled_value
        return ThinkingRequest(
            value=value,
            show_trace=trace_visible,
            source="unprofiled",
            profile_used=False,
            configured_level=generic_level,
        )

    if not profile.supported:
        return ThinkingRequest(
            value=False,
            show_trace=False,
            source="profile_unsupported",
            profile_used=True,
            configured_level=requested_level,
        )

    def disabled_value(source: str) -> ThinkingRequest:
        value: bool | str = False
        if profile.disable_supported and "none" in profile.levels:
            # Some provider APIs use a first-class string rather than boolean
            # false to disable reasoning (currently xAI Grok 4.3).
            value = "none"
        elif not profile.disable_supported:
            value = profile.disabled_fallback_level or False
        return ThinkingRequest(
            value=value,
            show_trace=trace_visible,
            source=source,
            profile_used=True,
            configured_level=requested_level,
        )

    if force_disabled:
        return disabled_value("forced_disabled")

    if requested_level:
        if requested_level in profile.levels:
            return ThinkingRequest(
                value=requested_level,
                show_trace=trace_visible,
                source="configured_level",
                profile_used=True,
                configured_level=requested_level,
            )
        if requested_level in _DISABLED_ALIASES:
            return disabled_value("configured_disabled")
        logger.warning(
            "Ignoring unsupported %s=%r for %s/%s; supported values: %s",
            requested_source,
            requested_level,
            provider,
            model,
            ", ".join(profile.levels) or "boolean only",
        )

    if trace_visible:
        return ThinkingRequest(
            value=profile.default_level or True,
            show_trace=True,
            source="profile_default",
            profile_used=True,
            configured_level=requested_level,
        )

    return disabled_value("profile_hidden")
