import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from status_phrases import StatusPhrases


PHRASE_CONFIGS = (
    ROOT / "config" / "status_phrases.json",
    ROOT / "config" / "status_phrases_unhinged.json",
)


def _enabled_manifest_tools() -> set[str]:
    names: set[str] = set()
    for path in (ROOT / "skills").rglob("*.tool.json"):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("enabled") is not False:
            names.add(manifest["name"])
    return names


def test_tool_alias_uses_family_phrase_and_direct_override_still_wins():
    selector = StatusPhrases(config_path=str(PHRASE_CONFIGS[0]), mode="normal")

    travel_start = selector.tool_specific["_family_travel"]["start"]
    assert selector.get_phrase("task_start", "flight_search") in travel_start

    ocr_start = selector.tool_specific["document_ocr"]["start"]
    assert selector.get_phrase("task_start", "document_ocr") in ocr_start


def test_normal_and_unhinged_configs_cover_every_enabled_local_tool():
    enabled_tools = _enabled_manifest_tools()
    alias_sets: list[set[str]] = []

    for config_path in PHRASE_CONFIGS:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        tool_specific = config["tool_specific"]
        aliases = config["tool_aliases"]
        alias_sets.append(set(aliases))

        for tool_name, target in aliases.items():
            assert tool_name not in tool_specific, f"{tool_name} has a redundant alias"
            assert target in tool_specific, f"{tool_name} targets missing phrase family {target}"
            target_phrases = tool_specific[target]
            assert isinstance(target_phrases, dict)
            assert target_phrases.get("start")
            assert target_phrases.get("progress")

        covered = {
            name
            for name, phrases in tool_specific.items()
            if not name.startswith("_") and isinstance(phrases, dict)
        } | set(aliases)
        assert enabled_tools <= covered, (
            f"{config_path.name} lacks fallback status coverage for "
            f"{sorted(enabled_tools - covered)}"
        )

    assert alias_sets[0] == alias_sets[1]


def test_aliases_are_reported_as_tool_overrides():
    selector = StatusPhrases(config_path=str(PHRASE_CONFIGS[0]), mode="normal")
    overrides = selector.list_tool_overrides()

    assert "flight_search" in overrides
    assert "document_ocr" in overrides
    assert "_family_travel" not in overrides


def test_static_image_phrases_do_not_guess_the_provider():
    provider_names = ("gemini", "openai", "xai", "grok", "dall-e", "dalle")

    for config_path in PHRASE_CONFIGS:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        image_phrases = config["tool_specific"]["generate_image"]
        phrases = image_phrases["start"] + image_phrases["progress"]

        for phrase in phrases:
            assert not any(name in phrase.casefold() for name in provider_names), (
                f"{config_path.name} has a provider-specific image status: {phrase}"
            )
