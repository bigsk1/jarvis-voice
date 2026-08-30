"""Provider-neutral transcription for existing audio files.

This module is intentionally separate from the wake-word/interactive STT CLI.
It reuses the same provider protocol helpers, but owns long-file limits,
chunking, and ``AUDIO_TRANSCRIBE_*`` policy so batch work cannot silently alter
the microphone path.
"""

from __future__ import annotations

import math
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from config_loader import get_active_config_mode, get_config_value
from stt_client import (
    STTProviderError,
    default_model_for_provider,
    normalize_stt_provider,
    run_with_stt_fallback,
    transcribe_openai_compatible,
)

SUPPORTED_AUDIO_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpga",
    ".ogg",
    ".wav",
    ".webm",
}
DEFAULT_MAX_FILE_MB = 250
DEFAULT_MAX_DURATION_SECONDS = 7200
DEFAULT_PROVIDER_MAX_MB = 25
DEFAULT_CHUNK_SECONDS = 300
DEFAULT_TIMEOUT_SECONDS = 900
DEFAULT_REQUEST_TIMEOUT_SECONDS = 300
_PCM_BYTES_PER_SECOND = 16_000 * 2  # mono 16 kHz, signed 16-bit PCM
_SILENCE_END_RE = re.compile(r"silence_end:\s*([0-9]+(?:\.[0-9]+)?)")


@dataclass(frozen=True)
class AudioInfo:
    path: Path
    filename: str
    size_bytes: int
    duration_seconds: float
    format_name: str


@dataclass(frozen=True)
class AudioTranscriptionSettings:
    provider: str
    model: str
    fallback_provider: str
    fallback_model: str
    max_file_bytes: int
    max_duration_seconds: int
    provider_max_bytes: int
    chunk_seconds: int
    timeout_seconds: int
    request_timeout_seconds: float
    compatible_base_url: str = ""
    compatible_api_key: str = field(default="", repr=False)
    openai_api_key: str = field(default="", repr=False)
    device: str = "cpu"
    compute_type: str = "int8"


@dataclass(frozen=True)
class AudioTranscriptionLimits:
    max_file_bytes: int
    max_duration_seconds: int


@dataclass(frozen=True)
class AudioTranscriptionResult:
    transcript: str
    info: AudioInfo
    provider_requested: str
    provider: str
    model: str
    fallback_used: bool
    fallback_reason: str | None
    chunk_count: int


class PartialAudioTranscriptionError(STTProviderError):
    """A provider/deadline failure after one or more chunks completed."""

    def __init__(
        self,
        message: str,
        *,
        partial_transcript: str,
        completed_chunks: int,
        total_chunks: int,
    ) -> None:
        super().__init__(message, retryable=False)
        self.partial_transcript = partial_transcript
        self.completed_chunks = completed_chunks
        self.total_chunks = total_chunks


class _Deadline:
    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = float(timeout_seconds)
        self.ends_at = time.monotonic() + self.timeout_seconds

    def remaining(self) -> float:
        remaining = self.ends_at - time.monotonic()
        if remaining <= 0:
            raise STTProviderError(
                "Audio transcription exceeded its configured overall deadline",
                retryable=False,
            )
        return remaining

    def bounded_timeout(self, maximum: float) -> float:
        return max(0.05, min(float(maximum), self.remaining()))


