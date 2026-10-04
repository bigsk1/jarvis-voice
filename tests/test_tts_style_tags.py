"""Provider policy regressions and extension without normalizer/prompt branches."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from security_utils import sanitize_for_speech  # noqa: E402
from tts_normalizer import normalize_tts_text, strip_speech_tags_for_display  # noqa: E402
from tts_style_tags import (  # noqa: E402
    TTS_TAG_POLICIES,
    SpeechTagPolicy,
    speech_tag_options,
    tts_style_tags_instruction,
)


@pytest.mark.parametrize("provider,model,enabled,expected", [
    ("xai", "", "true", True),
    (" XAI ", "", " YES ", True),
    ("xai", "", "1", True),
    ("xai", "", "on", True),
    ("xai", "", "false", False),
    ("xai", "", "0", False),
    ("elevenlabs", "eleven_v4", "true", True),
    ("elevenlabs", "eleven_v4_turbo", "true", True),
    ("elevenlabs", "eleven_v4", "false", False),
    ("elevenlabs", "eleven_v3", "true", False),
    ("elevenlabs", "eleven_multilingual_v2", "true", False),
    ("openai", "eleven_v4", "true", False),
    ("future-unknown", "", "true", False),
])
def test_prompt_gate_uses_effective_tts_provider_model_and_toggle(provider, model, enabled, expected):
    values = {"TTS_PROVIDER": provider, "ELEVENLABS_TTS_MODEL": model,
              "XAI_TTS_STYLE_TAGS_ENABLED": enabled, "ELEVENLABS_TTS_STYLE_TAGS_ENABLED": enabled,
              "LLM_PROVIDER": "xai"}
    instruction = tts_style_tags_instruction(lambda key, default: values.get(key, default))
    assert bool(instruction) is expected
    if expected:
        assert "FINAL SPOKEN RESPONSE only" in instruction
        assert "tool arguments" in instruction
        assert "word limit" in instruction


@pytest.mark.parametrize("provider,model,sample,expected", [
    ("xai", "", "[laugh] <soft>Hello</soft>", "[laugh] <soft>Hello</soft>"),
    ("elevenlabs", "eleven_v3", "[whispers] Hello", "[whispers] Hello"),
    ("elevenlabs", "eleven_v4", "[whispers] Hello", "[whispers] Hello"),
    ("elevenlabs", "eleven_v4_turbo", "[whispers] Hello", "[whispers] Hello"),
    ("elevenlabs", "eleven_multilingual_v2", "[whispers] Hello", "Hello"),
])
def test_disabled_generation_does_not_disable_explicit_playback(provider, model, sample, expected):
    values = {"TTS_PROVIDER": provider, "ELEVENLABS_TTS_MODEL": model,
              "XAI_TTS_STYLE_TAGS_ENABLED": "false", "ELEVENLABS_TTS_STYLE_TAGS_ENABLED": "false"}
    assert tts_style_tags_instruction(lambda key, default: values.get(key, default)) == ""
    assert sanitize_for_speech(sample, **speech_tag_options(provider, model)) == expected


def test_new_provider_policy_drives_prompt_playback_and_display_without_provider_branches(monkeypatch):
    policy = SpeechTagPolicy(
        label="Example", enabled_setting="EXAMPLE_TTS_TAGS_ENABLED",
        inline_tags=frozenset({"warmly", "gentle laugh"}), wrapping_tags=frozenset({"calm"}),
        model_setting="EXAMPLE_TTS_MODEL", playback_models=frozenset({"speech-1", "speech-2"}),
        generation_models=frozenset({"speech-2"}),
    )
    monkeypatch.setitem(TTS_TAG_POLICIES, "example", policy)
    values = {"TTS_PROVIDER": "example", "EXAMPLE_TTS_MODEL": "speech-2"}
    instruction = tts_style_tags_instruction(lambda key, default: values.get(key, default))
    assert "Example TTS is active" in instruction
    assert "[warmly]" in instruction and "[gentle laugh]" in instruction
    assert "<calm>...</calm>" in instruction
    assert "[pause]" not in instruction and "<slow>" not in instruction
    sample = "[WARMLY]] **Hello.** <calm>Take it easy.</calm> [gentle laugh]"
    expected = "[warmly] Hello. <calm>Take it easy.</calm> [gentle laugh]"
    for model in ("speech-1", "speech-2"):
        options = speech_tag_options("example", model)
        assert sanitize_for_speech(sample, **options) == expected
        assert normalize_tts_text(expected, **options) == expected
    assert strip_speech_tags_for_display(sample) == "**Hello.** Take it easy."
    assert normalize_tts_text(sample) == "Hello. Take it easy."
    assert normalize_tts_text(sample, **speech_tag_options("example", "unknown")) == "Hello. Take it easy."
    values["EXAMPLE_TTS_MODEL"] = "speech-1"
    assert tts_style_tags_instruction(lambda key, default: values.get(key, default)) == ""
