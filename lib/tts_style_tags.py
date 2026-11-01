"""Reviewed TTS delivery cues, provider capabilities, and final-speech prompts.

This module uses only the standard library. Callers supply the effective provider,
model, or scoped config getter; importing it never loads configuration.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SpeechTagPolicy:
    """One provider's reviewed markup and separate playback/generation gates."""

    label: str
    enabled_setting: str
    inline_tags: frozenset[str]
    wrapping_tags: frozenset[str] = frozenset()
    model_setting: str = ""
    playback_models: frozenset[str] | None = None
    generation_models: frozenset[str] | None = None
    model_labels: dict[str, str] = field(default_factory=dict)
    parameterized_tags: frozenset[str] = frozenset()
    parameterized_instruction: str = ""
    preserve_paragraphs: bool = False


XAI_INLINE_SPEECH_TAGS = frozenset({
    "pause", "long-pause", "hum-tune", "laugh", "chuckle", "giggle", "cry",
    "tsk", "tongue-click", "lip-smack", "breath", "inhale", "exhale", "sigh",
})
XAI_WRAPPING_SPEECH_TAGS = frozenset({
    "soft", "whisper", "loud", "build-intensity", "decrease-intensity",
    "higher-pitch", "lower-pitch", "slow", "fast", "sing-song", "singing",
    "laugh-speak", "emphasis",
})
ELEVENLABS_INLINE_SPEECH_TAGS = frozenset({
    "curious", "excited", "sarcastic", "crying", "mischievously",
    "whispers", "whispering", "shouts", "shouting", "laughs", "laughing",
    "clears throat", "sighs", "exhales",
})
ELEVENLABS_V4_MODELS = frozenset({"eleven_v4", "eleven_v4_turbo"})
ELEVENLABS_AUDIO_TAG_MODELS = ELEVENLABS_V4_MODELS | {"eleven_v3"}

# Require a distinct IPA symbol: ASCII-only /docs/ and /ti/ are ambiguous
# Markdown destinations, not enough evidence for a pronunciation instruction.
_IPA_SYMBOLS = "\u00e6\u00f0\u00f8\u014b\u0153\u0250-\u02af\u02c8\u02cc\u02d0\u02d1\u0300-\u036f"
KOKORO_PAUSE_PATTERN = re.compile(
    r'\[pause:([0-9]+(?:\.[0-9]+)?)s\](?!\s*\()', re.IGNORECASE,
)
KOKORO_PRONUNCIATION_PATTERN = re.compile(
    rf'\[([^\[\]<>\r\n]{{1,200}})\]\(/'
    rf'((?=[A-Za-z .{_IPA_SYMBOLS}]*[{_IPA_SYMBOLS}])[A-Za-z .{_IPA_SYMBOLS}]{{1,200}})/\)',
)
_CONTROL_NUMBER = r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+|nan|inf(?:inity)?)'
_KOKORO_VOICE = r'[a-z]{2}_[a-z0-9_]+(?:\([0-9]+(?:\.[0-9]+)?\))?'
KOKORO_CONTROL_PATTERN = re.compile(
    rf'\[(?:(?:pause|rate)(?::|=|\s+)\s*{_CONTROL_NUMBER}s?'
    rf'|voice:(?=[^\]\r\n]{{1,200}}\])\s*{_KOKORO_VOICE}(?:\+{_KOKORO_VOICE})*)\](?!\s*\()',
    re.IGNORECASE,
)


def markdown_code_spans(text: str) -> list[tuple[int, int]]:
    """Find fenced/inline examples so cue cleanup cannot rewrite literal code."""
    fences = []
    opening = re.compile(r'(?m)^[ \t]{0,3}(`{3,}|~{3,})[^\r\n]*(?:\r?\n|$)')
    position = 0
    while match := opening.search(text, position):
        delimiter = match.group(1)
        closing = re.compile(
            rf'(?m)^[ \t]{{0,3}}{re.escape(delimiter[0])}{{{len(delimiter)},}}[ \t]*\r?$',
        ).search(text, match.end())
        end = closing.end() if closing else len(text)
        fences.append((match.start(), end))
        position = end
    inline = re.compile(r'(?<!`)(`+)(?!`)[\s\S]*?(?<!`)\1(?!`)')
    spans = []
    position = 0
    for start, end in [*fences, (len(text), len(text))]:
        spans.extend((m.start(), m.end()) for m in inline.finditer(text, position, start))
        if end > start:
            spans.append((start, end))
        position = end
    return spans

# Register reviewed cues here. None means all models; an empty set means none.
# Generation toggles never disable explicitly supplied, supported playback cues.
TTS_TAG_POLICIES = {
    "xai": SpeechTagPolicy(
        label="xAI", enabled_setting="XAI_TTS_STYLE_TAGS_ENABLED",
        inline_tags=XAI_INLINE_SPEECH_TAGS, wrapping_tags=XAI_WRAPPING_SPEECH_TAGS,
    ),
    "elevenlabs": SpeechTagPolicy(
        label="ElevenLabs", enabled_setting="ELEVENLABS_TTS_STYLE_TAGS_ENABLED",
        inline_tags=ELEVENLABS_INLINE_SPEECH_TAGS, model_setting="ELEVENLABS_TTS_MODEL",
        playback_models=ELEVENLABS_AUDIO_TAG_MODELS, generation_models=ELEVENLABS_V4_MODELS,
        model_labels={"eleven_v4": "ElevenLabs v4", "eleven_v4_turbo": "ElevenLabs v4 Turbo"},
    ),
    "kokoro": SpeechTagPolicy(
        label="Kokoro", enabled_setting="KOKORO_TTS_STYLE_TAGS_ENABLED",
        inline_tags=frozenset(), parameterized_tags=frozenset({"pause", "pronunciation"}),
        preserve_paragraphs=True,
        parameterized_instruction=(
            "Use [pause:0.4s] for an occasional short pause (about 0.2 to 0.6 seconds). "
            "For English pronunciation corrections, use [word](/IPA/) only when the IPA is "
            "known, for example [Worcester](/wˈʊstər/); do not guess phonemes. "
            "Keep the configured speaker and speed. Do not use emotion tags, [voice:], "
            "[rate:], XML, or SSML. "
        ),
    ),
}