@contextmanager
def _deadline_alarm(deadline: _Deadline):
    """Enforce the batch deadline even during local model inference on Linux."""

    can_alarm = (
        threading.current_thread() is threading.main_thread()
        and hasattr(signal, "SIGALRM")
        and hasattr(signal, "setitimer")
    )
    if not can_alarm:
        yield
        return

    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    if previous_timer[0] > 0:
        # Do not replace a caller-owned timer. Individual subprocess/HTTP
        # operations still consume the same monotonic deadline.
        yield
        return
    previous_handler = signal.getsignal(signal.SIGALRM)

    def _expired(_signum, _frame):
        raise STTProviderError(
            "Audio transcription exceeded its configured overall deadline",
            retryable=False,
        )

    signal.signal(signal.SIGALRM, _expired)
    signal.setitimer(signal.ITIMER_REAL, deadline.remaining())
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = str(get_config_value(name, "") or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _config_text(name: str, default: str = "") -> str:
    return str(get_config_value(name, default) or "").strip()


def _normalized_provider(value: str, name: str) -> str:
    try:
        return normalize_stt_provider(value)
    except ValueError as exc:
        raise ValueError(
            f"Unsupported {name} '{value}'. Expected one of: "
            "faster-whisper, openai, openai-compatible"
        ) from exc


def _positive_float(name: str, raw: object, default: float) -> float:
    value = str(raw or "").strip()
    if not value:
        return float(default)
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be a positive number")
    return parsed


def load_audio_transcription_limits() -> AudioTranscriptionLimits:
    """Resolve the one bounded size/duration policy used by upload and tool."""

    return AudioTranscriptionLimits(
        max_file_bytes=_bounded_int(
            "AUDIO_TRANSCRIBE_MAX_FILE_MB", DEFAULT_MAX_FILE_MB, 1, 5000
        )
        * 1024
        * 1024,
        max_duration_seconds=_bounded_int(
            "AUDIO_TRANSCRIBE_MAX_DURATION_SECONDS",
            DEFAULT_MAX_DURATION_SECONDS,
            30,
            86400,
        ),
    )


def load_audio_transcription_settings() -> AudioTranscriptionSettings:
    """Resolve batch transcription policy without inheriting STT fallback."""

    mode = get_active_config_mode()
    default_provider = "openai" if mode == "cloud" else "faster-whisper"
    stt_provider = _normalized_provider(
        _config_text("STT_PROVIDER", default_provider) or default_provider,
        "STT_PROVIDER",
    )
    configured_provider = _config_text("AUDIO_TRANSCRIBE_PROVIDER")
    provider = _normalized_provider(
        configured_provider or stt_provider,
        "AUDIO_TRANSCRIBE_PROVIDER",
    )

    configured_model = _config_text("AUDIO_TRANSCRIBE_MODEL")
    inherited_model = _config_text("STT_MODEL") if provider == stt_provider else ""
    model = configured_model or inherited_model or default_model_for_provider(provider)

    fallback_provider = _config_text("AUDIO_TRANSCRIBE_FALLBACK_PROVIDER").lower()
    if fallback_provider:
        fallback_provider = _normalized_provider(
            fallback_provider, "AUDIO_TRANSCRIBE_FALLBACK_PROVIDER"
        )
        if fallback_provider == provider:
            raise ValueError(
                "AUDIO_TRANSCRIBE_FALLBACK_PROVIDER must differ from "
                "AUDIO_TRANSCRIBE_PROVIDER"
            )
    fallback_model = _config_text("AUDIO_TRANSCRIBE_FALLBACK_MODEL")
    if fallback_provider and not fallback_model:
        fallback_model = default_model_for_provider(fallback_provider)

    timeout_seconds = _bounded_int(
        "AUDIO_TRANSCRIBE_TIMEOUT_SECONDS",
        DEFAULT_TIMEOUT_SECONDS,
        30,
        7200,
    )
    request_timeout = min(
        float(timeout_seconds),
        _positive_float(
            "AUDIO_TRANSCRIBE_REQUEST_TIMEOUT_SECONDS",
            get_config_value("AUDIO_TRANSCRIBE_REQUEST_TIMEOUT_SECONDS", ""),
            float(min(DEFAULT_REQUEST_TIMEOUT_SECONDS, timeout_seconds)),
        ),
    )

    configured_base_url = _config_text("AUDIO_TRANSCRIBE_BASE_URL")
    configured_api_key = _config_text("AUDIO_TRANSCRIBE_API_KEY")
    if configured_api_key and not configured_base_url:
        raise ValueError(
            "AUDIO_TRANSCRIBE_API_KEY requires AUDIO_TRANSCRIBE_BASE_URL so "
            "credentials cannot be paired with an inherited endpoint"
        )
    if configured_base_url:
        compatible_base_url = configured_base_url
        compatible_api_key = configured_api_key
    else:
        compatible_base_url = _config_text("STT_BASE_URL")
        compatible_api_key = _config_text("STT_API_KEY")

    limits = load_audio_transcription_limits()

    return AudioTranscriptionSettings(
        provider=provider,
        model=model,
        fallback_provider=fallback_provider,
        fallback_model=fallback_model,
        max_file_bytes=limits.max_file_bytes,
        max_duration_seconds=limits.max_duration_seconds,
        provider_max_bytes=_bounded_int(
            "AUDIO_TRANSCRIBE_PROVIDER_MAX_MB",
            DEFAULT_PROVIDER_MAX_MB,
            1,
            1000,
        )
        * 1024
        * 1024,
        chunk_seconds=_bounded_int(
            "AUDIO_TRANSCRIBE_CHUNK_SECONDS",
            DEFAULT_CHUNK_SECONDS,
            30,
            3600,
        ),
        timeout_seconds=timeout_seconds,
        request_timeout_seconds=request_timeout,
        compatible_base_url=compatible_base_url,
        compatible_api_key=compatible_api_key,
        openai_api_key=_config_text("OPENAI_API_KEY"),
        device=_config_text("AUDIO_TRANSCRIBE_DEVICE")
        or _config_text("STT_DEVICE", "cpu")
        or "cpu",
        compute_type=_config_text("AUDIO_TRANSCRIBE_COMPUTE_TYPE")
        or _config_text("STT_COMPUTE_TYPE", "int8")
        or "int8",
    )


def inspect_audio_file(
    audio_path: str | Path,
    *,
    max_file_bytes: int,
    max_duration_seconds: int,
    deadline: _Deadline | None = None,
) -> AudioInfo:
    """Validate a bounded audio container with ffprobe before provider work."""

    path = Path(audio_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"Audio file does not exist: {path}")
    if path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_AUDIO_EXTENSIONS))
        raise ValueError(f"Unsupported audio format. Expected one of: {supported}")

    size_bytes = path.stat().st_size
    if size_bytes < 1:
        raise ValueError("Audio file is empty")
    if size_bytes > max_file_bytes:
        raise ValueError(
            f"Audio file exceeds the {max_file_bytes // (1024 * 1024)}MB limit"
        )
    if not shutil.which("ffprobe"):
        raise ValueError("ffprobe is required for audio transcription")

    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_type:format=duration,format_name",
        "-of",
        "default=noprint_wrappers=1",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=deadline.bounded_timeout(30) if deadline else 30,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Audio inspection timed out") from exc
    if completed.returncode != 0:
        raise ValueError("The selected file is not a readable audio file")

    values: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip()] = value.strip()
    if values.get("codec_type") != "audio":
        raise ValueError("The selected file does not contain an audio stream")
    try:
        duration_seconds = float(values.get("duration", ""))
    except ValueError as exc:
        raise ValueError("Audio duration could not be determined") from exc
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise ValueError("Audio duration could not be determined")
    if duration_seconds > max_duration_seconds:
        raise ValueError(
            "Audio duration exceeds the "
            f"{max_duration_seconds // 60}-minute transcription limit"
        )

    return AudioInfo(
        path=path,
        filename=path.name,
        size_bytes=size_bytes,
        duration_seconds=duration_seconds,
        format_name=values.get("format_name", ""),
    )


