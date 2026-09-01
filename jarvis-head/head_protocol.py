"""Bounded wire protocol for Jarvis Head datagram events."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from lib.head_events import MAX_DATAGRAM_BYTES

MAX_PLAYBACK_ID_CHARS = 128
MAX_WAV_PATH_CHARS = 4096


class EventType(StrEnum):
    LISTEN = "listen"
    THINK = "think"
    SPEAK = "speak"
    SPEAK_END = "speak_end"
    SLEEP = "sleep"


@dataclass(frozen=True, slots=True)
class HeadEvent:
    """One fully validated event from the local datagram socket."""

    type: EventType
    playback_id: str | None = None
    wav: str | None = None
    t0: float | None = None
    ok: bool | None = None


def parse_event(datagram: bytes) -> HeadEvent | None:
    """Return a typed event or None for malformed, unknown, or oversized input."""

    if not datagram or len(datagram) > MAX_DATAGRAM_BYTES:
        return None
    try:
        decoded = json.loads(datagram.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(decoded, dict):
        return None

    raw_type = decoded.get("type")
    try:
        event_type = EventType(raw_type)
    except (TypeError, ValueError):
        return None

    if event_type in {EventType.LISTEN, EventType.THINK, EventType.SLEEP}:
        if set(decoded) != {"type"}:
            return None
        return HeadEvent(event_type)

    if event_type is EventType.SPEAK:
        if set(decoded) != {"type", "playback_id", "wav", "t0"}:
            return None
        playback_id = _bounded_string(decoded["playback_id"], MAX_PLAYBACK_ID_CHARS)
        wav = _bounded_string(decoded["wav"], MAX_WAV_PATH_CHARS)
        t0 = _finite_number(decoded["t0"])
        if playback_id is None or wav is None or t0 is None or t0 <= 0:
            return None
        return HeadEvent(event_type, playback_id=playback_id, wav=wav, t0=t0)

    if set(decoded) != {"type", "playback_id", "ok"}:
        return None
    playback_id = _bounded_string(decoded["playback_id"], MAX_PLAYBACK_ID_CHARS)
    ok = decoded["ok"]
    if playback_id is None or not isinstance(ok, bool):
        return None
    return HeadEvent(event_type, playback_id=playback_id, ok=ok)


def _bounded_string(value: Any, limit: int) -> str | None:
    if not isinstance(value, str) or not value or len(value) > limit or "\x00" in value:
        return None
    return value


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    converted = float(value)
    return converted if math.isfinite(converted) else None
