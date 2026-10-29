"""Optional forensic metadata cannot weaken a confirmed scan verdict."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace

import pytest

from lib.prompt_guard_diagnostics import MAX_DIAGNOSTIC_WINDOWS, validate_diagnostics

TEXT = "🙂 Café e\u0301 status report: all systems operating normally."


def diagnostic():
    return {
        "version": 1, "aggregation": "max", "representation": "raw_text_v1",
        "winning_window_index": 1, "offset_unit": "unicode_code_points",
        "windows": [
            {"index": 0, "content_token_start": 0, "content_token_end": 10,
             "char_start": 0, "char_end": 25, "injection_score": 0.1},
            {"index": 1, "content_token_start": 8, "content_token_end": 20,
             "char_start": 15, "char_end": len(TEXT), "injection_score": 0.9},
        ],
    }


def validate(value, *, text=TEXT, count=2, score=0.9):
    return validate_diagnostics(value, text=text, windows_scanned=count, injection_score=score)


def test_preserves_code_point_offsets_and_only_reviewed_fields():
    raw = diagnostic()
    raw["extra"] = "private-service-secret"
    raw["windows"][1]["text"] = "<script>untrusted</script>"
    result = validate(raw)
    assert result is not None
    assert result.windows[1].char_end == len(TEXT) < len(TEXT.encode())
    assert TEXT[result.windows[0].char_start:result.windows[0].char_end].startswith("🙂 Café")
    assert "private-service-secret" not in repr(result) and "<script>" not in repr(result)
    with pytest.raises(FrozenInstanceError):
        result.windows[0].char_end = 100
    assert validate(result) == result


@pytest.mark.parametrize("reason", [None, "tokenizer_did_not_provide_offsets",
                                     "offsets_do_not_match_request_text"])
def test_token_only_diagnostics_never_invent_character_spans(reason):
    raw = diagnostic()
    raw["offset_unit"] = None
    raw["char_offset_reason"] = reason
    for window in raw["windows"]:
        del window["char_start"], window["char_end"]
    result = validate(raw)
    assert result is not None and result.offset_unit is None
    assert all(w.char_start is None and w.char_end is None for w in result.windows)
    assert result.char_offset_reason == reason


@pytest.mark.parametrize("changes", [
    {"version": True}, {"version": 2}, {"aggregation": "mean"},
    {"representation": "other"}, {"winning_window_index": True},
    {"winning_window_index": -1}, {"winning_window_index": 0}, {"winning_window_index": 2},
    {"offset_unit": "utf8_bytes"}, {"offset_unit": "utf16"},
    {"char_offset_reason": "<script>secret</script>"},
    {"char_offset_reason": "offsets_do_not_match_request_text"},
    {"windows": []}, {"windows": "untrusted"}, {"windows": None},
])
def test_invalid_envelopes_are_discarded(changes):
    assert validate({**diagnostic(), **changes}) is None


@pytest.mark.parametrize("changes", [
    {"index": True}, {"index": 0}, {"content_token_start": True},
    {"content_token_start": -1}, {"content_token_start": 0},
    {"content_token_start": 11}, {"content_token_start": 20},
    {"content_token_end": 10}, {"content_token_end": 1_000_000},
    {"char_start": True}, {"char_start": -1},
    {"char_end": len(TEXT.encode())}, {"char_end": 20},
    {"char_start": None}, {"char_end": None},
    {"injection_score": True}, {"injection_score": "0.9"},
    {"injection_score": float("nan")}, {"injection_score": float("inf")},
    {"injection_score": -0.1}, {"injection_score": 1.1}, {"injection_score": 0.8},
])
def test_bad_window_intervals_scores_and_order_are_discarded(changes):
    raw = diagnostic()
    raw["windows"][1].update(changes)
    assert validate(raw) is None


def test_incomplete_window_counts_and_unbounded_arrays_are_discarded():
    raw = diagnostic()
    assert validate(raw, count=True) is None
    assert validate(raw, count=1) is None
    raw["windows"] *= MAX_DIAGNOSTIC_WINDOWS
    assert validate(raw, count=len(raw["windows"])) is None


def test_configured_service_window_maximum_fits_the_validation_bound():
    raw = diagnostic()
    raw["winning_window_index"] = 0
    raw["offset_unit"] = None
    raw["windows"] = [
        {"index": index, "content_token_start": index, "content_token_end": index + 2,
         "injection_score": 0.9}
        for index in range(32)
    ]
    result = validate(raw, count=32)
    assert result is not None and len(result.windows) == 32


def test_character_intervals_cannot_move_backwards():
    raw = diagnostic()
    raw["windows"][0]["char_start"] = 5
    raw["windows"][1]["char_start"] = 4
    assert validate(raw) is None


def test_winner_ties_use_first_index():
    raw = diagnostic()
    raw["windows"][0]["injection_score"] = 0.9
    assert validate(raw) is None
    raw["winning_window_index"] = 0
    assert validate(raw) is not None


def test_missing_unknown_objects_and_mismatched_text_are_discarded():
    for value in (None, [], {}, "untrusted"):
        assert validate(value) is None
    assert validate(diagnostic(), text="short") is None
    assert validate(diagnostic(), text="") is None
    raw = diagnostic()
    raw["windows"][0]["content_token_start"] = 1
    assert validate(raw) is None


def test_typed_observations_are_revalidated_at_persistence_boundary():
    parsed = validate(diagnostic())
    assert parsed is not None
    malformed = replace(parsed, windows=(parsed.windows[0], replace(parsed.windows[1], char_end=9999)))
    assert validate(malformed) is None
    assert validate(replace(parsed, winning_window_index=True)) is None
    assert validate(parsed, score=0.8) is None


def test_unknown_units_cannot_relabel_character_offsets_as_token_only():
    raw = deepcopy(diagnostic())
    raw["offset_unit"] = None
    assert validate(raw) is None