def _remote_endpoint(
    provider: str, settings: AudioTranscriptionSettings
) -> tuple[str, str]:
    if provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not configured")
        return "https://api.openai.com/v1", settings.openai_api_key

    if not settings.compatible_base_url:
        raise ValueError(
            "AUDIO_TRANSCRIBE_BASE_URL or STT_BASE_URL is required for "
            "openai-compatible transcription"
        )
    return settings.compatible_base_url, settings.compatible_api_key


class _FasterWhisperTranscriber:
    """Load Faster-Whisper once for the complete tool invocation."""

    def __init__(self, model_name: str, *, device: str, compute_type: str):
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:
            raise ValueError("faster-whisper is not installed") from exc

        try:
            self.model = WhisperModel(
                model_name,
                device=device,
                compute_type=compute_type,
            )
        except Exception as exc:
            raise STTProviderError(
                f"faster-whisper model initialization failed: {exc}",
                retryable=False,
            ) from exc

    def transcribe(self, path: Path) -> str:
        try:
            segments, _ = self.model.transcribe(
                str(path),
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300},
            )
            return "".join(segment.text for segment in segments).strip()
        except STTProviderError:
            raise
        except Exception as exc:
            raise STTProviderError(
                f"faster-whisper failed: {exc}", retryable=False
            ) from exc


