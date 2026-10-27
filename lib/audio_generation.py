"""One-shot spoken-audio generation, independent of Jarvis reply playback.

No cache, text rewriting, splitting, automatic provider fallback, or POST retry.
Provider limits are checked before submission; duration is measured afterward.
"""

from __future__ import annotations

import io
import json
import math
import os
import re
import subprocess
import tempfile
import time
import wave
from urllib.parse import urlsplit

import requests
from config_loader import get_config_value
from http_client import get_session
from remote_completion import RemoteCompletionError, submission_error
from requests.adapters import HTTPAdapter
from tts_style_tags import (
    all_inline_speech_tags,
    all_wrapping_speech_tags,
    get_speech_tag_policy,
)

PROVIDERS = frozenset({"openai", "elevenlabs", "xai", "qwen3-tts", "kokoro"})
MAX_AUDIO_BYTES = 64 * 1024 * 1024
_ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
_FORMATS = {"mp3": "audio/mpeg", "wav": "audio/wav"}
_OPENAI_VOICES = frozenset({"alloy", "ash", "ballad", "coral", "echo", "fable", "onyx",
                            "nova", "sage", "shimmer", "verse", "marin", "cedar"})
_OPENAI_LEGACY_VOICES = frozenset({"alloy", "ash", "coral", "echo", "fable", "onyx",
                                  "nova", "sage", "shimmer"})
_OPENAI_INSTRUCTION_MODELS = frozenset({"gpt-4o-mini-tts", "gpt-4o-mini-tts-2025-12-15"})
_INLINE_CUE = re.compile(r"\[([^\[\]\r\n]{1,80})\]")
_WRAPPING_CUE = re.compile(r"</?([A-Za-z][A-Za-z-]*)\s*>")


def get_audio_delivery_capabilities(provider: str, model: str) -> dict:
    """Describe tool delivery controls without inheriting reply-TTS toggles.

    Examples are a small guide to the provider's syntax, not a closed provider
    vocabulary. In particular ElevenLabs also accepts free-form bracket cues.
    """
    policy = get_speech_tag_policy(provider, model)
    instructions_field = ""
    if provider == "openai" and model in _OPENAI_INSTRUCTION_MODELS:
        instructions_field = "instructions"
    result = {
        "instructions_supported": bool(instructions_field),
        "inline_tags_supported": bool(policy and policy.inline_tags),
        "wrapping_tags_supported": bool(policy and policy.wrapping_tags),
        "inline_tag_examples": [],
        "wrapping_tag_examples": [],
    }
    if instructions_field:
        result["instructions_field"] = instructions_field
    if provider == "elevenlabs" and policy:
        result["inline_tag_examples"] = ["[whispering]", "[excited]", "[laughs]"]
        result["note"] = "Place square-bracket delivery cues in text; no SSML or XML wrapping."
    elif provider == "xai" and policy:
        result["inline_tag_examples"] = ["[pause]", "[laugh]", "[sigh]"]
        result["wrapping_tag_examples"] = ["<whisper>text</whisper>", "<slow>text</slow>"]
        result["note"] = "Use xAI-native bracket sounds and matching XML-style wrapping cues."
    elif instructions_field == "instructions":
        result["note"] = "Put delivery direction in instructions, separate from the exact spoken text."
    elif provider == "qwen3-tts":
        result["note"] = "No verified instruction-capable Qwen backend is exposed by this integration."
    else:
        result["note"] = "No expressive speech tags or separate instructions are exposed for this model."
    return result


def _delivery_controls(settings: dict) -> tuple[str, dict]:
    """Validate known speech syntax without changing scripts or ordinary brackets."""
    provider, model, text = (settings[key] for key in ("provider", "model", "text"))
    capabilities = get_audio_delivery_capabilities(provider, model)
    instructions = settings.get("instructions", "")
    if not isinstance(instructions, str):
        raise ValueError("instructions must be a string")
    if instructions and not instructions.strip():
        raise ValueError("instructions must contain delivery direction")
    if len(instructions) > 4096:
        raise ValueError("instructions must be at most 4096 characters")
    if instructions and not capabilities["instructions_supported"]:
        raise ValueError(f"{provider} model {model} does not support separate instructions; choose an instruction-capable provider/model")
    policy = get_speech_tag_policy(provider, model)
    reviewed_inline = all_inline_speech_tags()
    reviewed_wrapping = all_wrapping_speech_tags()
    for match in _INLINE_CUE.finditer(text):
        cue = match.group(1).strip().lower()
        if cue in reviewed_inline and (
            policy is None or cue not in policy.inline_tags
        ):
            raise ValueError(f"{provider} model {model} does not support the inline speech cue [{cue}]; use supported delivery controls")
    for match in _WRAPPING_CUE.finditer(text):
        cue = match.group(1).lower()
        if cue in reviewed_wrapping and (policy is None or cue not in policy.wrapping_tags):
            raise ValueError(f"{provider} model {model} does not support the wrapping speech cue <{cue}>")
    if provider == "elevenlabs" and policy and re.search(r"<\s*break\b", text, re.IGNORECASE):
        raise ValueError(f"ElevenLabs model {model} does not support SSML break tags; use bracket audio cues or punctuation")
    return instructions, capabilities


