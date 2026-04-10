#!/usr/bin/env python3
"""
Model-specific prompt overrides.

Loads small YAML prompt overlays for exact or normalized provider/model pairs.
The goal is to patch stable model quirks without changing the global prompts.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - dependency is normally available
    yaml = None

logger = logging.getLogger(__name__)

SUPPORTED_SECTIONS = {
    "routing_prepend",
    "routing_append",
    "qa_prepend",
    "qa_append",
    "tool_calling_prepend",
    "completion_guard_eval_prepend",
}

_KNOWN_RUNTIME_SUFFIXES = {"latest", "cloud"}


@dataclass(frozen=True)
class ModelPromptOverride:
    """Resolved override payload for a provider/model pair."""

    provider: str
    model: str
    mode: str
    matched_model: str = ""
    source_path: str = ""
    description: str = ""
    enabled: bool = False
    sections: dict[str, str] = field(default_factory=dict)

    def get(self, key: str) -> str:
        return self.sections.get(key, "")

    def has_any(self, *keys: str) -> bool:
        return any(self.sections.get(key) for key in keys)


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    ordered = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _strip_runtime_suffix(model_name: str) -> str:
    if ":" not in model_name:
        bare = re.sub(r"-(latest|cloud)$", "", model_name, flags=re.IGNORECASE)
        return bare or model_name
    base, suffix = model_name.rsplit(":", 1)
    if suffix.lower() in _KNOWN_RUNTIME_SUFFIXES and base:
        return base
    return model_name


def _strip_date_suffix(model_name: str) -> str:
    return re.sub(r"-\d{4}-\d{2}-\d{2}$", "", model_name)


def get_model_override_candidates(model_name: str) -> list[str]:
    """
    Return ordered candidate names for override lookup.

    Examples:
    - gpt-5.4-nano-2026-03-17 -> [exact, gpt-5.4-nano]
    - qwen3:latest -> [exact, qwen3]
    - kimi-k2.5-2026-03-17:cloud -> [exact, kimi-k2.5-2026-03-17, kimi-k2.5]
    """
    model_name = (model_name or "").strip()
    if not model_name:
        return []

    ordered = [model_name]
    worklist = [model_name]
    transforms = (_strip_runtime_suffix, _strip_date_suffix)

    while worklist:
        current = worklist.pop(0)
        for transform in transforms:
            candidate = transform(current)
            if candidate and candidate != current and candidate not in ordered:
                ordered.append(candidate)
                worklist.append(candidate)

    return _dedupe_preserve_order(ordered)


def _build_override_path(config_root: Path, provider: str, model_name: str) -> Path:
    return config_root / provider / model_name / "prompt_overrides.yaml"


def _coerce_section_text(payload: dict, section: str) -> str:
    value = payload.get(section)
    if value in (None, False):
        return ""
    if isinstance(value, str):
        return value.strip()
    logger.warning(
        "[MODEL_PROMPTS] Section %s must be a string; got %s",
        section,
        type(value).__name__,
    )
    return ""


def load_model_prompt_override(
    provider: str,
    model: str,
    mode: str,
    config_root: str | Path | None = None,
) -> ModelPromptOverride:
    """
    Load the most specific valid prompt override for the provider/model pair.

    Resolution order:
    1. exact model name
    2. normalized alias without :latest / :cloud
    3. normalized alias without dated suffix
    """
    provider = (provider or "").strip()
    model = (model or "").strip()
    mode = (mode or "").strip()
    root = Path(config_root) if config_root else Path(__file__).resolve().parent.parent / "config" / "models"

    empty = ModelPromptOverride(provider=provider, model=model, mode=mode)
    if not provider or not model:
        return empty
    if yaml is None:
        logger.warning("[MODEL_PROMPTS] PyYAML is unavailable; skipping prompt overrides")
        return empty

    for candidate in get_model_override_candidates(model):
        path = _build_override_path(root, provider, candidate)
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = yaml.safe_load(handle) or {}
        except yaml.YAMLError as exc:
            logger.warning("[MODEL_PROMPTS] Invalid YAML for %s/%s: %s", provider, candidate, exc)
            continue
        except OSError as exc:
            logger.warning("[MODEL_PROMPTS] Failed reading %s: %s", path, exc)
            continue

        if not isinstance(payload, dict):
            logger.warning("[MODEL_PROMPTS] Override file %s must contain a YAML mapping", path)
            continue

        enabled = payload.get("enabled", True)
        if enabled is False:
            return empty

        applies_to_modes = payload.get("applies_to_modes")
        if applies_to_modes:
            if not isinstance(applies_to_modes, list):
                logger.warning(
                    "[MODEL_PROMPTS] applies_to_modes must be a list in %s; skipping override",
                    path,
                )
                return empty
            allowed_modes = {str(item).strip() for item in applies_to_modes if str(item).strip()}
            if mode and allowed_modes and mode not in allowed_modes:
                return empty

        unknown_keys = sorted(set(payload.keys()) - SUPPORTED_SECTIONS - {"enabled", "description", "applies_to_modes"})
        if unknown_keys:
            logger.debug("[MODEL_PROMPTS] Ignoring unknown keys in %s: %s", path, ", ".join(unknown_keys))

        sections = {
            section: text
            for section in SUPPORTED_SECTIONS
            if (text := _coerce_section_text(payload, section))
        }
        override = ModelPromptOverride(
            provider=provider,
            model=model,
            mode=mode,
            matched_model=candidate,
            source_path=str(path),
            description=str(payload.get("description", "")).strip(),
            enabled=bool(sections),
            sections=sections,
        )
        if sections:
            logger.info(
                "[MODEL_PROMPTS] Loaded override for %s/%s via %s (%s)",
                provider,
                model,
                path,
                ", ".join(sorted(sections)),
            )
        return override

    return empty


def apply_prompt_override_sections(
    base_prompt: str,
    override: ModelPromptOverride | None,
    prepend_sections: tuple[str, ...] = (),
    append_sections: tuple[str, ...] = (),
) -> str:
    """Apply selected override sections around a base prompt."""
    if not base_prompt or not override or not override.enabled:
        return base_prompt

    prepend_parts = [override.get(section) for section in prepend_sections if override.get(section)]
    append_parts = [override.get(section) for section in append_sections if override.get(section)]
    if not prepend_parts and not append_parts:
        return base_prompt

    prompt_parts = []
    if prepend_parts:
        prompt_parts.append("MODEL-SPECIFIC GUIDANCE:\n" + "\n".join(prepend_parts))
    prompt_parts.append(base_prompt.strip())
    if append_parts:
        prompt_parts.append("MODEL-SPECIFIC REMINDERS:\n" + "\n".join(append_parts))
    return "\n\n".join(part for part in prompt_parts if part).strip()
