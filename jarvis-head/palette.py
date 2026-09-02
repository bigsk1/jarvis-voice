"""Pure tonal-ramp math for the Jarvis Head terminal palette.

The Linux virtual console advertises ``ccc``/``initc``, so its 16 palette slots
can be redefined into a single-hue ramp. 256-color terminals get the same ramp
snapped to the xterm cube. Everything here is curses-free so the mapping from
rain intensity and mask luminance to ramp position stays unit-testable.
"""

from __future__ import annotations

RGB = tuple[int, int, int]

BASE_HUES: dict[str, RGB] = {
    "green": (0, 255, 70),
    "cyan": (0, 230, 255),
    "blue": (70, 120, 255),
    "magenta": (255, 70, 230),
    "red": (255, 45, 45),
    "yellow": (255, 220, 40),
    "white": (235, 235, 235),
}

# Ramp length requested on terminals that can express it. The Linux console
# yields 14 (seven normal + seven bright slots); 8-color ``ccc`` terminals that
# are not the console yield 7; everything else falls back to three attributes.
SHADE_COUNT = 15
CONSOLE_COLOR_SLOTS = 7
RAMP_SATURATION_POINT = 0.62
RAMP_DARK_FLOOR = 0.10
RAMP_DARK_GAMMA = 1.35
RAMP_TINT_CEILING = 0.85

# Where each renderer role sits on the ramp, as a fraction of its length.
# Rain body stays in the lower third so skin reads brighter than the field, the
# demoted lead sits around mid skin tone, and eye whites take the top of the ramp.
RAIN_FRACTIONS = (0.08, 0.18, 0.28)
LEAD_FRACTION = 0.45
FACE_FLOOR_FRACTION = 0.36
# Mask luminance is compressed before it hits the ramp. The authored head has
# forehead/cheek highlights near 195 and a nose specular near 250; linear mapping
# put them in the same pale tint as the eye whites (255). Gamma > 1 keeps skin
# highlights in saturated hue and reserves the tint for the eyes.
FACE_GAMMA = 2.2
# Operator gain on the face's height above the ramp floor (fb renderer). The
# panel reads brighter than a PNG of the same frame, so the floor is generous.
DEFAULT_FACE_BRIGHTNESS = 1.0
FACE_BRIGHTNESS_RANGE = (0.2, 1.5)
# Signed scanline offset in 256-level framebuffer ramp units. Positive values
# brighten the band, zero hides it, and negative values create a dark sweep.
DEFAULT_SCAN_LEVELS = 72
SCAN_LEVELS_RANGE = (-255, 255)

_XTERM_CUBE_LEVELS = (0, 95, 135, 175, 215, 255)
NEUTRAL_CHROMA_LIMIT = 24


def build_ramp(base: RGB, steps: int) -> tuple[RGB, ...]:
    """Return ``steps`` colors from near-black through ``base`` to a pale tint."""

    if steps < 2:
        raise ValueError("a ramp needs at least two steps")
    _validate_rgb(base)

    # Snap the saturated base hue onto a real step so the ramp always contains
    # it exactly; the two segments interpolate toward it from either side.
    peak = min(steps - 1, max(1, round(RAMP_SATURATION_POINT * (steps - 1))))
    ramp: list[RGB] = []
    for index in range(steps):
        if index <= peak:
            relative = index / peak
            scale = RAMP_DARK_FLOOR + (1.0 - RAMP_DARK_FLOOR) * relative**RAMP_DARK_GAMMA
            ramp.append(_scale(base, scale))
        else:
            relative = (index - peak) / (steps - 1 - peak)
            ramp.append(_lerp(base, (255, 255, 255), relative * RAMP_TINT_CEILING))
    return tuple(ramp)


