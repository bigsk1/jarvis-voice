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
    EYE_ANCHOR_VALUE,
    AmbientScanScheduler,
    DemoTimelinePlayer,
    FaceGlyphLayer,
    FaceVisibilityTransition,
    HeadScene,
    IdleFaceMotion,
    RainPalette,
    eye_clusters,
    face_glyph_pool,
)
from mask import FittedMask, MaskCell, SemanticFaceMasks, SemanticMask  # noqa: E402
from rain import RainCell  # noqa: E402
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


def test_face_palette_puts_eyes_on_top_and_leads_below_skin():
    palette = RainPalette.for_shades(tuple(range(100, 114)))  # 14 console shades

    skin = palette.attribute_for_mask(130)
    eyes = palette.attribute_for_mask(255)
    lead = palette.attribute_for(RainCell(x=0, y=0, char="x", intensity=3, is_lead=True))
    body = palette.attribute_for(RainCell(x=0, y=0, char="x", intensity=3, is_lead=False))

    assert eyes == palette.shades[-1]
    assert body < lead < skin < eyes
    assert palette.attribute_for_mask(0) > palette.shades[0]
    assert all(palette.attribute_for_mask(value) in palette.shades for value in range(256))


def test_halo_dims_rain_one_step_and_stops_at_the_darkest_shade():
    palette = RainPalette.for_shades((10, 20, 30))
    faint = RainCell(x=0, y=0, char="x", intensity=1, is_lead=False)
    lead = RainCell(x=0, y=0, char="x", intensity=3, is_lead=True)

    assert palette.attribute_for(faint, dimmed=True) == 10
    assert palette.attribute_for(lead, dimmed=True) < palette.attribute_for(lead)


def test_face_glyphs_carry_luminance_as_weight_bands():
    image = Image.new("L", (3, 1))
    image.putpixel((0, 0), 40)
    image.putpixel((1, 0), 130)
    image.putpixel((2, 0), 240)
    layer = FaceGlyphLayer(SemanticMask(image).fit(1, 3, cell_aspect=1.0, scale=1.0), seed=3)

    for _ in range(40):
        layer.update(0.1)
        dark, mid, bright = layer.cells
        assert dark.char in face_glyph_pool(40)
        assert mid.char in face_glyph_pool(130)
        assert bright.char in face_glyph_pool(240)


def test_expression_swap_rebands_glyphs_only_where_the_band_changed():
    resting = SemanticMask(Image.new("L", (2, 1), color=130)).fit(1, 2, cell_aspect=1.0, scale=1.0)
    brighter = Image.new("L", (2, 1), color=130)
    brighter.putpixel((1, 0), 240)
    layer = FaceGlyphLayer(resting, seed=5)
    kept, rebanded = (cell.char for cell in layer.cells)

    layer.apply_mask(SemanticMask(brighter).fit(1, 2, cell_aspect=1.0, scale=1.0))

    assert layer.cells[0].char == kept
    assert layer.cells[1].char in face_glyph_pool(240)
    assert layer.cells[1].char != rebanded


def test_halo_surrounds_the_silhouette_without_overlapping_it():
    layer = FaceGlyphLayer(_fitted_test_mask(), seed=1)
    occupied = {(cell.x, cell.y) for cell in layer.cells}

    assert layer.halo
    assert not layer.halo & occupied
    assert (-1, 1) in layer.halo
    assert (5, 1) in layer.halo
    assert (2, -2) in layer.halo
    assert (2, -3) not in layer.halo
    assert (2, 4) in layer.halo
    assert (-5, 1) not in layer.halo


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


