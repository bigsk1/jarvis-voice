"""Phase 1 tests for the dynamic Jarvis Head face glyph layer."""

from __future__ import annotations

import sys
from itertools import groupby
from pathlib import Path

import pytest
from PIL import Image

HEAD_ROOT = Path(__file__).resolve().parents[1] / "jarvis-head"
sys.path.insert(0, str(HEAD_ROOT))

from app import (  # noqa: E402
    DemoTimelinePlayer,
    FaceGlyphLayer,
    FaceVisibilityTransition,
    IdleFaceMotion,
    RainPalette,
)
from mask import SemanticFaceMasks, SemanticMask  # noqa: E402
from visemes import MouthShape, VisemeTimeline  # noqa: E402


def _fitted_test_mask():
    image = Image.new("L", (5, 3), color=100)
    image.putpixel((2, 1), 0)
    return SemanticMask(image).fit(3, 5, cell_aspect=1.0, scale=1.0)


def _snapshot(layer: FaceGlyphLayer) -> tuple[tuple[int, int, int, str], ...]:
    return tuple((cell.x, cell.y, cell.value, cell.char) for cell in layer.cells)


def test_face_glyphs_change_scatter_without_moving_the_mask():
    layer = FaceGlyphLayer(
        _fitted_test_mask(),
        seed=7,
        tick_interval=0.1,
        change_chance=1.0,
    )
    before = _snapshot(layer)

    layer.update(0.09)
    assert _snapshot(layer) == before

    layer.update(0.02)
    after = _snapshot(layer)

    assert [(x, y, value) for x, y, value, _char in after] == [
        (x, y, value) for x, y, value, _char in before
    ]
    for previous, current in zip(before, after, strict=True):
        if previous[2] == 0:
            assert current[3] == " "
        else:
            assert current[3] != previous[3]


def test_fixed_seed_keeps_face_animation_repeatable():
    first = FaceGlyphLayer(_fitted_test_mask(), seed=42)
    second = FaceGlyphLayer(_fitted_test_mask(), seed=42)

    for dt in (0.04, 0.07, 0.2, 0.11):
        first.update(dt)
        second.update(dt)
        assert _snapshot(first) == _snapshot(second)


def test_face_coalesces_and_dissipates_in_a_repeatable_scatter():
    first = FaceGlyphLayer(_fitted_test_mask(), seed=42)
    second = FaceGlyphLayer(_fitted_test_mask(), seed=42)

    assert tuple(first.visible_cells(0.0)) == ()
    halfway = tuple(first.visible_cells(0.5))
    assert 0 < len(halfway) < len(first.cells)
    assert [(cell.x, cell.y) for cell in halfway] == [
        (cell.x, cell.y) for cell in second.visible_cells(0.5)
    ]
    assert tuple(first.visible_cells(1.0)) == tuple(first.cells)

    with pytest.raises(ValueError, match="between"):
        tuple(first.visible_cells(-0.01))


def test_invalid_face_animation_values_are_rejected():
    fitted = _fitted_test_mask()

    with pytest.raises(ValueError, match="positive"):
        FaceGlyphLayer(fitted, seed=1, tick_interval=0)
    with pytest.raises(ValueError, match="between"):
        FaceGlyphLayer(fitted, seed=1, change_chance=1.1)
    with pytest.raises(ValueError, match="negative"):
        FaceGlyphLayer(fitted, seed=1).update(-0.01)


def test_face_palette_keeps_even_the_brightest_mask_cells_green():
    palette = object.__new__(RainPalette)
    palette.levels = (10, 20, 30)
    palette.lead = 99

    assert [palette.attribute_for_mask(value) for value in (40, 120, 200, 255)] == [
        10,
        20,
        30,
        30,
    ]


def test_expression_swaps_preserve_glyphs_outside_changed_regions():
    masks = SemanticFaceMasks.from_directory(HEAD_ROOT / "assets").fit(50, 200)
    resting = masks.get(blinking=False, mouth="rest")
    speaking = masks.get(blinking=True, mouth="ae")
    layer = FaceGlyphLayer(resting, seed=42)
    before = {(cell.x, cell.y): cell.char for cell in layer.cells}

    layer.apply_mask(speaking)

    for original, target, changed in zip(
        resting.cells,
        speaking.cells,
        layer.cells,
        strict=True,
    ):
        assert (original.x, original.y) == (changed.x, changed.y)
        if original.value == target.value:
            assert changed.char == before[(changed.x, changed.y)]


def test_idle_motion_is_repeatable_and_remains_inside_two_cell_bounds():
    first = IdleFaceMotion(
        fps=20,
        seed=9,
        blink_interval=(0.1, 0.1),
        drift_target_interval=(0.1, 0.1),
        drift_step_interval=0.05,
    )
    second = IdleFaceMotion(
        fps=20,
        seed=9,
        blink_interval=(0.1, 0.1),
        drift_target_interval=(0.1, 0.1),
        drift_step_interval=0.05,
    )
    snapshots = []

    for _ in range(40):
        first.update(0.05)
        second.update(0.05)
        snapshot = (first.blinking, first.offset)
        snapshots.append(snapshot)
        assert snapshot == (second.blinking, second.offset)

    assert any(blinking for blinking, _offset in snapshots)
    assert all(abs(offset[0]) <= 2 and abs(offset[1]) <= 1 for _blink, offset in snapshots)
    blink_runs = [
        len(tuple(group))
        for blinking, group in groupby(state[0] for state in snapshots)
        if blinking
    ]
    assert blink_runs
    assert all(length in (2, 3) for length in blink_runs)


def test_default_idle_drift_waits_at_least_three_seconds_before_repositioning():
    motion = IdleFaceMotion(fps=20, seed=9)

    motion.update(2.99)

    assert motion.offset == (0, 0)

    motion.update(4.01)

    assert motion.offset != (0, 0)
    assert abs(motion.offset[0]) <= 2
    assert abs(motion.offset[1]) <= 1


def test_face_visibility_transition_reverses_without_jumping():
    transition = FaceVisibilityTransition(
        coalesce_seconds=1.0,
        dissipate_seconds=2.0,
    )

    assert transition.update(0.25, target_visible=True) == pytest.approx(0.25)
    assert transition.update(0.75, target_visible=True) == pytest.approx(1.0)
    assert transition.update(1.0, target_visible=False) == pytest.approx(0.5)
    assert transition.update(0.25, target_visible=True) == pytest.approx(0.75)

    with pytest.raises(ValueError, match="negative"):
        transition.update(-0.01, target_visible=True)


def test_demo_timeline_loops_with_a_neutral_pause():
    timeline = VisemeTimeline(
        duration=0.2,
        frame_seconds=0.1,
        shapes=(MouthShape.AE, MouthShape.ROUND),
    )
    player = DemoTimelinePlayer(timeline, pause=0.1)

    assert player.update(0.05) is MouthShape.REST
    assert player.update(0.05) is MouthShape.AE
    assert player.update(0.1) is MouthShape.ROUND
    assert player.update(0.1) is MouthShape.REST
