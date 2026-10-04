"""Provider-scoped instructions for expressive final speech."""

from tts_normalizer import ELEVENLABS_INLINE_SPEECH_TAGS, ELEVENLABS_V4_MODELS, speech_tag_options


def elevenlabs_tts_style_tags_instruction(get_setting) -> str:
    """Allow reviewed cues only for ElevenLabs v4 when generation is enabled."""
    model = get_setting("ELEVENLABS_TTS_MODEL", "").strip()
    options = speech_tag_options(get_setting("TTS_PROVIDER", ""), model)
    enabled = get_setting("ELEVENLABS_TTS_STYLE_TAGS_ENABLED", "true").strip().lower()
    if (
        not options["preserve_elevenlabs_tags"]
        or model not in ELEVENLABS_V4_MODELS
        or enabled not in {"1", "true", "yes", "on"}
    ):
        return ""
    tags = ", ".join(f"[{tag}]" for tag in sorted(ELEVENLABS_INLINE_SPEECH_TAGS))
    model_label = "v4 Turbo" if model == "eleven_v4_turbo" else "v4"
    return (
        f"\n\nElevenLabs {model_label} TTS is active. You may use these supported audio tags sparingly "
        f"in the FINAL SPOKEN RESPONSE only when they improve delivery: {tags}. "
        "Use exact square-bracket syntax, for example [curious] How did that happen? "
        "Use only the listed tags. Do not use XML, SSML, or xAI wrapping tags. "
        "Never put speech tags in tool arguments, code, URLs, filenames, IDs, prices, "
        "data tables, or factual lists. Do not tag every sentence. "
        "Keep the configured word limit; tags should not add extra content."
    )
