"""Phase 6 tests for the Jarvis Head tonal ramp and glyph-weight mapping."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HEAD_ROOT = Path(__file__).resolve().parents[1] / "jarvis-head"
sys.path.insert(0, str(HEAD_ROOT))

from app import FACE_GLYPH_BANDS, face_glyph_pool  # noqa: E402
from palette import (  # noqa: E402
    BASE_HUES,
    LINUX_PALETTE_RESET,
    build_ramp,
    dedupe_adjacent,
    face_fraction,
    face_shade_index,
    linux_palette_sequence,
    nearest_xterm256,
    rain_shade_index,
    to_curses_scale,
    xterm256_ramp,
)
from rain import BACKGROUND_CHARS  # noqa: E402


def _luminance(color: tuple[int, int, int]) -> float:
    red, green, blue = color
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


@pytest.mark.parametrize("name", sorted(BASE_HUES))
def test_ramp_is_monotonically_brighter_and_ends_near_white(name):
    ramp = build_ramp(BASE_HUES[name], 15)

    luminances = [_luminance(color) for color in ramp]
    assert luminances == sorted(luminances)
    assert len(set(ramp)) == len(ramp)
    assert all(channel >= 190 for channel in ramp[-1])
    assert max(ramp[0]) <= 40


def test_ramp_passes_through_the_base_hue():
    base = BASE_HUES["green"]

    assert base in build_ramp(base, 15)

    with pytest.raises(ValueError, match="two steps"):
        build_ramp(base, 1)


@pytest.mark.parametrize("shade_count", (3, 7, 14, 15))
def test_roles_are_ordered_rain_below_lead_below_skin_below_eyes(shade_count):
    rain = [rain_shade_index(level, False, shade_count) for level in (1, 2, 3)]
    lead = rain_shade_index(3, True, shade_count)
    skin = face_shade_index(130, shade_count)
    eyes = face_shade_index(255, shade_count)

    assert rain == sorted(rain)
    assert rain[-1] <= lead <= skin <= eyes
    assert eyes == shade_count - 1
    assert rain_shade_index(0, False, shade_count) == rain[0]
    assert rain_shade_index(99, False, shade_count) == rain[-1]


def test_console_ramp_keeps_lead_strictly_below_skin_and_eyes_on_top():
    assert rain_shade_index(3, True, 14) < face_shade_index(130, 14)
    assert face_shade_index(40, 14) > rain_shade_index(1, False, 14)
    assert face_shade_index(255, 14) == 13


def test_invalid_shade_inputs_are_rejected():
    with pytest.raises(ValueError, match="0-255"):
        face_shade_index(256, 14)
    with pytest.raises(ValueError, match="two shades"):
        rain_shade_index(1, False, 1)


def test_xterm_snapping_prefers_exact_cube_entries_and_gray_only_for_neutrals():
    assert nearest_xterm256((0, 0, 0)) == 16
    assert nearest_xterm256((255, 255, 255)) == 231
    assert nearest_xterm256((0, 255, 0)) == 46
    assert nearest_xterm256((128, 128, 128)) == 244
    # Dark saturated green must not become gray even though gray is closer.
    assert nearest_xterm256((0, 39, 11)) == 16
    assert nearest_xterm256((0, 61, 17)) == 22


@pytest.mark.parametrize("name", sorted(BASE_HUES))
def test_xterm_ramp_has_no_black_and_enough_distinct_shades(name):
    ramp = xterm256_ramp(BASE_HUES[name], 15)

    assert 16 not in ramp
    assert len(ramp) >= 8
    assert len(ramp) == len(set(ramp))
    assert dedupe_adjacent((1, 1, 2, 2, 1)) == (1, 2, 1)


def test_console_palette_sequences_and_curses_scale():
    assert linux_palette_sequence(8, (0, 255, 70)) == "\x1b]P800ff46"
    assert linux_palette_sequence(15, (255, 255, 255)) == "\x1b]PFffffff"
    assert LINUX_PALETTE_RESET == "\x1b]R"
    assert to_curses_scale((0, 255, 51)) == (0, 1000, 200)

    with pytest.raises(ValueError, match="0-15"):
        linux_palette_sequence(16, (0, 0, 0))
    with pytest.raises(ValueError, match="0-255"):
        to_curses_scale((0, 256, 0))


def test_face_glyph_bands_are_disjoint_subsets_of_the_rain_alphabet():
    pools = [pool for _bound, pool in FACE_GLYPH_BANDS]

    for pool in pools:
        assert set(pool) <= set(BACKGROUND_CHARS)
        assert len(set(pool)) == len(pool) >= 2
    for first, second in zip(pools, pools[1:], strict=False):
        assert not set(first) & set(second)

    bounds = [bound for bound, _pool in FACE_GLYPH_BANDS]
    assert bounds == sorted(bounds) and bounds[-1] == 256
    for index, (bound, pool) in enumerate(FACE_GLYPH_BANDS):
        lower = 0 if index == 0 else bounds[index - 1]
        assert face_glyph_pool(lower) == pool
        assert face_glyph_pool(bound - 1) == pool
    # Forehead/cheek highlights (~195) must not reach the dense specular band.
    assert face_glyph_pool(195) is not pools[-1]
    assert face_glyph_pool(255) is pools[-1]
    with pytest.raises(ValueError, match="0-255"):
        face_glyph_pool(-1)


def test_highlight_curve_keeps_skin_highlights_out_of_the_eye_tint():
    # Authored mask: forehead ~192, cheek ~197, nose specular ~249, eye whites 255.
    assert face_fraction(0) == pytest.approx(0.36)
    assert face_fraction(255) == pytest.approx(1.0)
    assert face_fraction(195) < 0.75
    assert face_shade_index(195, 14) <= face_shade_index(255, 14) - 3
    assert face_shade_index(130, 14) > rain_shade_index(3, True, 14)
    fractions = [face_fraction(value) for value in range(256)]
    assert fractions == sorted(fractions)
