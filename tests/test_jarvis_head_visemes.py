"""Phase 2 tests for bounded Jarvis Head WAV analysis."""

from __future__ import annotations

import math
import sys
import wave
from array import array
from pathlib import Path

import pytest

HEAD_ROOT = Path(__file__).resolve().parents[1] / "jarvis-head"
sys.path.insert(0, str(HEAD_ROOT))

import visemes  # noqa: E402
from visemes import MouthShape, WavAnalysisError, analyze_wav  # noqa: E402


def _write_segmented_wav(path: Path, *, sample_rate: int = 16_000) -> Path:
    segments = (
        (0, 0.0),
        (2_500, 0.10),
        (2_500, 0.75),
        (220, 0.75),
        (0, 0.0),
    )
    samples = array("h")
    for frequency, amplitude in segments:
        for index in range(round(sample_rate * 0.3)):
            value = 0
            if frequency:
                value = round(
                    32_767 * amplitude * math.sin(2 * math.pi * frequency * index / sample_rate)
                )
            samples.append(value)

    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(samples.tobytes())
    return path


def test_wav_analysis_quantizes_all_four_apertures(tmp_path):
    timeline = analyze_wav(_write_segmented_wav(tmp_path / "speech.wav"))

    assert timeline.duration == pytest.approx(1.5)
    assert timeline.frame_seconds == pytest.approx(0.05)
    assert set(timeline.shapes) == set(MouthShape)
    assert timeline.shape_at(-0.1) is MouthShape.REST
    assert timeline.shape_at(0.4) is MouthShape.CLOSED
    assert timeline.shape_at(0.7) is MouthShape.AE
    assert timeline.shape_at(1.0) is MouthShape.ROUND
    assert timeline.shape_at(timeline.duration) is MouthShape.REST


def test_wav_analysis_keeps_relative_loudness_for_the_speech_pulse(tmp_path):
    timeline = analyze_wav(_write_segmented_wav(tmp_path / "speech.wav"))

    assert len(timeline.levels) == len(timeline.shapes)
    assert timeline.level_at(0.1) == 0.0  # leading silence
    assert timeline.level_at(-0.1) == 0.0 and timeline.level_at(timeline.duration) == 0.0
    quiet, loud = timeline.level_at(0.4), timeline.level_at(0.7)
    assert 0 < quiet < loud <= 1.0
    assert loud == pytest.approx(1.0)  # the loudest segment sets the scale
    assert quiet == pytest.approx(0.10 / 0.75, abs=0.02)


def test_timeline_levels_are_optional_but_must_align_and_stay_normalized():
    shapes = (MouthShape.AE, MouthShape.REST)
    unmeasured = visemes.VisemeTimeline(duration=0.1, frame_seconds=0.05, shapes=shapes)
    assert unmeasured.level_at(0.02) == 0.0
    with pytest.raises(ValueError, match="one per shape"):
        visemes.VisemeTimeline(duration=0.1, frame_seconds=0.05, shapes=shapes, levels=(1.0,))
    with pytest.raises(ValueError, match="0-1"):
        visemes.VisemeTimeline(duration=0.1, frame_seconds=0.05, shapes=shapes, levels=(1.2, 0.0))


def test_wav_analysis_rejects_non_wav_and_non_regular_paths(tmp_path):
    invalid = tmp_path / "not-wav.txt"
    invalid.write_text("not a wav", encoding="utf-8")

    with pytest.raises(WavAnalysisError, match="invalid PCM WAV"):
        analyze_wav(invalid)
    with pytest.raises(WavAnalysisError, match="regular file"):
        analyze_wav(tmp_path)


def test_wav_analysis_enforces_file_and_duration_bounds(tmp_path, monkeypatch):
    wav_path = _write_segmented_wav(tmp_path / "bounded.wav")

    monkeypatch.setattr(visemes, "MAX_WAV_BYTES", 10)
    with pytest.raises(WavAnalysisError, match="MiB demo limit"):
        analyze_wav(wav_path)

    monkeypatch.setattr(visemes, "MAX_WAV_BYTES", 64 * 1024 * 1024)
    monkeypatch.setattr(visemes, "MAX_WAV_SECONDS", 0.5)
    with pytest.raises(WavAnalysisError, match="second demo limit"):
        analyze_wav(wav_path)