def test_ambient_scan_waits_for_a_visible_face_and_resets_when_it_hides():
    scheduler = AmbientScanScheduler(
        seed=9,
        first_seconds=1.0,
        min_seconds=10.0,
        max_seconds=10.0,
        double_chance=0.0,
        sweep_seconds=1.0,
    )

    assert scheduler.update(5.0, face_visible=False) == (None, False)
    assert scheduler.update(0.75, face_visible=True) == (None, False)
    phase, nudge = scheduler.update(0.25, face_visible=True)
    assert phase == pytest.approx(0.0)
    assert nudge is False
    assert scheduler.update(0.5, face_visible=True) == (pytest.approx(0.5), False)
    assert scheduler.update(0.5, face_visible=True) == (None, False)
    assert scheduler.update(9.99, face_visible=True) == (None, False)
    phase, nudge = scheduler.update(0.01, face_visible=True)
    assert phase == pytest.approx(0.0)
    assert nudge is False

    assert scheduler.update(0.0, face_visible=False) == (None, False)
    assert scheduler.update(0.99, face_visible=True) == (None, False)
    phase, _nudge = scheduler.update(0.01, face_visible=True)
    assert phase == pytest.approx(0.0)


def test_ambient_scan_double_pass_requests_one_glitch_nudge():
    scheduler = AmbientScanScheduler(
        seed=4,
        first_seconds=0.0,
        min_seconds=10.0,
        max_seconds=10.0,
        double_chance=1.0,
        sweep_seconds=1.0,
        double_gap_seconds=0.2,
    )

    assert scheduler.update(0.0, face_visible=True) == (pytest.approx(0.0), False)
    assert scheduler.update(1.0, face_visible=True) == (None, False)
    assert scheduler.update(0.19, face_visible=True) == (None, False)
    phase, nudge = scheduler.update(0.01, face_visible=True)
    assert phase == pytest.approx(0.0)
    assert nudge is True
    assert scheduler.update(0.5, face_visible=True) == (pytest.approx(0.5), False)


def test_ambient_scan_timing_is_seeded_and_rejects_invalid_ranges():
    first = AmbientScanScheduler(seed=42, first_seconds=0.0)
    second = AmbientScanScheduler(seed=42, first_seconds=0.0)
    samples = []
    for _ in range(400):
        left = first.update(0.1, face_visible=True)
        right = second.update(0.1, face_visible=True)
        assert left == right
        samples.append(left)
    assert sum(phase is not None for phase, _nudge in samples) > 20

    with pytest.raises(ValueError, match="first delay"):
        AmbientScanScheduler(seed=1, first_seconds=-1)
    with pytest.raises(ValueError, match="interval"):
        AmbientScanScheduler(seed=1, min_seconds=2, max_seconds=1)
    with pytest.raises(ValueError, match="double chance"):
        AmbientScanScheduler(seed=1, double_chance=1.1)


def test_scan_glitch_nudge_is_repeatable_and_stays_nearby():
    first = IdleFaceMotion(fps=20, seed=11)
    second = IdleFaceMotion(fps=20, seed=11)

    for _ in range(20):
        before = first.offset
        first.nudge()
        second.nudge()
        assert first.offset == second.offset
        assert first.offset != before
        assert abs(first.offset[0] - before[0]) <= 1
        assert abs(first.offset[1] - before[1]) <= 1


def test_head_scene_runs_ambient_scan_during_speech_and_applies_double_nudge():
    scene = HeadScene(
        height=60,
        width=100,
        preset="kiosk",
        fps=20,
        seed=11,
        face_masks=SemanticFaceMasks.from_directory(HEAD_ROOT / "assets"),
        timeline=None,
        cell_aspect=0.5,
        event_socket=None,
        state_machine=None,
        ambient_scan=True,
        ambient_scan_first_seconds=0.0,
        ambient_scan_min_seconds=10.0,
        ambient_scan_max_seconds=10.0,
        ambient_scan_double_chance=1.0,
    )
    scene.speech_energy = 0.75
    before = scene.face_offset

    scene.step(0.0)
    assert scene.scan_phase == pytest.approx(0.0)
    assert scene.thinking is False
    assert scene.speech_energy == 0.75
    scene.step(1.2)
    assert scene.scan_phase is None
    scene.step(0.2)

    assert scene.scan_phase == pytest.approx(0.0)
    assert scene.face_offset != before
    assert scene.speech_energy == 0.75


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


