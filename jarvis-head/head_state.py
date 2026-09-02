"""Base-state plus speech-overlay model for the Jarvis Head display."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable

from head_protocol import EventType, HeadEvent
from visemes import MAX_WAV_SECONDS, MouthShape, VisemeTimeline, WavAnalysisError, analyze_wav

DEFAULT_IDLE_TIMEOUT = 120.0
SPEECH_END_SLACK = 1.0
MAX_FUTURE_START = 10.0


class BaseState(StrEnum):
    SLEEP = "sleep"
    LISTEN = "listen"
    THINK = "think"


@dataclass(frozen=True, slots=True)
class SpeechOverlay:
    playback_id: str
    t0: float
    timeline: VisemeTimeline

    @property
    def deadline(self) -> float:
        return self.t0 + self.timeline.duration + SPEECH_END_SLACK


class HeadStateMachine:
    """Deterministic event state whose only external work is bounded WAV loading."""

    def __init__(
        self,
        *,
        idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
        wav_loader: Callable[[str | Path], VisemeTimeline] = analyze_wav,
    ) -> None:
        if idle_timeout <= 0:
            raise ValueError("idle timeout must be positive")
        self.idle_timeout = idle_timeout
        self.wav_loader = wav_loader
        self.base_state = BaseState.SLEEP
        self.speech_overlay: SpeechOverlay | None = None
        self._last_activity: float | None = None
        self._latest_speak_t0: float | None = None

    @property
    def face_visible(self) -> bool:
        return self.base_state is not BaseState.SLEEP or self.speech_overlay is not None

    @property
    def active_playback_id(self) -> str | None:
        if self.speech_overlay is None:
            return None
        return self.speech_overlay.playback_id

    def handle(
        self,
        event: HeadEvent,
        *,
        now_wall: float | None = None,
        now_mono: float | None = None,
    ) -> bool:
        """Apply one validated event; False means it was stale or unusable."""

        wall = time.time() if now_wall is None else now_wall
        monotonic = time.monotonic() if now_mono is None else now_mono

        if event.type is EventType.LISTEN:
            self.base_state = BaseState.LISTEN
        elif event.type is EventType.THINK:
            self.base_state = BaseState.THINK
        elif event.type is EventType.SLEEP:
            self.base_state = BaseState.SLEEP
        elif event.type is EventType.SPEAK:
            if not self._start_speech(event, now_wall=wall):
                return False
        elif event.type is EventType.SPEAK_END:
            if self.speech_overlay is None:
                return False
            if event.playback_id != self.speech_overlay.playback_id:
                return False
            self.speech_overlay = None
        else:  # pragma: no cover - EventType is exhaustive
            return False

        self._last_activity = monotonic
        return True

    def tick(
        self,
        *,
        now_wall: float | None = None,
        now_mono: float | None = None,
    ) -> None:
        wall = time.time() if now_wall is None else now_wall
        monotonic = time.monotonic() if now_mono is None else now_mono
        if self.speech_overlay is not None and wall >= self.speech_overlay.deadline:
            self.speech_overlay = None
        if (
            self.base_state is not BaseState.SLEEP
            and self._last_activity is not None
            and monotonic - self._last_activity >= self.idle_timeout
        ):
            self.base_state = BaseState.SLEEP

    def mouth_shape(self, *, now_wall: float | None = None) -> MouthShape:
        if self.speech_overlay is None:
            return MouthShape.REST
        wall = time.time() if now_wall is None else now_wall
        return self.speech_overlay.timeline.shape_at(wall - self.speech_overlay.t0)

    def mouth_energy(self, *, now_wall: float | None = None) -> float:
        """Loudness 0-1 of the active speech overlay at ``now_wall``; 0 when silent."""

        if self.speech_overlay is None:
            return 0.0
        wall = time.time() if now_wall is None else now_wall
        return self.speech_overlay.timeline.level_at(wall - self.speech_overlay.t0)

    def _start_speech(self, event: HeadEvent, *, now_wall: float) -> bool:
        if event.playback_id is None or event.wav is None or event.t0 is None:
            return False
        if self._latest_speak_t0 is not None:
            if event.t0 < self._latest_speak_t0:
                return False
            if event.t0 == self._latest_speak_t0:
                return self.active_playback_id == event.playback_id
        if now_wall - event.t0 > MAX_WAV_SECONDS + SPEECH_END_SLACK:
            return False
        if event.t0 - now_wall > MAX_FUTURE_START:
            return False

        try:
            timeline = self.wav_loader(event.wav)
        except WavAnalysisError:
            return False
        if now_wall >= event.t0 + timeline.duration + SPEECH_END_SLACK:
            return False

        self.speech_overlay = SpeechOverlay(event.playback_id, event.t0, timeline)
        self._latest_speak_t0 = event.t0
        return True
