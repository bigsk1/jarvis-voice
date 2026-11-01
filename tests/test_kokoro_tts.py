"""Kokoro controls survive speech cleanup without leaking to other providers."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from lib.tts_normalizer import normalize_tts_text, strip_speech_tags_for_display
from lib.tts_style_tags import speech_tag_options, tts_style_tags_instruction

ROOT = Path(__file__).resolve().parents[1]


def test_kokoro_preserves_pronunciation_and_pauses_across_repeated_cleanup():
    text = (
        "**Visit** [Worcester](/wˈʊstər/). [PAUSE:0.4S] "
        "[excited](/ɪksˈaɪtɪd/) and [pause](/pɔːz/). "
        "[excited] [voice:af_bella] [rate:0.9] "
        "Read [more](https://example.test). 34°F 🐈"
    )
    options = speech_tag_options("kokoro")
    speech = normalize_tts_text(text, **options)
    assert speech == (
        "Visit [Worcester](/wˈʊstər/). [PAUSE:0.4S] "
        "[excited](/ɪksˈaɪtɪd/) and [pause](/pɔːz/). Read more. 34 degrees"
    )
    assert normalize_tts_text(speech, **options) == speech
    assert strip_speech_tags_for_display(speech) == (
        "Visit Worcester. excited and pause. Read more. 34 degrees"
    )


@pytest.mark.parametrize("provider,model", [
    ("openai", ""), ("qwen3-tts", ""), ("xai", ""),
    ("elevenlabs", "eleven_v4"), ("unknown", ""),
])
def test_inactive_providers_receive_words_without_kokoro_controls(provider, model):
    text = "[Worcester](/wˈʊstər/) [pause:0.4s] [rate:0.9] [voice:af_bella] is ready."
    assert normalize_tts_text(text, **speech_tag_options(provider, model)) == "Worcester is ready."


@pytest.mark.parametrize("token", [
    "[pause:60.1s]", "[pause:-1s]", "[pause:nans]", "[pause=0.4]",
    "[PAUSE 0.4]", "[rate:0.9]", "[voice:af_bella]",
    "[pause:" + "9" * 210 + "s]",
])
def test_unsupported_or_invalid_kokoro_controls_are_not_spoken(token):
    assert normalize_tts_text(f"Hello {token} there.", **speech_tag_options("kokoro")) == "Hello there."


def test_kokoro_pause_budget_drops_excess_without_changing_surrounding_words():
    text = "[pause:60s] " * 6 + "Done."
    speech = normalize_tts_text(text, **speech_tag_options("kokoro"))
    assert speech.count("[pause:60s]") == 5
    assert speech.endswith("Done.")


def test_kokoro_keeps_blank_paragraph_boundaries_and_server_pronunciation_input():
    text = "The delay is 1,5s. It is…um…fine.\n\nNext paragraph."
    options = speech_tag_options("kokoro")
    assert normalize_tts_text(text, **options) == text
    assert normalize_tts_text(normalize_tts_text(text, **options), **options) == text
    assert "\n\n" not in normalize_tts_text(text, **speech_tag_options("openai"))


def test_ordinary_bracketed_phrases_are_not_delivery_controls():
    text = "Ask the [voice actor] about [rate of change] and [pause for thought]."
    assert normalize_tts_text(text, **speech_tag_options("kokoro")) == text
    assert strip_speech_tags_for_display(text) == text


@pytest.mark.parametrize("provider,model", [
    ("kokoro", ""), ("openai", ""), ("xai", ""),
    ("elevenlabs", "eleven_v4"), ("unknown", ""),
])
def test_bracketed_facts_survive_every_policy_and_display(provider, model):
    text = (
        "The limit is [rate: 5 requests per minute]. "
        "Check [voice: front door] and [pause: a beat]."
    )
    assert normalize_tts_text(text, **speech_tag_options(provider, model)) == text
    assert normalize_tts_text(text) == text
    assert strip_speech_tags_for_display(text) == text


@pytest.mark.parametrize("link", [
    "[Docs](/docs/)", "[Guide](/guide/)", "[local](/guide)",
    "[nested](/docs/setup/)", "[pause](/docs/)", "[Docs](/docɒ1/)",
])
def test_relative_links_remain_links_in_display_and_labels_in_speech(link):
    assert strip_speech_tags_for_display(link) == link
    label = link[1:link.index("]")]
    for provider in ("kokoro", "openai", "unknown"):
        assert normalize_tts_text(link, **speech_tag_options(provider)) == label


@pytest.mark.parametrize("example", [
    "`[pause:0.4s] [Worcester](/wˈʊstər/)`",
    "`` [pause:0.4s] ` [Worcester](/wˈʊstər/) ``",
    "```text\n  [pause:0.4s]\n  [Worcester](/wˈʊstər/)\n```",
    "~~~text\n  [pause:0.4s]\n  [Worcester](/wˈʊstər/)\n~~~",
    "```text\n  [pause:0.4s]\n  [Worcester](/wˈʊstər/)\n",
])
def test_code_examples_remain_verbatim_in_display_and_never_execute_in_speech(example):
    text = f"Example:\n{example}"
    assert strip_speech_tags_for_display(text) == text
    speech = normalize_tts_text(text, **speech_tag_options("kokoro"))
    assert "[pause:" not in speech and "(/wˈʊstər/)" not in speech
    assert "Worcester" in speech
    assert normalize_tts_text(speech, **speech_tag_options("kokoro")) == speech


def test_literal_examples_and_actual_cues_are_separated_in_same_reply():
    text = "Use `[pause:0.4s]` if needed. [pause:0.2s] Visit [Worcester](/wˈʊstər/)."
    assert strip_speech_tags_for_display(text) == (
        "Use `[pause:0.4s]` if needed. Visit Worcester."
    )
    speech = normalize_tts_text(text, **speech_tag_options("kokoro"))
    assert speech == "Use pause:0.4s if needed. [pause:0.2s] Visit [Worcester](/wˈʊstər/)."


@pytest.mark.parametrize("provider,model", [
    ("kokoro", ""), ("openai", ""), ("xai", ""),
    ("elevenlabs", "eleven_v4"), ("unknown", ""),
])
@pytest.mark.parametrize("fenced", [False, True])
def test_spoken_code_retains_indexing_and_non_cue_brackets(provider, model, fenced):
    code = "items[0] = name[i]; matrix[1][2]; [Chapter 1]; [rate: 5 requests per minute]"
    example = f"```\n{code}\n```" if fenced else f"`{code}`"
    text = f"Read {example}."
    options = speech_tag_options(provider, model)
    speech = normalize_tts_text(text, **options)
    assert code in speech
    assert normalize_tts_text(speech, **options) == speech
    assert code in normalize_tts_text(text)
    assert strip_speech_tags_for_display(text) == text


@pytest.mark.parametrize("provider,model", [
    ("kokoro", ""), ("openai", ""), ("xai", ""), ("elevenlabs", "eleven_v4"),
])
def test_spoken_code_keeps_indices_beside_inert_cue_examples(provider, model):
    text = "Use `items[0] [pause:0.4s] name[i] [excited] [laugh]` if needed."
    assert normalize_tts_text(text, **speech_tag_options(provider, model)) == (
        "Use items[0] pause:0.4s name[i] excited laugh if needed."
    )


def test_kokoro_prompt_is_short_provider_specific_and_disabled_by_its_own_toggle():
    values = {"TTS_PROVIDER": "kokoro", "LLM_PROVIDER": "anthropic"}
    def get(key, default):
        return values.get(key, default)

    hint = tts_style_tags_instruction(get)
    assert "Kokoro TTS is active" in hint
    assert "[pause:0.4s]" in hint and "[Worcester](/wˈʊstər/)" in hint
    assert "do not guess phonemes" in hint
    assert "[excited]" not in hint and "[laughs]" not in hint
    values["KOKORO_TTS_STYLE_TAGS_ENABLED"] = "false"
    assert tts_style_tags_instruction(get) == ""
    values["TTS_PROVIDER"] = "openai"
    values["KOKORO_TTS_STYLE_TAGS_ENABLED"] = "true"
    assert tts_style_tags_instruction(get) == ""


def test_native_normalizer_honors_requested_kokoro_provider_without_loading_private_config():
    sample = "[Worcester](/wˈʊstər/) [pause:0.4s] [voice:af_bella] is ready."
    env = {"PATH": os.environ["PATH"], "TTS_PROVIDER": "openai", "TTS_PROVIDER_OVERRIDE": "kokoro"}
    result = subprocess.run(
        [sys.executable, str(ROOT / "bin/tts-normalize.py"), sample],
        env=env, capture_output=True, text=True, check=True,
    )
    assert result.stdout == "[Worcester](/wˈʊstər/) [pause:0.4s] is ready."