def _config(name: str, default: str = "") -> str:
    return str(get_config_value(name, default) or "").strip()


def audio_timeout_seconds() -> int:
    """Return the configured HTTP budget; callers add time for saving artifacts."""
    try:
        value = int(_config("AUDIO_TOOL_TIMEOUT_SECONDS", "180"))
    except ValueError:
        raise ValueError("AUDIO_TOOL_TIMEOUT_SECONDS must be an integer from 1 to 900") from None
    if not 1 <= value <= 900:
        raise ValueError("AUDIO_TOOL_TIMEOUT_SECONDS must be an integer from 1 to 900")
    return value


def _argument(arguments: dict, name: str) -> str:
    value = arguments.get(name)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value.strip()


def resolve_audio_settings(arguments: dict) -> dict:
    """Resolve explicit choices, tool overrides, then provider-specific defaults.

    Tool defaults never cross provider boundaries. The returned object contains
    public provenance and the exact input script, never credentials or URLs.
    """
    if set(arguments) - {"text", "provider", "voice", "model", "title", "instructions"}:
        raise ValueError("Unsupported generate_audio argument")
    default_provider = _config("AUDIO_TOOL_PROVIDER").lower()
    if default_provider not in PROVIDERS:
        raise ValueError("Set AUDIO_TOOL_PROVIDER to enable spoken-audio generation")
    provider = _argument(arguments, "provider").lower() or default_provider
    if provider not in PROVIDERS:
        raise ValueError("Unsupported audio provider")
    text = arguments.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("A nonempty text script is required")
    defaults = {
        "openai": ("VOICE", "onyx", "TTS_MODEL", "gpt-4o-mini-tts"),
        "elevenlabs": ("ELEVENLABS_TTS_VOICE", "", "ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2"),
        "xai": ("XAI_TTS_VOICE", "eve", "", "grok-tts"),
        "qwen3-tts": ("QWEN3_TTS_VOICE", "Jarvis", "", "tts-1"),
        "kokoro": ("KOKORO_TTS_VOICE", "af_nicole", "", "kokoro"),
    }
    voice_key, voice_default, model_key, model_default = defaults[provider]
    voice = _argument(arguments, "voice")
    model = _argument(arguments, "model")
    if provider == default_provider:
        voice = voice or _config("AUDIO_TOOL_VOICE")
        model = model or _config("AUDIO_TOOL_MODEL")
    voice = voice or _config(voice_key, voice_default)
    model = model or (_config(model_key, model_default) if model_key else model_default)
    title = _argument(arguments, "title") or "Generated speech"
    if len(title) > 200:
        raise ValueError("Audio title must be at most 200 characters")
    settings = {"text": text, "provider": provider, "voice": voice, "model": model, "title": title}
    if "instructions" in arguments:
        instructions = arguments["instructions"]
        if not isinstance(instructions, str):
            raise ValueError("instructions must be a string")
        if not instructions.strip():
            raise ValueError("instructions must contain delivery direction")
        settings["instructions"] = instructions
    _build_request(settings)  # Validate all settings before the first network call.
    audio_timeout_seconds()
    return settings


def _number(name: str, default: str, minimum: float, maximum: float) -> float:
    try:
        value = float(_config(name, default))
    except ValueError:
        raise ValueError(f"{name} must be a finite number from {minimum} to {maximum}") from None
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be a finite number from {minimum} to {maximum}")
    return value


def _credential(name: str) -> str:
    value = _config(name)
    if not value or value.lower().startswith(("your-", "your_", "replace-", "replace_")):
        raise ValueError(f"{name} is not configured")
    return value


def _local_url(name: str) -> str:
    url = _config(name)
    try:
        parsed = urlsplit(url)
        valid = parsed.scheme in {"http", "https"} and parsed.hostname and not (
            parsed.username or parsed.password or parsed.fragment
        )
        _ = parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f"{name} must be a configured HTTP(S) speech endpoint")
    return url