def nearest_xterm256(color: RGB) -> int:
    """Snap an RGB color to the closest xterm 256-color index (16-255).

    The gray ramp (232-255) is only a candidate for near-neutral input. Very dark
    saturated colors would otherwise snap to gray because the 6x6x6 cube has no
    entries between black and channel level 95, and a gray rain reads as dirt.
    """

    _validate_rgb(color)
    best_index = 16
    best_distance: float | None = None
    for red_index, red in enumerate(_XTERM_CUBE_LEVELS):
        for green_index, green in enumerate(_XTERM_CUBE_LEVELS):
            for blue_index, blue in enumerate(_XTERM_CUBE_LEVELS):
                distance = _distance(color, (red, green, blue))
                if best_distance is None or distance < best_distance:
                    best_distance = distance
                    best_index = 16 + 36 * red_index + 6 * green_index + blue_index
    if max(color) - min(color) <= NEUTRAL_CHROMA_LIMIT:
        for gray_index in range(24):
            level = 8 + 10 * gray_index
            distance = _distance(color, (level, level, level))
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_index = 232 + gray_index
    return best_index


def xterm256_ramp(base: RGB, steps: int) -> tuple[int, ...]:
    """Snap a ramp onto xterm indices, dropping black and repeated neighbors.

    Index 16 is black-on-black, so it is never a usable foreground shade.
    """

    snapped = tuple(nearest_xterm256(color) for color in build_ramp(base, steps))
    usable = dedupe_adjacent(tuple(index for index in snapped if index != 16))
    if len(usable) < 2:
        raise ValueError("ramp collapsed onto too few xterm colors")
    return usable


def dedupe_adjacent(values: tuple[int, ...]) -> tuple[int, ...]:
    """Drop repeated neighbors so a snapped ramp never wastes a shade slot."""

    result: list[int] = []
    for value in values:
        if not result or result[-1] != value:
            result.append(value)
    return tuple(result)


def to_curses_scale(color: RGB) -> tuple[int, int, int]:
    """Convert 0-255 channels to the 0-1000 range ``curses.init_color`` wants."""

    _validate_rgb(color)
    return tuple(round(channel * 1000 / 255) for channel in color)  # type: ignore[return-value]


def linux_palette_sequence(slot: int, color: RGB) -> str:
    """Return the Linux console ``ESC ] P n rrggbb`` palette redefinition."""

    if not 0 <= slot <= 15:
        raise ValueError("Linux console palette slots are 0-15")
    _validate_rgb(color)
    red, green, blue = color
    return f"\x1b]P{slot:X}{red:02x}{green:02x}{blue:02x}"


LINUX_PALETTE_RESET = "\x1b]R"


def rain_shade_index(intensity: int, is_lead: bool, shade_count: int) -> int:
    """Map a rain cell onto the ramp, keeping leads below skin brightness."""

    _validate_shade_count(shade_count)
    if is_lead:
        return _fraction_index(LEAD_FRACTION, shade_count)
    clamped = min(max(intensity, 1), len(RAIN_FRACTIONS))
    return _fraction_index(RAIN_FRACTIONS[clamped - 1], shade_count)


def face_shade_index(value: int, shade_count: int) -> int:
    """Map mask luminance onto the ramp; 255 always lands on the top shade."""

    _validate_shade_count(shade_count)
    if not 0 <= value <= 255:
        raise ValueError("mask values are 0-255")
    return _fraction_index(face_fraction(value), shade_count)


def face_fraction(value: int) -> float:
    """Return the ramp position (0-1) for a mask luminance after the highlight curve."""

    if not 0 <= value <= 255:
        raise ValueError("mask values are 0-255")
    curved = (value / 255) ** FACE_GAMMA
    return FACE_FLOOR_FRACTION + (1.0 - FACE_FLOOR_FRACTION) * curved


def _fraction_index(fraction: float, shade_count: int) -> int:
    return min(shade_count - 1, max(0, round(fraction * (shade_count - 1))))


def _validate_shade_count(shade_count: int) -> None:
    if shade_count < 2:
        raise ValueError("a palette needs at least two shades")


def _validate_rgb(color: RGB) -> None:
    if len(color) != 3 or any(not 0 <= channel <= 255 for channel in color):
        raise ValueError("colors are (r, g, b) tuples of 0-255 integers")


def _scale(color: RGB, scale: float) -> RGB:
    return tuple(min(255, max(0, round(channel * scale))) for channel in color)  # type: ignore[return-value]


def _lerp(start: RGB, end: RGB, amount: float) -> RGB:
    return tuple(  # type: ignore[return-value]
        min(255, max(0, round(a + (b - a) * amount))) for a, b in zip(start, end, strict=True)
    )


def _distance(a: RGB, b: RGB) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b, strict=True))
