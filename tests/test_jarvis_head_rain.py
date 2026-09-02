"""Phase 0 tests for the pure Jarvis Head rain model."""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

HEAD_ROOT = Path(__file__).resolve().parents[1] / "jarvis-head"
sys.path.insert(0, str(HEAD_ROOT))

from rain import KIOSK_PRESET, REFERENCE_PRESET, MatrixColumn, RainField, RainPreset  # noqa: E402


def _snapshot(field: RainField) -> tuple[tuple[int, int, str, int, bool], ...]:
    return tuple(
        (cell.x, cell.y, cell.char, cell.intensity, cell.is_lead) for cell in field.visible_cells()
    )


def test_kiosk_covers_every_column_while_reference_keeps_gutters():
    kiosk = RainField(12, 24, KIOSK_PRESET, seed=7)
    reference = RainField(12, 24, REFERENCE_PRESET, seed=7)

    assert kiosk.column_positions == tuple(range(24))
    assert reference.column_positions[:5] == (0, 2, 5, 9, 12)
    assert len(reference.column_positions) < len(kiosk.column_positions)


def test_fixed_seed_produces_repeatable_frames():
    first = RainField(10, 14, "kiosk", seed=42)
    second = RainField(10, 14, "kiosk", seed=42)

    assert _snapshot(first) == _snapshot(second)
    for dt in (0.02, 0.04, 0.07, 0.03, 0.08):
        first.update(dt)
        second.update(dt)
        assert _snapshot(first) == _snapshot(second)


def test_column_preserves_upstream_reset_cycle():
    preset = RainPreset(
        name="test",
        gap_pattern=(0,),
        column_length_range=(0.5, 0.5),
        fall_speed_range=(0.1, 0.1),
        change_chance=0,
        chars="AB",
    )
    column = MatrixColumn(
        height=4,
        preset=preset,
        rng=random.Random(3),
        randomize_phase=False,
    )

    assert column.length == 2
    assert column.top == -2
    for _ in range(column.height + column.length):
        column.update(0.11)
    assert column.top == -column.length


def test_resize_rebuilds_with_cells_inside_terminal_bounds():
    field = RainField(8, 11, "kiosk", seed=91)
    field.resize(5, 7)
    cells = tuple(field.visible_cells())

    assert field.column_positions == tuple(range(7))
    assert all(0 <= cell.x < 7 for cell in cells)
    assert all(0 <= cell.y < 5 for cell in cells)
    assert all(len(cell.char) == 1 for cell in cells)
    assert all(1 <= cell.intensity <= KIOSK_PRESET.intensity_levels for cell in cells)


def test_invalid_field_dimensions_and_negative_time_are_rejected():
    with pytest.raises(ValueError, match="positive"):
        RainField(0, 10)

    field = RainField(5, 5, seed=1)
    with pytest.raises(ValueError, match="negative"):
        field.update(-0.01)


@pytest.mark.parametrize("preset", (KIOSK_PRESET, REFERENCE_PRESET))
@pytest.mark.parametrize("seed", (1, 7, 42))
def test_visible_spans_reproduce_visible_cells_exactly(preset, seed):
    field = RainField(9, 11, preset, seed=seed)

    for _ in range(60):
        field.update(0.05)
        from_spans = set()
        for x, span in field.visible_spans():
            assert 0 <= span.y_start < span.y_end <= field.height
            assert len(span.chars) == len(span.intensities) == span.y_end - span.y_start
            for offset, (char, intensity) in enumerate(
                zip(span.chars, span.intensities, strict=True)
            ):
                y = span.y_start + offset
                from_spans.add((x, y, char, intensity, y == span.lead_y))
        assert from_spans == set(_snapshot(field))
