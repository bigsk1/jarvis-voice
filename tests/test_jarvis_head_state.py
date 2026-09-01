"""Phase 3 tests for the Jarvis Head base-plus-speech state machine."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HEAD_ROOT = PROJECT_ROOT / "jarvis-head"
sys.path.insert(0, str(HEAD_ROOT))

from head_protocol import EventType, HeadEvent, parse_event  # noqa: E402
from head_state import BaseState, HeadStateMachine  # noqa: E402
from visemes import MouthShape, VisemeTimeline  # noqa: E402

from lib.head_events import MAX_DATAGRAM_BYTES  # noqa: E402

TIMELINE = VisemeTimeline(
    duration=2.0,
    frame_seconds=0.5,
    shapes=(MouthShape.AE, MouthShape.ROUND, MouthShape.CLOSED, MouthShape.REST),
)


def _machine(*, idle_timeout: float = 120.0) -> HeadStateMachine:
    return HeadStateMachine(idle_timeout=idle_timeout, wav_loader=lambda _path: TIMELINE)


def _simple(event_type: EventType) -> HeadEvent:
    return HeadEvent(event_type)


def _speak(playback_id: str, t0: float, wav: str = "speech.wav") -> HeadEvent:
    return HeadEvent(EventType.SPEAK, playback_id=playback_id, wav=wav, t0=t0)


def _end(playback_id: str, ok: bool = True) -> HeadEvent:
    return HeadEvent(EventType.SPEAK_END, playback_id=playback_id, ok=ok)


def test_speech_from_sleep_shows_face_then_returns_to_rain_on_duration_failsafe():
    state = _machine()
    assert state.base_state is BaseState.SLEEP
    assert state.face_visible is False

    assert state.handle(_speak("one", 100.0), now_wall=100.0, now_mono=5.0)
    assert state.face_visible is True
    assert state.mouth_shape(now_wall=100.1) is MouthShape.AE

    state.tick(now_wall=103.0, now_mono=8.0)
    assert state.active_playback_id is None
    assert state.face_visible is False


def test_speech_from_listen_returns_to_the_listening_face():
    state = _machine()
    assert state.handle(_simple(EventType.LISTEN), now_wall=99.0, now_mono=1.0)
    assert state.handle(_speak("one", 100.0), now_wall=100.0, now_mono=2.0)
    assert state.handle(_end("one"), now_wall=100.5, now_mono=2.5)

    assert state.base_state is BaseState.LISTEN
    assert state.face_visible is True
    assert state.mouth_shape(now_wall=100.5) is MouthShape.REST


def test_sleep_changes_base_without_cancelling_active_speech():
    state = _machine()
    state.handle(_simple(EventType.LISTEN), now_wall=99.0, now_mono=1.0)
    state.handle(_speak("one", 100.0), now_wall=100.0, now_mono=2.0)

    assert state.handle(_simple(EventType.SLEEP), now_wall=100.2, now_mono=2.2)
    assert state.base_state is BaseState.SLEEP
    assert state.active_playback_id == "one"
    assert state.face_visible is True

    assert state.handle(_end("one"), now_wall=100.5, now_mono=2.5)
    assert state.face_visible is False


def test_retry_switches_ids_and_ignores_stale_speak_and_end_events():
    state = _machine()
    assert state.handle(_speak("first", 100.0), now_wall=100.0, now_mono=1.0)
    assert state.handle(_speak("retry", 100.1), now_wall=100.1, now_mono=1.1)
    assert state.active_playback_id == "retry"

    assert not state.handle(_end("first", ok=False), now_wall=100.2, now_mono=1.2)
    assert not state.handle(_speak("late", 99.0), now_wall=100.2, now_mono=1.2)
    assert state.active_playback_id == "retry"
    assert state.handle(_end("retry"), now_wall=100.3, now_mono=1.3)

    # A delayed duplicate cannot resurrect an attempt that already ended.
    assert not state.handle(_speak("retry", 100.1), now_wall=100.4, now_mono=1.4)
    assert state.face_visible is False


def test_missing_and_non_wav_paths_are_ignored_without_changing_rain(tmp_path):
    state = HeadStateMachine()
    assert not state.handle(
        _speak("missing", 100.0, str(tmp_path / "missing.wav")),
        now_wall=100.0,
        now_mono=1.0,
    )
    invalid = tmp_path / "invalid.wav"
    invalid.write_text("not a wav", encoding="utf-8")
    assert not state.handle(
        _speak("invalid", 100.1, str(invalid)),
        now_wall=100.1,
        now_mono=1.1,
    )
    assert state.base_state is BaseState.SLEEP
    assert state.face_visible is False


def test_old_and_unreasonably_future_speech_is_rejected_before_wav_loading():
    loaded: list[str] = []
    state = HeadStateMachine(wav_loader=lambda path: loaded.append(str(path)) or TIMELINE)
    assert not state.handle(_speak("old", 100.0), now_wall=500.1, now_mono=1.0)
    assert not state.handle(_speak("future", 511.0), now_wall=500.0, now_mono=1.0)
    assert loaded == []


def test_idle_timeout_forces_listen_and_think_back_to_sleep():
    state = _machine(idle_timeout=10.0)
    state.handle(_simple(EventType.LISTEN), now_wall=100.0, now_mono=5.0)
    state.tick(now_wall=109.9, now_mono=14.9)
    assert state.base_state is BaseState.LISTEN
    state.tick(now_wall=110.0, now_mono=15.0)
    assert state.base_state is BaseState.SLEEP

    state.handle(_simple(EventType.THINK), now_wall=111.0, now_mono=16.0)
    state.tick(now_wall=121.0, now_mono=26.0)
    assert state.base_state is BaseState.SLEEP


def test_protocol_rejects_unknown_shapes_types_and_extra_fields():
    invalid_objects = (
        {},
        {"type": "unknown"},
        {"type": "listen", "extra": True},
        {"type": "speak", "playback_id": "id", "wav": "x.wav", "t0": True},
        {"type": "speak_end", "playback_id": "id", "ok": "true"},
        ["listen"],
    )
    for invalid in invalid_objects:
        assert parse_event(json.dumps(invalid).encode()) is None
    assert parse_event(b"\xff") is None
    assert parse_event(b"x" * (MAX_DATAGRAM_BYTES + 1)) is None


def test_protocol_accepts_each_documented_event_shape():
    datagrams = (
        {"type": "listen"},
        {"type": "think"},
        {"type": "sleep"},
        {"type": "speak", "playback_id": "id", "wav": "x.wav", "t0": 100.5},
        {"type": "speak_end", "playback_id": "id", "ok": False},
    )
    assert [parse_event(json.dumps(item).encode()).type for item in datagrams] == [
        EventType.LISTEN,
        EventType.THINK,
        EventType.SLEEP,
        EventType.SPEAK,
        EventType.SPEAK_END,
    ]