def _build_request(settings: dict) -> tuple[str, dict, dict, str]:
    provider, model, voice, text = (settings[key] for key in ("provider", "model", "voice", "text"))
    if provider not in PROVIDERS:
        raise ValueError("Unsupported audio provider")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("A nonempty text script is required")
    if not isinstance(model, str) or not _ID.fullmatch(model):
        raise ValueError("A valid speech model ID is required")
    if not isinstance(voice, str) or not voice or len(voice) > 160 or any(ord(c) < 32 for c in voice):
        raise ValueError("A valid voice name or ID is required")
    instructions, capabilities = _delivery_controls(settings)
    headers = {"Content-Type": "application/json"}
    extension = "mp3"
    if provider == "openai":
        if model not in {"tts-1", "tts-1-hd", "gpt-4o-mini-tts", "gpt-4o-mini-tts-2025-12-15"}:
            raise ValueError("Unsupported OpenAI speech model")
        if voice not in _OPENAI_VOICES:
            raise ValueError("OpenAI requires a supported built-in voice name")
        if model in {"tts-1", "tts-1-hd"} and voice not in _OPENAI_LEGACY_VOICES:
            raise ValueError(f"OpenAI model {model} does not support voice {voice}; choose a supported legacy voice or gpt-4o-mini-tts")
        limit = 4096
        url = "https://api.openai.com/v1/audio/speech"
        headers["Authorization"] = "Bearer " + _credential("OPENAI_API_KEY")
        payload = {"model": model, "voice": voice, "input": text, "response_format": extension}
    elif provider == "elevenlabs":
        if not _ID.fullmatch(voice):
            raise ValueError("ElevenLabs requires a voice ID, not a voice display name")
        limits = {"eleven_v3": 5000, "eleven_v4": 10000, "eleven_v4_turbo": 10000,
                  "eleven_multilingual_v2": 10000, "eleven_multilingual_v1": 10000,
                  "eleven_flash_v2_5": 40000, "eleven_turbo_v2_5": 40000,
                  "eleven_flash_v2": 30000, "eleven_turbo_v2": 30000, "eleven_monolingual_v1": 10000}
        if model not in limits:
            raise ValueError("Unsupported ElevenLabs speech model")
        limit = limits[model]
        url = "https://api.elevenlabs.io/v1/text-to-speech/" + voice
        headers["xi-api-key"] = _credential("ELEVENLABS_API_KEY")
        stability = _number("ELEVENLABS_TTS_STABILITY", "0.5", 0, 1)
        if model == "eleven_v3":
            stability = min((0.0, 0.5, 1.0), key=lambda item: abs(item - stability))
        voice_settings = {"stability": stability,
                          "similarity_boost": _number("ELEVENLABS_TTS_SIMILARITY_BOOST", "0.75", 0, 1)}
        if model not in {"eleven_v3", "eleven_v4", "eleven_v4_turbo"}:
            voice_settings.update({"style": _number("ELEVENLABS_TTS_STYLE", "0.5", 0, 1),
                                   "use_speaker_boost": _config("ELEVENLABS_TTS_USE_SPEAKER_BOOST", "true").lower() in {"true", "1", "yes", "on"}})
        payload = {"text": text, "model_id": model, "voice_settings": voice_settings}
    elif provider == "xai":
        if model != "grok-tts":
            raise ValueError("xAI speech uses grok-tts; its endpoint has no selectable model")
        if not _ID.fullmatch(voice):
            raise ValueError("xAI requires a voice ID")
        limit = int(_number("XAI_TTS_MAX_CHARS", "15000", 1, 15000))
        extension = _config("XAI_TTS_CODEC", "mp3").lower()
        if extension not in {"mp3", "wav"}:
            raise ValueError("Generated xAI audio requires XAI_TTS_CODEC=mp3 or wav")
        sample_rate = int(_number("XAI_TTS_SAMPLE_RATE", "24000", 8000, 48000))
        if sample_rate not in {8000, 16000, 22050, 24000, 44100, 48000}:
            raise ValueError("Unsupported XAI_TTS_SAMPLE_RATE")
        output_format = {"codec": extension, "sample_rate": sample_rate}
        if extension == "mp3":
            bit_rate = int(_number("XAI_TTS_BIT_RATE", "128000", 32000, 192000))
            if bit_rate not in {32000, 64000, 96000, 128000, 192000}:
                raise ValueError("Unsupported XAI_TTS_BIT_RATE")
            output_format["bit_rate"] = bit_rate
        url = "https://api.x.ai/v1/tts"
        headers["Authorization"] = "Bearer " + _credential("XAI_API_KEY")
        payload = {"text": text, "voice_id": voice, "language": _config("XAI_TTS_LANGUAGE", "en"),
                   "output_format": output_format}
    else:
        expected_model = "tts-1" if provider == "qwen3-tts" else "kokoro"
        if model != expected_model:
            raise ValueError(f"{provider} uses the configured service model {expected_model}")
        prefix = "QWEN3_TTS" if provider == "qwen3-tts" else "KOKORO_TTS"
        url = _local_url(prefix + "_URL")
        extension = _config("QWEN3_TTS_FORMAT", "mp3").lower() if provider == "qwen3-tts" else "mp3"
        if extension not in _FORMATS:
            raise ValueError("Generated audio requires QWEN3_TTS_FORMAT=mp3 or wav")
        payload = {"model": model, "input": text, "voice": voice,
                   "speed": _number(prefix + "_SPEED", "1.0", 0.25, 4),
                   "response_format": extension}
        limit = 4096 if provider == "qwen3-tts" else 40000
    if instructions:
        payload[capabilities["instructions_field"]] = instructions
    if len(text) > limit:
        raise ValueError(f"{provider} model {model} accepts at most {limit} characters per audio request; text was not sent or truncated")
    return url, headers, payload, extension