def get_speech_tag_policy(provider: str, model: str = "") -> SpeechTagPolicy | None:
    """Resolve cues for the actual playback provider and effective model."""
    policy = TTS_TAG_POLICIES.get((provider or "").strip().lower())
    if policy is None or (
        policy.playback_models is not None and (model or "").strip() not in policy.playback_models
    ):
        return None
    return policy


def speech_tag_options(provider: str, elevenlabs_model: str = "") -> dict[str, SpeechTagPolicy | None]:
    """Normalizer kwargs; the second argument is the effective playback model.

    The model argument keeps its historical keyword name for existing callers.
    """
    return {"speech_tag_policy": get_speech_tag_policy(provider, elevenlabs_model)}


def configured_speech_tag_options(
    get_setting: Callable[[str, str], str], *, purpose: str = "final", default_provider: str = "",
) -> dict[str, SpeechTagPolicy | None]:
    """Resolve actual native playback settings before any caller strips cues."""
    provider = get_setting("TTS_PROVIDER", default_provider)
    model = get_setting("ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2")
    if purpose == "status":
        model = get_setting("ELEVENLABS_STATUS_TTS_MODEL", "") or model
    return speech_tag_options(provider, model)


def all_inline_speech_tags() -> frozenset[str]:
    """Union for display cleanup, including cues from inactive providers."""
    return frozenset(tag for policy in TTS_TAG_POLICIES.values() for tag in policy.inline_tags)


def all_wrapping_speech_tags() -> frozenset[str]:
    """Union for display cleanup, including cues from inactive providers."""
    return frozenset(tag for policy in TTS_TAG_POLICIES.values() for tag in policy.wrapping_tags)


def _generation_policy(
    get_setting: Callable[[str, str], str], provider: str | None,
) -> tuple[SpeechTagPolicy | None, str]:
    selected = get_setting("TTS_PROVIDER", "").strip().lower()
    if provider is not None and selected != provider:
        return None, ""
    policy = TTS_TAG_POLICIES.get(selected)
    if policy is None:
        return None, ""
    model = get_setting(policy.model_setting, "").strip() if policy.model_setting else ""
    enabled = get_setting(policy.enabled_setting, "true").strip().lower()
    if (
        enabled not in {"1", "true", "yes", "on"}
        or get_speech_tag_policy(selected, model) is None
        or (policy.generation_models is not None and model not in policy.generation_models)
    ):
        return None, model
    return policy, model


def tts_style_tags_enabled(
    get_setting: Callable[[str, str], str], *, provider: str | None = None,
) -> bool:
    """Whether the active final-speech provider permits generated cues."""
    policy, _ = _generation_policy(get_setting, provider)
    return policy is not None


def tts_style_tags_instruction(
    get_setting: Callable[[str, str], str], *, provider: str | None = None,
) -> str:
    """One vocabulary-derived instruction shared by router and formatter."""
    policy, model = _generation_policy(get_setting, provider)
    if policy is None:
        return ""
    label = policy.model_labels.get(model, policy.label)
    inline = ", ".join(f"[{tag}]" for tag in sorted(policy.inline_tags))
    instruction = (
        f"\n\n{label} TTS is active. You may use these supported speech tags sparingly "
        "in the FINAL SPOKEN RESPONSE only when they improve delivery. "
    )
    if inline:
        instruction += f"Inline sounds: {inline}. "
    if policy.parameterized_instruction:
        instruction += policy.parameterized_instruction
    elif policy.wrapping_tags:
        wrapping = ", ".join(f"<{tag}>...</{tag}>" for tag in sorted(policy.wrapping_tags))
        example = sorted(policy.wrapping_tags)[0]
        instruction += f"Wrapping styles: {wrapping}. Use exact tag syntax: "
        if policy.inline_tags:
            instruction += f"inline tags use square brackets like [{sorted(policy.inline_tags)[0]}]; "
        instruction += f"wrapping tags use angle brackets like <{example}>text</{example}>. "
    else:
        instruction += "Use exact square-bracket syntax. Do not use XML, SSML, or wrapping tags. "
    return instruction + (
        "Use only the listed tags for reply speech. For generate_audio.text, follow that "
        "tool's selected provider/model capabilities from audio_voices instead; its native "
        "speech cues are allowed independently of reply-TTS settings. Never put speech tags "
        "in other tool arguments, code, URLs, "
        "filenames, IDs, prices, data tables, or factual lists. Do not tag every sentence. "
        "Keep the configured word limit; tags should not add extra content."
    )
