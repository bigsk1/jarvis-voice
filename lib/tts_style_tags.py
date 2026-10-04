"""Reviewed TTS delivery cues, provider capabilities, and final-speech prompts.

This module uses only the standard library. Callers supply the effective provider,
model, or scoped config getter; importing it never loads configuration.
"""

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
    if policy.wrapping_tags:
        wrapping = ", ".join(f"<{tag}>...</{tag}>" for tag in sorted(policy.wrapping_tags))
        example = sorted(policy.wrapping_tags)[0]
        instruction += f"Wrapping styles: {wrapping}. Use exact tag syntax: "
        if policy.inline_tags:
            instruction += f"inline tags use square brackets like [{sorted(policy.inline_tags)[0]}]; "
        instruction += f"wrapping tags use angle brackets like <{example}>text</{example}>. "
    else:
        instruction += "Use exact square-bracket syntax. Do not use XML, SSML, or wrapping tags. "
    return instruction + (
        "Use only the listed tags. Never put speech tags in tool arguments, code, URLs, "
        "filenames, IDs, prices, data tables, or factual lists. Do not tag every sentence. "
        "Keep the configured word limit; tags should not add extra content."
    )
