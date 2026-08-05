"""Regression checks for the concise OpenAI-primary cloud template."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FULL_TEMPLATE = ROOT / "config" / "cloud.env.example"
OPENAI_TEMPLATE = ROOT / "config" / "cloud.openai.env.example"
ASSIGNMENT_RE = re.compile(r"(?m)^\s*#?\s*([A-Z][A-Z0-9_]*)\s*=")


def _section(text: str, start: str, end: str | None = None) -> str:
    start_index = text.index(start)
    end_index = text.index(end, start_index) if end else len(text)
    return text[start_index:end_index]


def _setting_names(text: str) -> set[str]:
    """Return active and commented example assignment names."""

    return set(ASSIGNMENT_RE.findall(text))


def test_openai_core_is_first_and_optional_integrations_are_last() -> None:
    text = OPENAI_TEMPLATE.read_text(encoding="utf-8")

    core_index = text.index("# OPENAI CORE")
    optional_index = text.index("# OPTIONAL TOOL INTEGRATIONS")

    assert core_index < text.index("# ===== Tool profiles")
    assert text.index("OPENAI_API_KEY=", core_index) < text.index("# ===== Tool profiles")
    assert optional_index > text.index("MAX_RECORD_TIME=")

    core = text[core_index:optional_index]
    assert 'LLM_PROVIDER="openai"' in core
    assert "EMBEDDING_PROVIDER=openai" in core
    assert "TTS_PROVIDER=openai" in core
    assert 'IMAGE_TOOL_PROVIDER="openai"' in core
    assert 'VIDEO_TOOL_PROVIDER="openai"' in core


def test_openai_only_profile_is_offered_but_not_selected_by_default() -> None:
    text = OPENAI_TEMPLATE.read_text(encoding="utf-8")

    default_index = text.index("JARVIS_TOOL_PROFILE=default")
    suggested_index = text.index("# JARVIS_TOOL_PROFILE=openai_only")

    assert default_index < suggested_index
    assert not re.search(r"(?m)^JARVIS_TOOL_PROFILE=openai_only$", text)


def test_intelligence_and_feedback_controls_are_documented() -> None:
    """Keep the concise template complete for its built-in learning surface."""

    text = OPENAI_TEMPLATE.read_text(encoding="utf-8")
    required = {
        "FEEDBACK_PROVIDER",
        "FEEDBACK_MODEL",
        "FEEDBACK_RANDOM_ENABLED",
        "FEEDBACK_RANDOM_CHANCE",
        "USER_CORRECTION_LEARNING_MODE",
        "USER_CORRECTION_APPEND_LESSONS",
        "USER_PROFILE_CARD_ENABLED",
        "INTELLIGENCE_LEARNING_RATE",
        "INTELLIGENCE_DECAY_RATE",
        "INTELLIGENCE_ANOMALY_THRESHOLD",
        "INTELLIGENCE_MIN_CONFIDENCE",
        "INTELLIGENCE_NEGATIVE_WEIGHT",
        "INTELLIGENCE_DECAY_INTERVAL_DAYS",
    }

    missing = sorted(required - _setting_names(text))
    assert not missing, f"Learning settings missing from OpenAI template: {missing}"
    assert re.search(r"(?m)^FEEDBACK_RANDOM_ENABLED=false$", text)
    assert re.search(r"(?m)^USER_CORRECTION_APPEND_LESSONS=false$", text)


def test_optional_tool_settings_track_full_cloud_template() -> None:
    """Do not let tool integration examples silently drift out of this file."""

    full = FULL_TEMPLATE.read_text(encoding="utf-8")
    openai = OPENAI_TEMPLATE.read_text(encoding="utf-8")

    full_optional_surface = "\n".join(
        (
            _section(
                full,
                "# ===== n8n Integration",
                "# ===== Jarvis API Authentication",
            ),
            _section(
                full,
                "# ===== TTS Provider =====",
                "# --- xAI chat / tools",
            ),
            _section(
                full,
                "# ===== External API Keys =====",
                "# ===== Output Paths =====",
            ),
            _section(
                full,
                "# ===== Proxy =====",
                "# ===== Intelligence Layer",
            ),
            _section(full, "# TOOL BLOCKLIST"),
        )
    )

    missing = sorted(
        _setting_names(full_optional_surface) - _setting_names(openai)
    )
    assert not missing, (
        "Optional tool settings from config/cloud.env.example are missing from "
        f"config/cloud.openai.env.example: {missing}"
    )


def test_default_tool_blocklist_matches_full_template() -> None:
    full = FULL_TEMPLATE.read_text(encoding="utf-8")
    openai = OPENAI_TEMPLATE.read_text(encoding="utf-8")
    assignment = re.compile(r'(?m)^BLOCKED_TOOLS="([^"]*)"$')

    full_blocked = assignment.search(full)
    openai_blocked = assignment.search(openai)

    assert full_blocked is not None
    assert openai_blocked is not None
    assert openai_blocked.group(1) == full_blocked.group(1)
    assert "supa_crawl_knowledge" in openai_blocked.group(1).split(",")


def test_manifest_environment_requirements_are_documented() -> None:
    """Every credential-aware tool requirement should have a visible example."""

    required_names: set[str] = set()
    for manifest_path in (ROOT / "skills").glob("**/*.tool.json"):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        availability = manifest.get("availability") or {}

        for key in ("all_of_env", "any_of_env"):
            required_names.update(availability.get(key) or ())

        provider_setting = availability.get("provider_setting")
        if provider_setting:
            required_names.add(provider_setting)

        for requirements in (
            availability.get("provider_requirements") or {}
        ).values():
            for key in ("all_of_env", "any_of_env"):
                required_names.update(requirements.get(key) or ())

    openai = OPENAI_TEMPLATE.read_text(encoding="utf-8")
    missing = sorted(required_names - _setting_names(openai))

    assert not missing, (
        "Tool manifest environment requirements are missing from "
        f"config/cloud.openai.env.example: {missing}"
    )