def _silence_points(
    path: Path, *, timeout_seconds: int, deadline: _Deadline | None = None
) -> list[float]:
    """Return silence end points; failure simply falls back to fixed boundaries."""

    if not shutil.which("ffmpeg"):
        return []
    try:
        completed = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "info",
                "-i",
                str(path),
                "-af",
                "silencedetect=noise=-35dB:d=0.4",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=(
                deadline.bounded_timeout(max(30, min(timeout_seconds, 300)))
                if deadline
                else max(30, min(timeout_seconds, 300))
            ),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [float(match) for match in _SILENCE_END_RE.findall(completed.stderr)]


def _chunk_ranges(
    duration_seconds: float,
    target_seconds: int,
    silence_points: list[float],
) -> list[tuple[float, float]]:
    if duration_seconds <= target_seconds:
        return [(0.0, duration_seconds)]

    boundaries = [0.0]
    target = float(target_seconds)
    while target < duration_seconds:
        lower = max(boundaries[-1] + 30.0, target - 30.0)
        # Snap only backward so a silence boundary can never make the rendered
        # PCM chunk exceed the size-derived target.
        upper = min(duration_seconds - 1.0, target)
        nearby = [point for point in silence_points if lower <= point <= upper]
        boundary = min(nearby, key=lambda point: abs(point - target)) if nearby else target
        if boundary <= boundaries[-1]:
            boundary = min(duration_seconds, boundaries[-1] + target_seconds)
        boundaries.append(boundary)
        target = boundary + target_seconds
    boundaries.append(duration_seconds)
    return [
        (start, end - start)
        for start, end in zip(boundaries, boundaries[1:])
        if end - start > 0.01
    ]


def _render_wav_chunk(
    source: Path,
    output: Path,
    start: float,
    duration: float,
    *,
    timeout_seconds: float | None = None,
) -> None:
    if not shutil.which("ffmpeg"):
        raise ValueError("ffmpeg is required to prepare audio for remote transcription")
    try:
        completed = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-ss",
                f"{start:.3f}",
                "-i",
                str(source),
                "-t",
                f"{duration:.3f}",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(output),
            ],
            capture_output=True,
            text=True,
            timeout=(
                timeout_seconds
                if timeout_seconds is not None
                else max(60, min(600, int(duration) + 60))
            ),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise STTProviderError("Audio chunk preparation timed out", retryable=False) from exc
    if completed.returncode != 0 or not output.is_file():
        raise STTProviderError("Audio chunk preparation failed", retryable=False)


