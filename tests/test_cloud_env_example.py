"""Regression checks for the canonical cloud configuration template."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLOUD_TEMPLATE = ROOT / "config" / "cloud.env.example"
ASSIGNMENT_RE = re.compile(r"(?m)^\s*#?\s*([A-Z][A-Z0-9_]*)\s*=")


def _setting_names(text: str) -> set[str]:
    """Return active and commented example assignment names."""

    return set(ASSIGNMENT_RE.findall(text))


def test_cloud_template_defaults_to_openai_with_required_ollama_embeddings() -> None:
    text = CLOUD_TEMPLATE.read_text(encoding="utf-8")

    assert 'LLM_PROVIDER="openai"' in text
    assert "OPENAI_API_KEY=" in text
    assert "OLLAMA_BASE_URL=" in text
    assert 'OLLAMA_EMBEDDING_MODEL="bigsk1/jarvis-embedding:bf16-v1"' in text
    assert "OLLAMA_EMBEDDING_MODEL_DIGEST=" in text
    assert "TTS_PROVIDER=openai" in text
    assert 'IMAGE_TOOL_PROVIDER="openai"' in text
    assert 'VIDEO_TOOL_PROVIDER="xai"' in text


def test_openai_only_profile_is_offered_but_not_selected_by_default() -> None:
    text = CLOUD_TEMPLATE.read_text(encoding="utf-8")

    default_index = text.index("JARVIS_TOOL_PROFILE=default")
    suggested_index = text.index("# JARVIS_TOOL_PROFILE=openai_only")

    assert default_index < suggested_index
    assert not re.search(r"(?m)^JARVIS_TOOL_PROFILE=openai_only$", text)


def test_intelligence_and_feedback_controls_are_documented() -> None:
    text = CLOUD_TEMPLATE.read_text(encoding="utf-8")
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
        "INTELLIGENCE_RELEVANCE_THRESHOLD",
        "INTELLIGENCE_NEGATIVE_WEIGHT",
        "INTELLIGENCE_DECAY_INTERVAL_DAYS",
    }

    missing = sorted(required - _setting_names(text))
    assert not missing, f"Learning settings missing from cloud template: {missing}"
    assert re.search(r"(?m)^FEEDBACK_RANDOM_ENABLED=false$", text)
    assert re.search(r"(?m)^USER_CORRECTION_APPEND_LESSONS=false$", text)


def test_default_tool_blocklist_keeps_unconfigured_services_hidden() -> None:
    text = CLOUD_TEMPLATE.read_text(encoding="utf-8")
    assignment = re.compile(r'(?m)^BLOCKED_TOOLS="([^"]*)"$')
    blocked = assignment.search(text)

    assert blocked is not None
    assert "supa_crawl_knowledge" in blocked.group(1).split(",")


def _public_manifest_environment_requirements(skills_dir: Path) -> set[str]:
    """Private tools must not require entries in the tracked ENV template."""
    required_names: set[str] = set()
    manifests = list(skills_dir.glob("*.tool.json"))
    manifests.extend((skills_dir / "auto-tools").glob("*.tool.json"))
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        availability = manifest.get("availability") or {}

        for key in ("all_of_env", "any_of_env"):
            required_names.update(availability.get(key) or ())

        provider_setting = availability.get("provider_setting")
        if provider_setting:
            required_names.add(provider_setting)

        for requirements in (availability.get("provider_requirements") or {}).values():
            for key in ("all_of_env", "any_of_env"):
                required_names.update(requirements.get(key) or ())

    return required_names


def test_manifest_environment_requirements_are_documented() -> None:
    """Every public credential-aware tool requirement has a visible example."""
    required_names = _public_manifest_environment_requirements(ROOT / "skills")
    text = CLOUD_TEMPLATE.read_text(encoding="utf-8")
    missing = sorted(required_names - _setting_names(text))

    assert not missing, (
        "Tool manifest environment requirements are missing from "
        f"config/cloud.env.example: {missing}"
    )


def test_public_environment_coverage_excludes_personal_tools(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    for directory, name, env_name in (
        (skills_dir, "shared_fixture", "SHARED_FIXTURE_KEY"),
        (skills_dir / "auto-tools", "generated_fixture", "GENERATED_FIXTURE_KEY"),
        (skills_dir / "personal", "private_fixture", "PRIVATE_FIXTURE_KEY"),
        (skills_dir / "personal" / "nested", "nested_fixture", "PRIVATE_NESTED_KEY"),
    ):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{name}.tool.json").write_text(json.dumps({
            "name": name,
            "enabled": True,
            "availability": {"all_of_env": [env_name]},
        }), encoding="utf-8")

    assert _public_manifest_environment_requirements(skills_dir) == {
        "SHARED_FIXTURE_KEY", "GENERATED_FIXTURE_KEY",
    }
