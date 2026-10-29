"""Bounded window metadata for private Prompt Guard investigation evidence.

Diagnostics never participate in the verdict. Invalid optional metadata is
discarded without losing an otherwise valid classification or its evidence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

MAX_DIAGNOSTIC_WINDOWS = 128
_OFFSET_REASONS = (
    "tokenizer_did_not_provide_offsets",
    "offsets_do_not_match_request_text",
)


@dataclass(frozen=True, slots=True)
class PromptGuardWindow:
    """One scored region; offsets do not explain which words caused its score."""

    index: int
    content_token_start: int
    content_token_end: int
    injection_score: float
    char_start: int | None = None
    char_end: int | None = None


@dataclass(frozen=True, slots=True)
class PromptGuardDiagnostics:
    """Validated metadata only, without source text or arbitrary service fields."""

    winning_window_index: int
    windows: tuple[PromptGuardWindow, ...]
    offset_unit: Literal["unicode_code_points"] | None = None
    char_offset_reason: str | None = None
    version: Literal[1] = 1
    aggregation: Literal["max"] = "max"
    representation: Literal["raw_text_v1"] = "raw_text_v1"


def _fields(value: object) -> dict:
    if isinstance(value, PromptGuardDiagnostics):
        return {name: getattr(value, name) for name in (
            "version", "aggregation", "representation", "winning_window_index",
            "windows", "offset_unit", "char_offset_reason",
        )}
    if isinstance(value, PromptGuardWindow):
        return {name: getattr(value, name) for name in (
            "index", "content_token_start", "content_token_end", "injection_score",
            "char_start", "char_end",
        )}
    if isinstance(value, dict):
        return value
    raise ValueError("invalid_diagnostics")


def _score(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid_score")
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 1:
        raise ValueError("invalid_score")
    return number


def _window(value: object, *, index: int, text: str, token_limit: int,
            has_char_offsets: bool) -> PromptGuardWindow:
    raw = _fields(value)
    start, end = raw.get("content_token_start"), raw.get("content_token_end")
    if (type(raw.get("index")) is not int or raw["index"] != index
            or type(start) is not int or type(end) is not int
            or not 0 <= start < end <= token_limit):
        raise ValueError("invalid_token_interval")
    char_start, char_end = raw.get("char_start"), raw.get("char_end")
    if has_char_offsets:
        if (type(char_start) is not int or type(char_end) is not int
                or not 0 <= char_start < char_end <= len(text)):
            raise ValueError("invalid_character_interval")
    elif char_start is not None or char_end is not None:
        raise ValueError("unknown_offset_unit")
    return PromptGuardWindow(index, start, end, _score(raw.get("injection_score")),
                             char_start, char_end)


def _validate(value: object, *, text: str, windows_scanned: int,
              injection_score: float) -> PromptGuardDiagnostics:
    raw = _fields(value)
    windows = raw.get("windows")
    winner = raw.get("winning_window_index")
    if (type(raw.get("version")) is not int or raw["version"] != 1
            or raw.get("aggregation") != "max" or raw.get("representation") != "raw_text_v1"
            or type(windows_scanned) is not int or not 1 <= windows_scanned <= MAX_DIAGNOSTIC_WINDOWS
            or not isinstance(windows, (list, tuple)) or len(windows) != windows_scanned
            or type(winner) is not int or not 0 <= winner < windows_scanned):
        raise ValueError("invalid_diagnostics")
    unit, reason = raw.get("offset_unit"), raw.get("char_offset_reason")
    if (unit not in (None, "unicode_code_points")
            or (reason is not None and reason not in _OFFSET_REASONS)
            or (unit is not None and reason is not None)):
        raise ValueError("invalid_offset_metadata")
    if not isinstance(text, str) or not text:
        raise ValueError("invalid_text")
    # A generous byte-derived bound limits invented token positions without
    # importing a tokenizer or inferring character offsets from token counts.
    token_limit = len(text.encode("utf-8")) * 4
    parsed = tuple(_window(item, index=index, text=text, token_limit=token_limit,
                           has_char_offsets=unit is not None)
                   for index, item in enumerate(windows))
    if parsed[0].content_token_start != 0:
        raise ValueError("missing_first_window")
    for previous, current in zip(parsed, parsed[1:]):
        if (not previous.content_token_start < current.content_token_start <= previous.content_token_end
                or current.content_token_end <= previous.content_token_end):
            raise ValueError("invalid_window_order")
        if (unit is not None and (current.char_start < previous.char_start
                                 or current.char_end < previous.char_end)):
            raise ValueError("invalid_character_order")
    scores = [window.injection_score for window in parsed]
    if max(scores) != _score(injection_score) or winner != scores.index(max(scores)):
        raise ValueError("inconsistent_window_scores")
    return PromptGuardDiagnostics(winner, parsed, unit, reason)


def validate_diagnostics(value: object, *, text: str, windows_scanned: int,
                         injection_score: float) -> PromptGuardDiagnostics | None:
    """Keep bounded metadata tied to exact input; discard invalid optional data.

    Accepts wire objects and typed observations so incident persistence can
    revalidate the same contract against its exact quarantined text.
    """
    try:
        return _validate(value, text=text, windows_scanned=windows_scanned,
                         injection_score=injection_score)
    except (ValueError, TypeError, OverflowError, UnicodeError):
        return None
