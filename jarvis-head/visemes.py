"""Bounded WAV analysis for the Jarvis Head four-aperture demo."""

from __future__ import annotations

import stat
import wave
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

MAX_WAV_BYTES = 64 * 1024 * 1024
MAX_WAV_SECONDS = 300.0
MIN_SAMPLE_RATE = 8_000
MAX_SAMPLE_RATE = 96_000
MAX_CHANNELS = 8
FRAME_SECONDS = 0.05
ABSOLUTE_SILENCE_RMS = 0.006
RELATIVE_SILENCE = 0.08
CLOSED_LEVEL = 0.24
ROUND_CENTROID_HZ = 900.0
ROUND_LOW_BAND_HZ = 1_000.0
ROUND_LOW_BAND_RATIO = 0.55


class WavAnalysisError(ValueError):
    """The supplied WAV cannot be safely used by the display demo."""


class MouthShape(StrEnum):
    REST = "rest"
    CLOSED = "closed"
    AE = "ae"
    ROUND = "o"


@dataclass(frozen=True, slots=True)
class VisemeTimeline:
    """Fixed-rate mouth shapes held entirely in memory after WAV parsing."""

    duration: float
    frame_seconds: float
    shapes: tuple[MouthShape, ...]

    def __post_init__(self) -> None:
        if self.duration <= 0 or self.frame_seconds <= 0 or not self.shapes:
            raise ValueError("timeline values must be positive and non-empty")

    def shape_at(self, elapsed: float) -> MouthShape:
        if elapsed < 0 or elapsed >= self.duration:
            return MouthShape.REST
        index = min(int(elapsed / self.frame_seconds), len(self.shapes) - 1)
        return self.shapes[index]


@dataclass(frozen=True, slots=True)
class _AudioFrame:
    rms: float
    centroid_hz: float
    low_band_ratio: float
    zero_crossing_rate: float


def analyze_wav(path: str | Path) -> VisemeTimeline:
    """Analyze a bounded PCM WAV without playing it or retaining audio samples."""

    wav_path = Path(path).expanduser()
    try:
        file_stat = wav_path.stat()
    except OSError as exc:
        raise WavAnalysisError(f"cannot read WAV {wav_path}: {exc.strerror or exc}") from exc
    if not stat.S_ISREG(file_stat.st_mode):
        raise WavAnalysisError(f"WAV path is not a regular file: {wav_path}")
    if file_stat.st_size <= 0:
        raise WavAnalysisError(f"WAV is empty: {wav_path}")
    if file_stat.st_size > MAX_WAV_BYTES:
        raise WavAnalysisError(
            f"WAV exceeds the {MAX_WAV_BYTES // (1024 * 1024)} MiB demo limit: {wav_path}"
        )

    try:
        with wave.open(str(wav_path), "rb") as wav_file:
            timeline = _analyze_pcm_wav(wav_file, wav_path)
    except (EOFError, wave.Error) as exc:
        raise WavAnalysisError(f"invalid PCM WAV {wav_path}: {exc}") from exc
    return timeline


def _analyze_pcm_wav(wav_file: wave.Wave_read, path: Path) -> VisemeTimeline:
    channels = wav_file.getnchannels()
    sample_width = wav_file.getsampwidth()
    sample_rate = wav_file.getframerate()
    declared_frames = wav_file.getnframes()

    if wav_file.getcomptype() != "NONE":
        raise WavAnalysisError(f"compressed WAV is not supported: {path}")
    if not 1 <= channels <= MAX_CHANNELS:
        raise WavAnalysisError(f"WAV channel count must be 1-{MAX_CHANNELS}: {path}")
    if sample_width not in (1, 2, 3, 4):
        raise WavAnalysisError(f"WAV sample width must be 8, 16, 24, or 32 bit: {path}")
    if not MIN_SAMPLE_RATE <= sample_rate <= MAX_SAMPLE_RATE:
        raise WavAnalysisError(
            f"WAV sample rate must be {MIN_SAMPLE_RATE}-{MAX_SAMPLE_RATE} Hz: {path}"
        )
    if declared_frames < 1:
        raise WavAnalysisError(f"WAV contains no audio frames: {path}")

    declared_duration = declared_frames / sample_rate
    if declared_duration > MAX_WAV_SECONDS:
        raise WavAnalysisError(
            f"WAV exceeds the {int(MAX_WAV_SECONDS)} second demo limit: {path}"
        )

    frames_per_window = max(1, round(sample_rate * FRAME_SECONDS))
    audio_frames: list[_AudioFrame] = []
    frames_read = 0
    while frames_read < declared_frames:
        raw = wav_file.readframes(min(frames_per_window, declared_frames - frames_read))
        if not raw:
            break
        mono = _decode_pcm(raw, sample_width=sample_width, channels=channels)
        if mono.size == 0:
            break
        frames_read += mono.size
        audio_frames.append(_measure_frame(mono, sample_rate))

    if not audio_frames or frames_read < 1:
        raise WavAnalysisError(f"WAV contains no decodable audio frames: {path}")

    peak_rms = max(frame.rms for frame in audio_frames)
    silence_rms = max(ABSOLUTE_SILENCE_RMS, peak_rms * RELATIVE_SILENCE)
    shapes = tuple(
        _classify_frame(frame, peak_rms=peak_rms, silence_rms=silence_rms)
        for frame in audio_frames
    )
    shapes = _smooth_single_frame_changes(shapes)
    return VisemeTimeline(
        duration=frames_read / sample_rate,
        frame_seconds=frames_per_window / sample_rate,
        shapes=shapes,
    )