def _transcribe_remote(
    info: AudioInfo,
    *,
    provider: str,
    model: str,
    settings: AudioTranscriptionSettings,
    deadline: _Deadline,
) -> tuple[str, int]:
    base_url, api_key = _remote_endpoint(provider, settings)
    size_safe_seconds = max(
        30,
        int((settings.provider_max_bytes * 0.80) / _PCM_BYTES_PER_SECOND),
    )
    target_seconds = min(settings.chunk_seconds, size_safe_seconds)
    silence_points = (
        _silence_points(
            info.path,
            timeout_seconds=settings.timeout_seconds,
            deadline=deadline,
        )
        if info.duration_seconds > target_seconds
        else []
    )
    ranges = _chunk_ranges(info.duration_seconds, target_seconds, silence_points)
    transcripts: list[str] = []
    nonempty_chunks = 0
    with tempfile.TemporaryDirectory(prefix="jarvis-audio-transcribe-") as temp_dir:
        for index, (start, duration) in enumerate(ranges, start=1):
            chunk = Path(temp_dir) / f"chunk_{index:04d}.wav"
            try:
                deadline.remaining()
                render_timeout = max(60, min(600, int(duration) + 60))
                _render_wav_chunk(
                    info.path,
                    chunk,
                    start,
                    duration,
                    timeout_seconds=deadline.bounded_timeout(render_timeout),
                )
                if chunk.stat().st_size > settings.provider_max_bytes:
                    raise STTProviderError(
                        "Prepared audio chunk exceeds the configured provider upload limit",
                        retryable=False,
                    )
                text = transcribe_openai_compatible(
                    str(chunk),
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    timeout=deadline.bounded_timeout(
                        settings.request_timeout_seconds
                    ),
                )
                if text:
                    transcripts.append(text)
                    nonempty_chunks += 1
                else:
                    transcripts.append(
                        f"[No speech detected in audio chunk {index} of {len(ranges)}.]"
                    )
            except STTProviderError as exc:
                if transcripts:
                    raise PartialAudioTranscriptionError(
                        str(exc),
                        partial_transcript="\n\n".join(transcripts).strip(),
                        completed_chunks=len(transcripts),
                        total_chunks=len(ranges),
                    ) from exc
                raise
            finally:
                chunk.unlink(missing_ok=True)
    if nonempty_chunks == 0:
        raise STTProviderError("No speech detected in the audio file", retryable=False)
    return "\n\n".join(transcripts).strip(), len(ranges)


def transcribe_audio_file(
    audio_path: str | Path,
    *,
    settings: AudioTranscriptionSettings | None = None,
) -> AudioTranscriptionResult:
    """Transcribe one existing audio file using batch-specific policy."""

    settings = settings or load_audio_transcription_settings()
    deadline = _Deadline(settings.timeout_seconds)
    with _deadline_alarm(deadline):
        info = inspect_audio_file(
            audio_path,
            max_file_bytes=settings.max_file_bytes,
            max_duration_seconds=settings.max_duration_seconds,
            deadline=deadline,
        )
        selected_provider = settings.provider
        fallback_reason: str | None = None

        def transcribe(provider: str) -> tuple[str, int, str]:
            deadline.remaining()
            model = settings.model
            if provider != settings.provider:
                model = settings.fallback_model or default_model_for_provider(provider)
            if provider == "faster-whisper":
                local = _FasterWhisperTranscriber(
                    model,
                    device=settings.device,
                    compute_type=settings.compute_type,
                )
                return local.transcribe(info.path), 1, model
            transcript, chunk_count = _transcribe_remote(
                info,
                provider=provider,
                model=model,
                settings=settings,
                deadline=deadline,
            )
            return transcript, chunk_count, model

        def on_fallback(primary: str, fallback: str, error: STTProviderError) -> None:
            nonlocal selected_provider, fallback_reason
            selected_provider = fallback
            fallback_reason = str(error)

        transcript, chunk_count, used_model = run_with_stt_fallback(
            settings.provider,
            settings.fallback_provider,
            transcribe,
            on_fallback=on_fallback,
        )
    return AudioTranscriptionResult(
        transcript=transcript,
        info=info,
        provider_requested=settings.provider,
        provider=selected_provider,
        model=used_model,
        fallback_used=selected_provider != settings.provider,
        fallback_reason=fallback_reason,
        chunk_count=chunk_count,
    )