def test_demo_timeline_exposes_speech_energy_alongside_the_shape():
    timeline = VisemeTimeline(
        duration=0.2,
        frame_seconds=0.1,
        shapes=(MouthShape.AE, MouthShape.ROUND),
        levels=(1.0, 0.4),
    )
    player = DemoTimelinePlayer(timeline, pause=0.1)

    player.update(0.05)  # inside the neutral pause
    assert player.energy == 0.0
    player.update(0.05)
    assert player.energy == 1.0
    player.update(0.1)
    assert player.energy == pytest.approx(0.4)
    player.update(0.1)
    assert player.energy == 0.0


def _authored_fitted_mask() -> FittedMask:
    masks = SemanticFaceMasks.from_directory(HEAD_ROOT / "assets")
    return masks.fit(60, 100, cell_aspect=0.5).get(blinking=False, mouth="rest")


def _authored_face_layer(seed: int = 3) -> FaceGlyphLayer:
    return FaceGlyphLayer(_authored_fitted_mask(), seed=seed)


def test_coalesce_resolves_the_eyes_first_and_the_jaw_last():
    layer = _authored_face_layer()
    fitted = _authored_fitted_mask()
    assert len(layer.eye_anchors) == 2
    (left_x, left_y), (right_x, right_y) = layer.eye_anchors
    assert left_x < right_x and abs(left_y - right_y) < 3

    assert all(0.0 <= point <= 1.0 for point in layer.transition_points)
    by_position = {
        (cell.x, cell.y): point
        for cell, point in zip(layer.cells, layer.transition_points, strict=True)
    }
    # Eye cells are the eye-white clusters; the nose specular is as bright but
    # is not an anchor, so it is measured separately below.
    eye_cells = [cell for cluster in eye_clusters(fitted) for cell in cluster]
    eye_positions = {(cell.x, cell.y) for cell in eye_cells}
    nose_cells = [
        cell
        for cell in layer.cells
        if cell.value >= EYE_ANCHOR_VALUE and (cell.x, cell.y) not in eye_positions
    ]
    assert nose_cells
    lit = [cell for cell in layer.cells if cell.value > 0]
    jaw_row = max(cell.y for cell in lit)
    jaw_cells = [cell for cell in lit if cell.y >= jaw_row - 1]
    eye_mean = sum(by_position[(c.x, c.y)] for c in eye_cells) / len(eye_cells)
    jaw_mean = sum(by_position[(c.x, c.y)] for c in jaw_cells) / len(jaw_cells)
    nose_mean = sum(by_position[(c.x, c.y)] for c in nose_cells) / len(nose_cells)
    assert eye_mean < 0.25 < 0.6 < jaw_mean
    assert eye_mean < nose_mean

    early = {(cell.x, cell.y) for cell in layer.visible_cells(0.4)}
    assert sum((c.x, c.y) in early for c in eye_cells) / len(eye_cells) > 0.8
    assert sum((c.x, c.y) in early for c in jaw_cells) / len(jaw_cells) < 0.2

    # The eased front is what both renderers use, so it must be the same curve.
    assert FaceGlyphLayer.eased_progress(0.5) == pytest.approx(0.5)
    assert FaceGlyphLayer.eased_progress(0.25) < 0.25
    with pytest.raises(ValueError, match="between"):
        FaceGlyphLayer.eased_progress(1.01)


def test_eye_anchors_fall_back_to_the_face_center_without_eye_whites():
    image = Image.new("L", (5, 3), color=100)  # no cell reaches 230
    layer = FaceGlyphLayer(SemanticMask(image).fit(3, 5, cell_aspect=1.0, scale=1.0), seed=1)
    assert len(layer.eye_anchors) == 1
    center = layer.eye_anchors[0]
    nearest = min(layer.cells, key=lambda c: (c.x - center[0]) ** 2 + (c.y - center[1]) ** 2)
    assert (
        layer.transition_points[layer.cells.index(nearest)] <= min(layer.transition_points) + 0.35
    )


