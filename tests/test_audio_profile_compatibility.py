"""Older installed profiles keep their generation restrictions with speech tools."""

import json
from pathlib import Path

import pytest
from config_loader import config_scope
from tool_profiles import effective_enabled

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("tool", ["generate_audio", "audio_voices"])
def test_old_music_restriction_covers_speech_without_changing_other_tools(tool):
    overrides = {"generate_music": False}
    assert effective_enabled(tool, True, overrides) is False
    assert effective_enabled("generate_image", True, overrides) is True
    assert effective_enabled(tool, True, {}) is True
    assert effective_enabled(tool, False, {}) is False


@pytest.mark.parametrize("overrides,enabled", [
    ({"generate_music": False, "generate_audio": True}, {"generate_audio", "audio_voices"}),
    ({"generate_music": False, "audio_voices": True}, {"audio_voices"}),
    ({"generate_music": True, "generate_audio": False}, set()),
    ({"generate_audio": False}, set()),
    ({"generate_audio": False, "audio_voices": True}, {"audio_voices"}),
    ({"generate_music": False, "generate_audio": True, "audio_voices": False}, {"generate_audio"}),
])
def test_explicit_speech_and_lookup_choices_win_over_ancestor_restrictions(overrides, enabled):
    for tool in ("generate_audio", "audio_voices"):
        assert effective_enabled(tool, True, overrides) is (tool in enabled)
        if overrides.get(tool) is True:
            assert effective_enabled(tool, False, overrides) is True


@pytest.mark.parametrize("profile,overrides,enabled", [
    ("old_offline", {"generate_music": False}, set()),
    ("old_local_minimal", {"generate_music": False, "generate_video": False}, set()),
    ("speech_disabled", {"generate_audio": False}, set()),
    ("lookup_only", {"generate_music": False, "audio_voices": True}, {"audio_voices"}),
    ("speech_enabled", {"generate_music": False, "generate_audio": True}, {"generate_audio", "audio_voices"}),
    ("unrestricted", {}, {"generate_audio", "audio_voices"}),
])
def test_registry_honors_older_profile_files_even_with_speech_credentials(
    tmp_path, monkeypatch, profile, overrides, enabled,
):
    import tool_profiles
    from tool_schema import ToolRegistry

    skills = tmp_path / "skills"
    profiles = skills / "profiles"
    profiles.mkdir(parents=True)
    (profiles / f"{profile}.json").write_text(json.dumps({"overrides": overrides}))
    for tool in ("generate_audio", "audio_voices"):
        (skills / f"{tool}.tool.json").write_text((ROOT / f"skills/{tool}.tool.json").read_text())
    monkeypatch.setattr(tool_profiles, "get_profiles_dir", lambda: profiles)
    with config_scope("cloud", {"JARVIS_TOOL_PROFILE": profile,
                                "AUDIO_TOOL_PROVIDER": "elevenlabs", "ELEVENLABS_API_KEY": "fixture-only-key"}):
        registry = ToolRegistry(str(skills))
    assert set(registry.list_tools()) == enabled