def _decode_pcm(raw: bytes, *, sample_width: int, channels: int) -> np.ndarray:
    import numpy as np

    frame_bytes = sample_width * channels
    complete_bytes = len(raw) - (len(raw) % frame_bytes)
    if complete_bytes <= 0:
        return np.empty(0, dtype=np.float32)
    raw = raw[:complete_bytes]

    if sample_width == 1:
        samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sample_width == 2:
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32_768.0
    elif sample_width == 3:
        packed = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        values = packed[:, 0] | (packed[:, 1] << 8) | (packed[:, 2] << 16)
        values = np.where(values & 0x80_0000, values - 0x100_0000, values)
        samples = values.astype(np.float32) / 8_388_608.0
    else:
        samples = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2_147_483_648.0

    return samples.reshape(-1, channels).mean(axis=1, dtype=np.float32)


def _measure_frame(mono: np.ndarray, sample_rate: int) -> _AudioFrame:
    import numpy as np

    rms = float(np.sqrt(np.mean(np.square(mono), dtype=np.float64)))
    if mono.size < 2 or rms == 0:
        return _AudioFrame(rms=rms, centroid_hz=0.0, low_band_ratio=1.0, zero_crossing_rate=0.0)

    windowed = mono * np.hanning(mono.size)
    spectrum = np.abs(np.fft.rfft(windowed))
    if spectrum.size:
        spectrum[0] = 0
    total = float(spectrum.sum())
    if total > 0:
        frequencies = np.fft.rfftfreq(mono.size, d=1.0 / sample_rate)
        centroid_hz = float(np.sum(frequencies * spectrum) / total)
        low_band_ratio = float(spectrum[frequencies <= ROUND_LOW_BAND_HZ].sum() / total)
    else:
        centroid_hz = 0.0
        low_band_ratio = 1.0
    zero_crossing_rate = float(np.mean(np.signbit(mono[:-1]) != np.signbit(mono[1:])))
    return _AudioFrame(
        rms=rms,
        centroid_hz=centroid_hz,
        low_band_ratio=low_band_ratio,
        zero_crossing_rate=zero_crossing_rate,
    )


def _classify_frame(
    frame: _AudioFrame,
    *,
    peak_rms: float,
    silence_rms: float,
) -> MouthShape:
    if frame.rms <= silence_rms or peak_rms <= ABSOLUTE_SILENCE_RMS:
        return MouthShape.REST

    relative_level = frame.rms / peak_rms
    if relative_level < CLOSED_LEVEL or (
        relative_level < 0.55 and frame.zero_crossing_rate > 0.28
    ):
        return MouthShape.CLOSED
    if (
        frame.centroid_hz <= ROUND_CENTROID_HZ
        and frame.low_band_ratio >= ROUND_LOW_BAND_RATIO
    ):
        return MouthShape.ROUND
    return MouthShape.AE


def _smooth_single_frame_changes(
    shapes: tuple[MouthShape, ...],
) -> tuple[MouthShape, ...]:
    if len(shapes) < 3:
        return shapes
    smoothed = list(shapes)
    for index in range(1, len(shapes) - 1):
        if shapes[index - 1] == shapes[index + 1] != shapes[index]:
            smoothed[index] = shapes[index - 1]
    return tuple(smoothed)