def test_face_presence_caps_the_coalesce_and_is_bounded():
    veiled = FaceVisibilityTransition(coalesce_seconds=1.0, dissipate_seconds=1.0, presence=0.45)
    assert veiled.update(0.3, target_visible=True) == pytest.approx(0.3)
    assert veiled.update(5.0, target_visible=True) == pytest.approx(0.45)
    assert veiled.update(0.1, target_visible=False) == pytest.approx(0.35)
    assert veiled.update(5.0, target_visible=True) == pytest.approx(0.45)
    with pytest.raises(ValueError, match="presence"):
        FaceVisibilityTransition(presence=0.2)
    with pytest.raises(ValueError, match="presence"):
        FaceVisibilityTransition(presence=1.1)


def test_scene_face_layer_anchors_the_mouth_so_a_veiled_face_still_speaks():
    from app import HeadScene, _mouth_anchor

    masks = SemanticFaceMasks.from_directory(HEAD_ROOT / "assets")
    scene = HeadScene(
        height=60,
        width=100,
        preset="kiosk",
        fps=30,
        seed=3,
        face_masks=masks,
        timeline=None,
        cell_aspect=0.5,
        event_socket=None,
        state_machine=None,
        face_presence=0.45,
    )
    layer = scene.face_layer
    assert layer is not None and scene.fitted_faces is not None
    assert len(layer.eye_anchors) == 2 and len(layer.anchors) == 3
    mouth = _mouth_anchor(scene.fitted_faces)
    assert mouth is not None and layer.anchors[2] == mouth
    (_lx, left_y), (_rx, right_y) = layer.eye_anchors
    assert mouth[1] > max(left_y, right_y) + 5  # the mouth sits well below the eyes

    rest = scene.fitted_faces.get(blinking=False, mouth="rest")
    ae = scene.fitted_faces.get(blinking=False, mouth="ae")
    mouth_cells = {
        (a.x, a.y) for a, b in zip(rest.cells, ae.cells, strict=True) if a.value != b.value
    }
    assert mouth_cells

    # The eye anchors are the eye whites, not the bright nose strip below them.
    bright = [c for c in rest.cells if c.value >= EYE_ANCHOR_VALUE]
    eye_cells = {(c.x, c.y) for cluster in eye_clusters(rest) for c in cluster}
    nose_cells = [c for c in bright if (c.x, c.y) not in eye_cells]
    assert eye_cells and nose_cells
    top_bright_row = min(c.y for c in bright)
    assert max(left_y, right_y) <= top_bright_row + 1
    nose_y = sum(c.y for c in nose_cells) / len(nose_cells)
    assert nose_y > max(left_y, right_y) + 3

    for _ in range(90):
        scene.step(1 / 30)
    assert scene.face_progress == pytest.approx(0.45)
    shown = {(c.x, c.y) for c in layer.visible_cells(scene.face_progress)}
    lit = [c for c in layer.cells if c.value > 0]
    assert len(shown) < 0.75 * len(lit)  # the skull stays veiled
    assert sum(pos in shown for pos in eye_cells) / len(eye_cells) > 0.9
    assert sum(pos in shown for pos in mouth_cells) / len(mouth_cells) > 0.7
    # The nose is not an anchor: it sits between the eyes and mouth so its upper
    # end resolves with them, but part of the strip stays rain at this presence.
    nose_shown = sum((c.x, c.y) in shown for c in nose_cells) / len(nose_cells)
    assert 0.3 < nose_shown < 0.8