def _measure_audio(audio: bytes, extension: str) -> float | None:
    if audio[:4] == b"RIFF":
        try:
            with wave.open(io.BytesIO(audio), "rb") as wav:
                duration = wav.getnframes() / wav.getframerate()
            if math.isfinite(duration) and duration > 0:
                return duration
        except (wave.Error, EOFError, ZeroDivisionError):
            pass
    try:
        with tempfile.NamedTemporaryFile(suffix="." + extension) as temp:
            temp.write(audio)
            temp.flush()
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                 "-of", "json", temp.name], capture_output=True, timeout=15, check=False,
                env={key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ},
            )
        data = json.loads(result.stdout)
        duration = float(data["format"]["duration"])
        if result.returncode == 0 and any(stream.get("codec_type") == "audio" for stream in data.get("streams", [])) and math.isfinite(duration) and duration > 0:
            return duration
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        pass
    return None


def synthesize_audio(settings: dict) -> dict:
    """Make one submission and return bounded, measured audio bytes.

    A transport failure leaves the remote outcome unknown. Neither request
    redirects nor HTTP adapters may replay a paid submission.
    """
    url, headers, payload, extension = _build_request(settings)
    timeout = audio_timeout_seconds()
    deadline = time.monotonic() + timeout
    response = None
    # Shared proxy behavior, with adapter retries explicitly disabled.
    session = get_session(use_proxy=False, retries=0)
    session.trust_env = False  # No ambient proxy settings or .netrc credentials.
    # The shared Retry(total=0) still raises on status_forcelist responses,
    # hiding confirmed 429/5xx responses. Plain no-retry adapters retain them.
    session.mount("http://", HTTPAdapter(max_retries=0))
    session.mount("https://", HTTPAdapter(max_retries=0))
    try:
        response = session.post(url, headers=headers, json=payload, stream=True,
                                timeout=(min(10, timeout), timeout), allow_redirects=False)
        if response.status_code != 200:
            raise submission_error(response.status_code,
                                   f"Audio provider returned HTTP {response.status_code}")
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if content_type.startswith("text/") or content_type in {"application/json", "application/problem+json"}:
            raise RemoteCompletionError("The provider returned non-audio content; do not regenerate automatically", "completed")
        try:
            content_length = int(response.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length > MAX_AUDIO_BYTES:
            raise RemoteCompletionError("Generated audio exceeds the 64 MiB download limit; do not regenerate automatically", "completed")
        audio = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            if time.monotonic() > deadline:
                raise RemoteCompletionError("Audio download exceeded its time budget; do not regenerate automatically", "completed")
            if len(audio) + len(chunk) > MAX_AUDIO_BYTES:
                raise RemoteCompletionError("Generated audio exceeds the 64 MiB download limit; do not regenerate automatically", "completed")
            audio.extend(chunk)
        if not audio:
            raise RemoteCompletionError("The provider returned empty audio; do not regenerate automatically", "completed")
        data = bytes(audio)
        if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
            extension = "wav"
        elif data.startswith(b"ID3") or len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0:
            extension = "mp3"
        else:
            raise RemoteCompletionError("The provider returned unrecognized audio content; do not regenerate automatically", "completed")
        duration = _measure_audio(data, extension)
        result = {"audio_bytes": data, "extension": extension, "mime_type": _FORMATS[extension],
                  "duration_seconds": duration}
        if duration is None:
            result["duration_warning"] = "Audio duration could not be measured; the generated file was preserved"
        return result
    except requests.RequestException:
        raise RuntimeError("Audio generation connection interrupted; outcome is unknown, so do not retry automatically") from None
    finally:
        if response is not None:
            response.close()
        session.close()