def test_eye_clusters_skip_the_nose_and_fall_back_to_a_center_split():
    def mask(cells):
        return FittedMask(width=20, height=20, cells=cells)

    def cell(x, y, value=255):
        return MaskCell(x=x, y=y, value=value)

    skin = [cell(x, y, 120) for y in range(2, 18) for x in range(4, 16)]
    eyes = [cell(6, 4), cell(7, 4), cell(12, 4), cell(13, 4)]
    nose = [cell(9, 6), cell(9, 7), cell(10, 7), cell(9, 8), cell(10, 8), cell(9, 9)]
    left, right = eye_clusters(mask(skin + eyes + nose))
    assert {(c.x, c.y) for c in left} == {(6, 4), (7, 4)}
    assert {(c.x, c.y) for c in right} == {(12, 4), (13, 4)}

    # Only one eye survives on the top band: its mirror across the face's center
    # column stands in for the other; the nose below the band is never used.
    left, right = eye_clusters(mask(skin + eyes[:2] + nose))
    assert {(c.x, c.y) for c in left} == {(6, 4), (7, 4)}
    assert [(c.x, c.y) for c in right] == [(12, 4)]

    # A nose-only strip straddling the center column is not a pair of eyes: the
    # halves are too close together, so there are no clusters (center fallback).
    assert eye_clusters(mask(skin + nose)) == []
    strip = [cell(9, 4), cell(10, 4), cell(9, 5), cell(10, 5)]
    assert eye_clusters(mask(skin + strip)) == []
    # ...and a one-sided strip hugging the center is not mirrored either.
    assert eye_clusters(mask(skin + [cell(9, 4), cell(9, 5)])) == []

    assert eye_clusters(mask(skin)) == []
    lit = skin + nose
    layer = FaceGlyphLayer(mask(lit), seed=1)
    center = (sum(c.x for c in lit) / len(lit), sum(c.y for c in lit) / len(lit))
    assert layer.eye_anchors == (center,)  # the face center, not the nose
    assert abs(center[0] - 9.5) < 0.1 and abs(center[1] - 9.5) < 0.1


@pytest.mark.parametrize(
    ("rows", "cols", "cell_aspect"),
    [
        pytest.param(108, 384, 5 / 10, id="1080p-font-8"),
        pytest.param(83, 274, 7 / 13, id="1080p-font-10"),
        pytest.param(72, 240, 8 / 15, id="1080p-font-12"),
        pytest.param(48, 160, 8 / 15, id="720p-font-12"),
        pytest.param(40, 128, 10 / 18, id="720p-font-15"),
        pytest.param(34, 116, 11 / 21, id="720p-font-17"),
        pytest.param(30, 98, 13 / 24, id="720p-font-20"),
        pytest.param(40, 120, 0.4, id="curses-40-rows"),
        pytest.param(30, 100, 0.4, id="curses-30-rows"),
        pytest.param(24, 80, 0.4, id="curses-24-rows"),
    ],
)
def test_eye_anchors_never_land_on_the_nose_on_any_supported_grid(rows, cols, cell_aspect):
    masks = SemanticFaceMasks.from_directory(HEAD_ROOT / "assets")
    fitted = masks.fit(rows, cols, cell_aspect=cell_aspect).get(blinking=False, mouth="rest")
    lit = [c for c in fitted.cells if c.value > 0]
    bright = [c for c in lit if c.value >= EYE_ANCHOR_VALUE]
    assert bright  # the specular survives on every grid; the eyes need not
    center_x = sum(c.x for c in lit) / len(lit)
    width = max(c.x for c in lit) - min(c.x for c in lit) + 1
    # Independent of the anchor logic: the nose is the bright strip near the center column.
    nose = {(c.x, c.y) for c in bright if abs(c.x - center_x) < 0.08 * width}
    assert nose

    clusters = eye_clusters(fitted)
    layer = FaceGlyphLayer(fitted, seed=1)
    if clusters:
        assert len(clusters) == 2
        assert not any((c.x, c.y) in nose for cluster in clusters for c in cluster)
        (left_x, left_y), (right_x, right_y) = layer.eye_anchors
        assert right_x - left_x >= 0.2 * width
        assert abs(left_y - right_y) < 1.5
        assert min(left_y, right_y) <= min(c.y for c in bright) + 1.5
    else:
        center = (center_x, sum(c.y for c in lit) / len(lit))
        assert layer.eye_anchors == (center,)


def test_idle_motion_breathes_on_a_slow_sine():
    motion = IdleFaceMotion(fps=30, seed=9)
    samples = []
    for _ in range(int(4.2 * 30)):
        motion.update(1 / 30)
        samples.append(motion.breath)
    assert -1.0 <= min(samples) < -0.95
    assert 0.95 < max(samples) <= 1.0
    steps = [abs(b - a) for a, b in zip(samples, samples[1:], strict=False)]
    assert max(steps) < 0.06  # smooth per frame, no jumps
