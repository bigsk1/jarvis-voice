"""Curses application for the standalone Jarvis Head display."""

from __future__ import annotations

import curses
import math
import os
import random
import signal
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from head_socket import HeadEventSocket
from head_state import DEFAULT_IDLE_TIMEOUT, BaseState, HeadStateMachine
from mask import DEFAULT_CELL_ASPECT, FittedFaceMasks, FittedMask, MaskCell, SemanticFaceMasks
from palette import (
    BASE_HUES,
    CONSOLE_COLOR_SLOTS,
    DEFAULT_FACE_BRIGHTNESS,
    DEFAULT_SCAN_LEVELS,
    FACE_BRIGHTNESS_RANGE,
    LINUX_PALETTE_RESET,
    SCAN_LEVELS_RANGE,
    SHADE_COUNT,
    build_ramp,
    face_shade_index,
    linux_palette_sequence,
    rain_shade_index,
    to_curses_scale,
    xterm256_ramp,
)
from rain import PRESETS, RainCell, RainField
from visemes import MouthShape, VisemeTimeline, analyze_wav

DEFAULT_FPS = 30.0
MAX_FRAME_DT = 0.25
# Stop signals a long-running display converts into one clean KeyboardInterrupt.
INTERRUPT_SIGNALS = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)
FACE_GLYPH_TICK = 0.1
FACE_GLYPH_CHANGE_CHANCE = 0.12
# Glyph weight is a second luminance channel on the face only. Shadowed skin
# uses sparse punctuation, mid tones lowercase, lit skin uppercase/digits, and
# only eye whites and speculars (>= 230) use the dense glyphs, so shading
# survives even when two cells share a shade. Bands are disjoint.
FACE_GLYPH_BANDS: tuple[tuple[int, str], ...] = (
    (70, ".,:;-_="),
    (150, "abcdefghijklmnopqrstuvwxyz"),
    (230, "ACDEFGIJKLOPRSTUVXYZ0123456789"),
    (256, "@#%&MWBQNH$"),
)
# Rain this close to the silhouette drops one shade so the head separates from
# the field. Cells are roughly 0.4 wide per row, so reach further in x than y.
HALO_REACH = (4, 2)
RENDERERS = ("curses", "fb")
DEFAULT_FRAMEBUFFER = "/dev/fb0"
DEFAULT_FONT_PX = 10
DEFAULT_SNAPSHOT_AT = 4.0
FACE_COALESCE_SECONDS = 1.0
FACE_DISSIPATE_SECONDS = 1.2
BLINK_INTERVAL = (2.0, 6.0)
BLINK_FRAMES = (2, 3)
DRIFT_TARGET_INTERVAL = (3.0, 7.0)
DRIFT_STEP_INTERVAL = 0.35
DRIFT_TARGETS = (
    (-2, 0),
    (-1, -1),
    (-1, 0),
    (0, -1),
    (0, 0),
    (0, 1),
    (1, 0),
    (1, 1),
    (2, 0),
)
DEMO_WAV_PAUSE = 0.75
# Coalesce order: eyes first, then the head assembles outward. Each cell's
# transition point mixes its distance from the nearest eye anchor with jitter
# so the wavefront reads as growth, not a wipe. Dissipate runs it backwards.
EYE_ANCHOR_VALUE = 230
# Bright components this close (in rows) to the topmost one are eye whites; the
# nose specular's centroid sits 5+ rows lower on every grid the head fits.
EYE_ROW_TOLERANCE = 1.5
# Two eye clusters must be this fraction of the face's width apart (the authored
# eyes are ~45% apart; the nose strip is under 10% wide).
EYE_MIN_SEPARATION = 0.2
EYE_DISTANCE_WEIGHT = 0.65
# Rows are about twice as tall as cells are wide; distances use screen shape.
EYE_DISTANCE_ROW_SCALE = 2.0
BREATH_PERIOD_SECONDS = 4.2
AMBIENT_SCAN_FIRST_SECONDS = 3.0
AMBIENT_SCAN_MIN_SECONDS = 10.0
AMBIENT_SCAN_MAX_SECONDS = 14.0
AMBIENT_SCAN_SWEEP_SECONDS = 1.2
AMBIENT_SCAN_DOUBLE_CHANCE = 0.15
AMBIENT_SCAN_DOUBLE_GAP_SECONDS = 0.2
# How far the coalesce goes when the face is "visible". 1.0 is the whole head;
# lower values hold the face mid-condensation: features resolved, the skull
# still veiled in rain. The mouth is a reveal anchor too, so it stays readable.
DEFAULT_FACE_PRESENCE = 1.0
FACE_PRESENCE_RANGE = (0.3, 1.0)

COLOR_NAMES = {
    "blue": curses.COLOR_BLUE,
    "cyan": curses.COLOR_CYAN,
    "green": curses.COLOR_GREEN,
    "magenta": curses.COLOR_MAGENTA,
    "red": curses.COLOR_RED,
    "white": curses.COLOR_WHITE,
    "yellow": curses.COLOR_YELLOW,
}


class RainPalette:
    """A single-hue tonal ramp of black-background curses attributes.

    ``shades`` runs dark to bright. Its length depends on the terminal: 256-color
    terminals snap the ramp to the xterm cube, the Linux console redefines its
    seven normal and seven bright palette slots, other ``ccc`` terminals get the
    seven normal slots, and everything else keeps the dim/normal/bold trio.
    """

    def __init__(self, stdscr: curses.window, color: str) -> None:
        self.has_colors = curses.has_colors()
        self._console_palette_changed = False
        if self.has_colors:
            curses.start_color()
            self.shades = self._build_shades(color)
        else:
            self.shades = (curses.A_DIM, curses.A_NORMAL, curses.A_BOLD)
        self.background = self.shades[0]
        self._build_tables()

        # An explicit black background keeps terminal transparency settings from
        # exposing whatever window happens to sit behind the kiosk.
        stdscr.bkgd(" ", self.background)

    @classmethod
    def for_shades(cls, shades: tuple[int, ...]) -> RainPalette:
        """Build a palette over caller-supplied attributes without touching curses."""

        if len(shades) < 2:
            raise ValueError("a palette needs at least two shades")
        palette = cls.__new__(cls)
        palette.has_colors = True
        palette._console_palette_changed = False
        palette.shades = tuple(shades)
        palette.background = palette.shades[0]
        palette._build_tables()
        return palette

    def attribute_for(self, cell: RainCell, *, dimmed: bool = False) -> int:
        table = self._rain_dimmed if dimmed else self._rain
        return table[cell.is_lead][min(max(cell.intensity, 1), 3)]

    def attribute_for_mask(self, value: int) -> int:
        """Map semantic face luminance onto the ramp; eyes take the top shade."""

        return self._face[value]

    def _build_tables(self) -> None:
        """Resolve every role to an attribute once; the draw loop only indexes."""

        count = len(self.shades)
        body = tuple(self.shades[rain_shade_index(level, False, count)] for level in (1, 1, 2, 3))
        lead = (self.shades[rain_shade_index(3, True, count)],) * 4
        body_dim = tuple(
            self.shades[max(0, rain_shade_index(level, False, count) - 1)] for level in (1, 1, 2, 3)
        )
        lead_dim = (self.shades[max(0, rain_shade_index(3, True, count) - 1)],) * 4
        # Indexed as [is_lead][intensity]; intensity 0 aliases 1.
        self._rain = (body, lead)
        self._rain_dimmed = (body_dim, lead_dim)
        self._face = tuple(self.shades[face_shade_index(value, count)] for value in range(256))

    def restore(self) -> None:
        """Undo a Linux console palette redefinition before the terminal is handed back."""

        if self._console_palette_changed:
            _write_raw(LINUX_PALETTE_RESET)
            self._console_palette_changed = False

    def _build_shades(self, color: str) -> tuple[int, ...]:
        base = BASE_HUES[color]
        if curses.COLORS >= 256 and curses.COLOR_PAIRS > SHADE_COUNT:
            indices = xterm256_ramp(base, SHADE_COUNT)
            for pair, index in enumerate(indices, start=1):
                curses.init_pair(pair, index, curses.COLOR_BLACK)
            return tuple(curses.color_pair(pair) for pair in range(1, len(indices) + 1))

        if curses.COLORS >= 8 and curses.can_change_color():
            is_console = _is_linux_console()
            ramp = build_ramp(base, CONSOLE_COLOR_SLOTS * (2 if is_console else 1))
            shades: list[int] = []
            for slot in range(1, CONSOLE_COLOR_SLOTS + 1):
                curses.init_color(slot, *to_curses_scale(ramp[slot - 1]))
                curses.init_pair(slot, slot, curses.COLOR_BLACK)
                shades.append(curses.color_pair(slot))
            if is_console:
                # ncurses refuses init_color above COLORS-1, but the console's
                # bright slots (8-15) are what A_BOLD selects, so set them raw.
                _write_raw(
                    "".join(
                        linux_palette_sequence(slot + 8, ramp[CONSOLE_COLOR_SLOTS + slot - 1])
                        for slot in range(1, CONSOLE_COLOR_SLOTS + 1)
                    )
                )
                self._console_palette_changed = True
                shades.extend(
                    curses.color_pair(slot) | curses.A_BOLD
                    for slot in range(1, CONSOLE_COLOR_SLOTS + 1)
                )
            return tuple(shades)

        foreground = COLOR_NAMES[color]
        curses.init_pair(1, foreground, curses.COLOR_BLACK)
        return (
            curses.color_pair(1) | curses.A_DIM,
            curses.color_pair(1),
            curses.color_pair(1) | curses.A_BOLD,
        )


def _is_linux_console() -> bool:
    try:
        term = curses.termname().decode("ascii", "replace")
    except curses.error:
        term = os.environ.get("TERM", "")
    return term.startswith("linux")


def _write_raw(sequence: str) -> None:
    """Send an escape sequence past ncurses; palette OSCs do not touch cursor state."""

    try:
        os.write(sys.stdout.fileno(), sequence.encode("ascii"))
    except (OSError, ValueError):
        pass


@dataclass(slots=True)
class FaceGlyphCell:
    """One mask cell with a mutable glyph and fixed semantic intensity."""

    x: int
    y: int
    value: int
    char: str


class FaceGlyphLayer:
    """A face that stays spatially locked while its glyphs mutate slowly."""

    def __init__(
        self,
        fitted_mask: FittedMask,
        *,
        seed: int | None,
        tick_interval: float = FACE_GLYPH_TICK,
        change_chance: float = FACE_GLYPH_CHANGE_CHANCE,
        extra_anchors: Sequence[tuple[float, float]] = (),
    ) -> None:
        if tick_interval <= 0:
            raise ValueError("tick_interval must be positive")
        if not 0 <= change_chance <= 1:
            raise ValueError("change_chance must be between 0 and 1")

        self.rng = random.Random(seed)
        self.tick_interval = tick_interval
        self.change_chance = change_chance
        self.accumulator = 0.0
        # Bumped on every glyph or value change so renderers can cache per-cell
        # arrays between frames and rebuild only when something actually moved.
        self.version = 0
        self.cells = [
            FaceGlyphCell(
                x=cell.x,
                y=cell.y,
                value=cell.value,
                char=" " if cell.value == 0 else self.rng.choice(face_glyph_pool(cell.value)),
            )
            for cell in fitted_mask.cells
        ]
        transition_rng = random.Random(_derived_seed(seed, 0xC0A1))
        self.eye_anchors = _eye_anchors(fitted_mask)
        self.anchors = (*self.eye_anchors, *extra_anchors)
        self._transition_points = _eye_first_transition_points(
            fitted_mask.cells, self.anchors, transition_rng
        )
        self.halo = _halo_cells(fitted_mask, reach=HALO_REACH)
        self._shifted_halo: tuple[tuple[int, int], frozenset[tuple[int, int]]] | None = None

    def halo_at(self, offset: tuple[int, int]) -> frozenset[tuple[int, int]]:
        """Return the halo in screen coordinates; drift changes rarely, so cache it."""

        if self._shifted_halo is None or self._shifted_halo[0] != offset:
            offset_x, offset_y = offset
            self._shifted_halo = (
                offset,
                frozenset((x + offset_x, y + offset_y) for x, y in self.halo),
            )
        return self._shifted_halo[1]

    def update(self, dt: float) -> None:
        """Change scattered glyphs on a slower cadence than the rain."""

        if dt < 0:
            raise ValueError("dt must not be negative")
        self.accumulator += dt
        while self.accumulator >= self.tick_interval:
            self.accumulator -= self.tick_interval
            changed = False
            for cell in self.cells:
                if cell.value > 0 and self.rng.random() < self.change_chance:
                    cell.char = self._replacement_char(cell.char, cell.value)
                    changed = True
            if changed:
                self.version += 1

    def apply_mask(self, fitted_mask: FittedMask) -> None:
        """Change expression intensities without resetting the glyph field."""

        if len(fitted_mask.cells) != len(self.cells):
            raise ValueError("expression masks must have identical coverage")
        self.version += 1
        for glyph_cell, mask_cell in zip(self.cells, fitted_mask.cells, strict=True):
            if (glyph_cell.x, glyph_cell.y) != (mask_cell.x, mask_cell.y):
                raise ValueError("expression masks must have aligned cells")
            previous_pool = face_glyph_pool(glyph_cell.value)
            glyph_cell.value = mask_cell.value
            if mask_cell.value == 0:
                glyph_cell.char = " "
            elif glyph_cell.char == " " or previous_pool != face_glyph_pool(mask_cell.value):
                # A cell that changed weight band (or was the mouth hole) needs a
                # glyph from its new band; same-band cells keep their glyph.
                glyph_cell.char = self.rng.choice(face_glyph_pool(mask_cell.value))

    @property
    def transition_points(self) -> list[float]:
        """Per-cell reveal thresholds in [0, 1]; lower reveals earlier (eyes ~0)."""

        return self._transition_points

    @staticmethod
    def eased_progress(progress: float) -> float:
        """Smoothstep shared by both renderers so their reveal fronts agree."""

        if not 0 <= progress <= 1:
            raise ValueError("face visibility progress must be between 0 and 1")
        return progress * progress * (3.0 - 2.0 * progress)

    def visible_cells(self, progress: float):
        """Yield a deterministic eyes-first subset for coalescence/dissipation."""

        eased = self.eased_progress(progress)
        for cell, transition_point in zip(
            self.cells,
            self._transition_points,
            strict=True,
        ):
            if transition_point < eased:
                yield cell

    def _replacement_char(self, current: str, value: int) -> str:
        pool = face_glyph_pool(value)
        replacement = self.rng.choice(pool)
        if replacement == current:
            replacement = pool[(pool.index(replacement) + 1) % len(pool)]
        return replacement


def face_glyph_pool(value: int) -> str:
    """Return the glyph band for a mask luminance; heavier glyphs for brighter cells."""

    if not 0 <= value <= 255:
        raise ValueError("mask values are 0-255")
    for upper_bound, pool in FACE_GLYPH_BANDS:
        if value < upper_bound:
            return pool
    return FACE_GLYPH_BANDS[-1][1]


def _eye_anchors(fitted_mask: FittedMask) -> tuple[tuple[float, float], ...]:
    """Return the centroids of the left and right eye whites, or the face center.

    Cells at or above ``EYE_ANCHOR_VALUE`` are the eye whites and the nose
    specular, so brightness alone does not find the eyes. See ``eye_clusters``.
    """

    lit = [cell for cell in fitted_mask.cells if cell.value > 0]
    if not lit:
        return ()
    clusters = eye_clusters(fitted_mask)
    if not clusters:
        return (_centroid(lit),)
    return tuple(_centroid(cluster) for cluster in clusters)


def eye_clusters(fitted_mask: FittedMask) -> list[list[MaskCell]]:
    """Return the bright cells that are the left and right eyes, as two groups.

    Bright cells are grouped into 8-connected components (each eye white is
    usually two pieces, one on either side of the iris). The eyes are every
    component whose centroid sits within ``EYE_ROW_TOLERANCE`` rows of the
    topmost one, split at the face's center column, and accepted only if the two
    halves are at least ``EYE_MIN_SEPARATION`` of the face's width apart: eyes
    are wide-set, the nose specular is one narrow central strip, so a strip that
    happens to straddle the center column does not pass as a pair. If only one
    eye survives the downsample (one side, well off center) its mirror image
    across the center column stands in for the other, as a single-cell group at
    the mirrored position. Anything else, including a nose-only strip on a grid
    too coarse to keep the eye whites, returns no clusters, and the caller
    anchors on the face center. Bright cells outside the band are never used.
    """

    lit = [cell for cell in fitted_mask.cells if cell.value > 0]
    bright = [cell for cell in lit if cell.value >= EYE_ANCHOR_VALUE]
    if not bright:
        return []
    center_x = _centroid(lit)[0]
    width = max(cell.x for cell in lit) - min(cell.x for cell in lit) + 1
    components = sorted(_connected_components(bright), key=lambda group: _centroid(group)[1])
    top_row = _centroid(components[0])[1]
    band = [
        cell
        for component in components
        if _centroid(component)[1] <= top_row + EYE_ROW_TOLERANCE
        for cell in component
    ]
    left = [cell for cell in band if cell.x < center_x]
    right = [cell for cell in band if cell.x >= center_x]
    if left and right:
        if _centroid(right)[0] - _centroid(left)[0] >= EYE_MIN_SEPARATION * width:
            return [left, right]
        return []
    lone = left or right
    lone_x, lone_y = _centroid(lone)
    if abs(lone_x - center_x) >= EYE_MIN_SEPARATION * width / 2:
        mirror = MaskCell(x=round(2 * center_x - lone_x), y=round(lone_y), value=EYE_ANCHOR_VALUE)
        return sorted([lone, [mirror]], key=lambda group: _centroid(group)[0])
    return []


def _centroid(cells: Sequence[MaskCell]) -> tuple[float, float]:
    return (sum(cell.x for cell in cells) / len(cells), sum(cell.y for cell in cells) / len(cells))


def _connected_components(cells: Sequence[MaskCell]) -> list[list[MaskCell]]:
    """Group cells into 8-connected components, in first-seen order."""

    by_position = {(cell.x, cell.y): cell for cell in cells}
    seen: set[tuple[int, int]] = set()
    components: list[list[MaskCell]] = []
    for start in by_position:
        if start in seen:
            continue
        seen.add(start)
        stack = [start]
        component: list[MaskCell] = []
        while stack:
            x, y = stack.pop()
            component.append(by_position[(x, y)])
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    neighbor = (x + dx, y + dy)
                    if neighbor in by_position and neighbor not in seen:
                        seen.add(neighbor)
                        stack.append(neighbor)
        components.append(component)
    return components


def _eye_first_transition_points(
    cells: Sequence[MaskCell],
    anchors: Sequence[tuple[float, float]],
    rng: random.Random,
) -> list[float]:
    """Mix eye distance with jitter into a reveal threshold per cell."""

    if not anchors:
        return [rng.random() for _cell in cells]
    distances = [
        min(math.hypot(cell.x - ax, (cell.y - ay) * EYE_DISTANCE_ROW_SCALE) for ax, ay in anchors)
        for cell in cells
    ]
    furthest = max(distances) or 1.0
    return [
        min(
            1.0,
            EYE_DISTANCE_WEIGHT * (distance / furthest)
            + (1.0 - EYE_DISTANCE_WEIGHT) * rng.random(),
        )
        for distance in distances
    ]


def _halo_cells(fitted_mask: FittedMask, *, reach: tuple[int, int]) -> frozenset[tuple[int, int]]:
    """Return terminal cells just outside the silhouette, in mask coordinates."""

    occupied = {(cell.x, cell.y) for cell in fitted_mask.cells}
    reach_x, reach_y = reach
    boundary = [
        (x, y)
        for x, y in occupied
        if any((x + dx, y + dy) not in occupied for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
    ]
    halo: set[tuple[int, int]] = set()
    for x, y in boundary:
        for dy in range(-reach_y, reach_y + 1):
            for dx in range(-reach_x, reach_x + 1):
                halo.add((x + dx, y + dy))
    return frozenset(halo - occupied)


class IdleFaceMotion:
    """Independent blink and discrete drift state for an otherwise fixed face."""

    def __init__(
        self,
        *,
        fps: float,
        seed: int | None,
        blink_interval: tuple[float, float] = BLINK_INTERVAL,
        drift_target_interval: tuple[float, float] = DRIFT_TARGET_INTERVAL,
        drift_step_interval: float = DRIFT_STEP_INTERVAL,
    ) -> None:
        if fps <= 0:
            raise ValueError("fps must be positive")
        if not 0 < blink_interval[0] <= blink_interval[1]:
            raise ValueError("blink_interval must contain positive ordered values")
        if not 0 < drift_target_interval[0] <= drift_target_interval[1]:
            raise ValueError("drift_target_interval must contain positive ordered values")
        if drift_step_interval <= 0:
            raise ValueError("drift_step_interval must be positive")

        self.rng = random.Random(_derived_seed(seed, 0xB11A))
        self.fps = fps
        self.blink_interval = blink_interval
        self.drift_target_interval = drift_target_interval
        self.drift_step_interval = drift_step_interval
        self.blinking = False
        self.offset = (0, 0)
        # Whole-face brightness sine, -1..1; the head stops looking like a print.
        self.breath = 0.0
        self._breath_phase = self.rng.random() * BREATH_PERIOD_SECONDS
        self._blink_remaining = 0.0
        self._next_blink = self.rng.uniform(*blink_interval)
        self._drift_target = (0, 0)
        self._next_drift_target = self.rng.uniform(*drift_target_interval)
        self._drift_step_accumulator = 0.0

    def update(self, dt: float) -> None:
        if dt < 0:
            raise ValueError("dt must not be negative")
        self._update_blink(dt)
        self._update_drift(dt)
        self._breath_phase = (self._breath_phase + dt) % BREATH_PERIOD_SECONDS
        self.breath = math.sin(2.0 * math.pi * self._breath_phase / BREATH_PERIOD_SECONDS)

    def nudge(self) -> None:
        """Jump one nearby cell for an occasional scan-linked glitch."""

        choices = tuple(
            target
            for target in DRIFT_TARGETS
            if target != self.offset
            and abs(target[0] - self.offset[0]) <= 1
            and abs(target[1] - self.offset[1]) <= 1
        )
        if choices:
            self.offset = self.rng.choice(choices)
            self._drift_target = self.offset
            self._next_drift_target = self.rng.uniform(*self.drift_target_interval)

    def _update_blink(self, dt: float) -> None:
        if self.blinking:
            self._blink_remaining -= dt
            if self._blink_remaining <= 0:
                self.blinking = False
                self._next_blink = self.rng.uniform(*self.blink_interval)
            return

        self._next_blink -= dt
        if self._next_blink <= 0:
            self.blinking = True
            self._blink_remaining = self.rng.choice(BLINK_FRAMES) / self.fps

    def _update_drift(self, dt: float) -> None:
        self._next_drift_target -= dt
        if self._next_drift_target <= 0:
            choices = tuple(target for target in DRIFT_TARGETS if target != self._drift_target)
            self._drift_target = self.rng.choice(choices)
            self._next_drift_target = self.rng.uniform(*self.drift_target_interval)

        self._drift_step_accumulator += dt
        while self._drift_step_accumulator >= self.drift_step_interval:
            self._drift_step_accumulator -= self.drift_step_interval
            self.offset = (
                _step_toward(self.offset[0], self._drift_target[0]),
                _step_toward(self.offset[1], self._drift_target[1]),
            )


class AmbientScanScheduler:
    """Occasionally trigger a visual scan without changing Jarvis state."""

    def __init__(
        self,
        *,
        seed: int | None,
        first_seconds: float = AMBIENT_SCAN_FIRST_SECONDS,
        min_seconds: float = AMBIENT_SCAN_MIN_SECONDS,
        max_seconds: float = AMBIENT_SCAN_MAX_SECONDS,
        double_chance: float = AMBIENT_SCAN_DOUBLE_CHANCE,
        sweep_seconds: float = AMBIENT_SCAN_SWEEP_SECONDS,
        double_gap_seconds: float = AMBIENT_SCAN_DOUBLE_GAP_SECONDS,
    ) -> None:
        if not math.isfinite(first_seconds) or first_seconds < 0:
            raise ValueError("ambient scan first delay must not be negative")
        if (
            not math.isfinite(min_seconds)
            or not math.isfinite(max_seconds)
            or min_seconds <= 0
            or max_seconds < min_seconds
        ):
            raise ValueError("ambient scan interval must contain positive ordered values")
        if not math.isfinite(double_chance) or not 0 <= double_chance <= 1:
            raise ValueError("ambient scan double chance must be between 0 and 1")
        if (
            not math.isfinite(sweep_seconds)
            or not math.isfinite(double_gap_seconds)
            or sweep_seconds <= 0
            or double_gap_seconds < 0
        ):
            raise ValueError("ambient scan sweep timing must be valid")

        self.rng = random.Random(_derived_seed(seed, 0x5CA7))
        self.first_seconds = first_seconds
        self.interval = (min_seconds, max_seconds)
        self.double_chance = double_chance
        self.sweep_seconds = sweep_seconds
        self.double_gap_seconds = double_gap_seconds
        self.phase: float | None = None
        self._visible = False
        self._active = False
        self._active_elapsed = 0.0
        self._countdown = first_seconds
        self._double_pending = False
        self._next_is_double = False

    def update(self, dt: float, *, face_visible: bool) -> tuple[float | None, bool]:
        """Return the current normalized sweep phase and whether to nudge."""

        if dt < 0:
            raise ValueError("dt must not be negative")
        if not face_visible:
            self._visible = False
            self._active = False
            self._active_elapsed = 0.0
            self._countdown = self.first_seconds
            self._double_pending = False
            self._next_is_double = False
            self.phase = None
            return None, False

        if not self._visible:
            self._visible = True
            self._countdown = self.first_seconds

        if self._active:
            self._active_elapsed += dt
            if self._active_elapsed < self.sweep_seconds:
                self.phase = self._active_elapsed / self.sweep_seconds
                return self.phase, False

            overshoot = self._active_elapsed - self.sweep_seconds
            self._active = False
            self._active_elapsed = 0.0
            self.phase = None
            if self._double_pending:
                self._countdown = self.double_gap_seconds - overshoot
                self._double_pending = False
                self._next_is_double = True
            else:
                self._countdown = self.rng.uniform(*self.interval) - overshoot
                self._next_is_double = False
        else:
            self._countdown -= dt

        if self._countdown > 1e-9:
            return None, False

        overshoot = max(0.0, -self._countdown)
        is_double = self._next_is_double
        self._next_is_double = False
        self._active = True
        self._active_elapsed = min(overshoot, self.sweep_seconds)
        if not is_double:
            self._double_pending = self.rng.random() < self.double_chance
        self.phase = self._active_elapsed / self.sweep_seconds
        return self.phase, is_double


class FaceVisibilityTransition:
    """Time-based face coalescence that reverses cleanly mid-transition."""

    def __init__(
        self,
        *,
        coalesce_seconds: float = FACE_COALESCE_SECONDS,
        dissipate_seconds: float = FACE_DISSIPATE_SECONDS,
        presence: float = DEFAULT_FACE_PRESENCE,
    ) -> None:
        if coalesce_seconds <= 0 or dissipate_seconds <= 0:
            raise ValueError("face transition durations must be positive")
        if not FACE_PRESENCE_RANGE[0] <= presence <= FACE_PRESENCE_RANGE[1]:
            raise ValueError("face presence must be between 0.3 and 1.0")
        self.coalesce_seconds = coalesce_seconds
        self.dissipate_seconds = dissipate_seconds
        self.presence = presence
        self.progress = 0.0

    def update(self, dt: float, *, target_visible: bool) -> float:
        if dt < 0:
            raise ValueError("dt must not be negative")
        if target_visible:
            self.progress = min(self.presence, self.progress + dt / self.coalesce_seconds)
        else:
            self.progress = max(0.0, self.progress - dt / self.dissipate_seconds)
        return self.progress


class DemoTimelinePlayer:
    """Loop a precomputed timeline with a neutral pause and no audio playback."""

    def __init__(self, timeline: VisemeTimeline, *, pause: float = DEMO_WAV_PAUSE) -> None:
        if pause < 0:
            raise ValueError("pause must not be negative")
        self.timeline = timeline
        self.pause = pause
        self.elapsed = -pause
        self.energy = 0.0

    def update(self, dt: float) -> MouthShape:
        if dt < 0:
            raise ValueError("dt must not be negative")
        self.elapsed += dt
        while self.elapsed >= self.timeline.duration:
            self.elapsed -= self.timeline.duration + self.pause
        self.energy = self.timeline.level_at(self.elapsed)
        return self.timeline.shape_at(self.elapsed)


class HeadScene:
    """Renderer-independent simulation: rain, face, motion, state, transitions.

    Both the curses and framebuffer renderers drive one of these per frame and
    read ``field``, ``drawn_face_layer``, ``face_offset``, and ``face_progress``.
    Nothing in here knows how a cell becomes pixels.
    """

    def __init__(
        self,
        *,
        height: int,
        width: int,
        preset: str,
        fps: float,
        seed: int | None,
        face_masks: SemanticFaceMasks | None,
        timeline: VisemeTimeline | None,
        cell_aspect: float,
        event_socket: HeadEventSocket | None,
        state_machine: HeadStateMachine | None,
        demo_thinking: bool = False,
        face_presence: float = DEFAULT_FACE_PRESENCE,
        ambient_scan: bool = False,
        ambient_scan_first_seconds: float = AMBIENT_SCAN_FIRST_SECONDS,
        ambient_scan_min_seconds: float = AMBIENT_SCAN_MIN_SECONDS,
        ambient_scan_max_seconds: float = AMBIENT_SCAN_MAX_SECONDS,
        ambient_scan_double_chance: float = AMBIENT_SCAN_DOUBLE_CHANCE,
    ) -> None:
        self.seed = seed
        self.face_masks = face_masks
        self.cell_aspect = cell_aspect
        self.event_socket = event_socket
        self.state_machine = state_machine
        self.demo_thinking = demo_thinking
        self.elapsed = 0.0
        self.speech_energy = 0.0
        self.scan_phase: float | None = None
        self.field = RainField(max(height, 1), max(width, 1), preset, seed=seed)
        self.fitted_faces = _fit_face_masks(face_masks, self.field, cell_aspect)
        self.face_layer = _new_face_layer(self.fitted_faces, seed)
        has_face = self.face_layer is not None
        self.motion = IdleFaceMotion(fps=fps, seed=seed) if has_face else None
        self.ambient_scan = (
            AmbientScanScheduler(
                seed=seed,
                first_seconds=ambient_scan_first_seconds,
                min_seconds=ambient_scan_min_seconds,
                max_seconds=ambient_scan_max_seconds,
                double_chance=ambient_scan_double_chance,
            )
            if has_face and ambient_scan
            else None
        )
        self.face_transition = (
            FaceVisibilityTransition(presence=face_presence) if has_face else None
        )
        self.timeline_player = DemoTimelinePlayer(timeline) if timeline is not None else None
        self.mouth_shape = MouthShape.REST
        self.face_visible = state_machine is None
        self.face_progress = 0.0
        self._current_expression: tuple[bool, MouthShape] = (False, MouthShape.REST)

    @property
    def blinking(self) -> bool:
        return self.motion.blinking if self.motion is not None else False

    @property
    def face_offset(self) -> tuple[int, int]:
        return self.motion.offset if self.motion is not None else (0, 0)

    @property
    def drawn_face_layer(self) -> FaceGlyphLayer | None:
        return self.face_layer if self.face_progress > 0 else None

    @property
    def breath(self) -> float:
        return self.motion.breath if self.motion is not None else 0.0

    @property
    def thinking(self) -> bool:
        if self.state_machine is not None:
            return self.state_machine.base_state is BaseState.THINK
        return self.demo_thinking

    def resize(self, height: int, width: int) -> None:
        """Rebuild the grid-sized parts; motion, state, and transition survive."""

        self.field.resize(max(height, 1), max(width, 1))
        self.fitted_faces = _fit_face_masks(self.face_masks, self.field, self.cell_aspect)
        self.face_layer = _new_face_layer(
            self.fitted_faces,
            self.seed,
            blinking=self.blinking,
            mouth=self.mouth_shape,
        )
        self._current_expression = (self.blinking, self.mouth_shape)

    def step(self, dt: float) -> None:
        if dt < 0:
            raise ValueError("dt must not be negative")
        self.elapsed += dt
        self.field.update(dt)
        if self.event_socket is not None and self.state_machine is not None:
            for event in self.event_socket.poll():
                self.state_machine.handle(
                    event,
                    now_wall=time.time(),
                    now_mono=time.monotonic(),
                )
            now_wall = time.time()
            self.state_machine.tick(now_wall=now_wall, now_mono=time.monotonic())
            self.mouth_shape = self.state_machine.mouth_shape(now_wall=now_wall)
            self.speech_energy = self.state_machine.mouth_energy(now_wall=now_wall)
            self.face_visible = self.state_machine.face_visible
        if self.face_layer is not None:
            self.face_layer.update(dt)
        if self.motion is not None:
            self.motion.update(dt)
        if self.ambient_scan is not None:
            self.scan_phase, nudge = self.ambient_scan.update(
                dt,
                face_visible=self.face_visible,
            )
            if nudge and self.motion is not None:
                self.motion.nudge()
        if self.timeline_player is not None:
            self.mouth_shape = self.timeline_player.update(dt)
            self.speech_energy = self.timeline_player.energy
        if self.face_transition is not None:
            self.face_progress = self.face_transition.update(
                dt,
                target_visible=self.face_visible,
            )

        desired = (self.blinking, self.mouth_shape)
        if (
            self.face_layer is not None
            and self.fitted_faces is not None
            and desired != self._current_expression
        ):
            self.face_layer.apply_mask(
                self.fitted_faces.get(blinking=desired[0], mouth=desired[1].value)
            )
            self._current_expression = desired


def run_display(
    *,
    preset: str = "kiosk",
    fps: float = DEFAULT_FPS,
    seed: int | None = None,
    color: str = "green",
    demo_face: bool = False,
    demo_wav: str | Path | None = None,
    asset_dir: str | Path | None = None,
    cell_aspect: float | None = DEFAULT_CELL_ASPECT,
    event_socket_path: str | Path | None = None,
    event_socket_default: bool = False,
    idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
    renderer: str = "curses",
    framebuffer_path: str | Path = DEFAULT_FRAMEBUFFER,
    font_path: str | Path | None = None,
    font_px: int = DEFAULT_FONT_PX,
    snapshot_path: str | Path | None = None,
    snapshot_at: float = DEFAULT_SNAPSHOT_AT,
    demo_think: bool = False,
    face_brightness: float = DEFAULT_FACE_BRIGHTNESS,
    face_presence: float = DEFAULT_FACE_PRESENCE,
    scan_levels: int = DEFAULT_SCAN_LEVELS,
    ambient_scan: bool = False,
    ambient_scan_first_seconds: float = AMBIENT_SCAN_FIRST_SECONDS,
    ambient_scan_min_seconds: float = AMBIENT_SCAN_MIN_SECONDS,
    ambient_scan_max_seconds: float = AMBIENT_SCAN_MAX_SECONDS,
    ambient_scan_double_chance: float = AMBIENT_SCAN_DOUBLE_CHANCE,
) -> None:
    """Run the standalone display and restore the terminal on every exit path."""

    if preset not in PRESETS:
        raise ValueError(f"unknown preset: {preset}")
    if not 1 <= fps <= 120:
        raise ValueError("fps must be between 1 and 120")
    if color not in COLOR_NAMES:
        raise ValueError(f"unknown color: {color}")
    if renderer not in RENDERERS:
        raise ValueError(f"unknown renderer: {renderer}")
    if cell_aspect is None:
        if renderer != "fb":
            raise ValueError("the curses renderer needs an explicit cell aspect")
    elif not 0.1 <= cell_aspect <= 2.0:
        raise ValueError("cell_aspect must be between 0.1 and 2.0")
    if idle_timeout <= 0:
        raise ValueError("idle timeout must be positive")
    if snapshot_path is not None and renderer != "fb":
        raise ValueError("snapshots need the framebuffer renderer")
    if snapshot_at < 0:
        raise ValueError("snapshot time must not be negative")
    if not FACE_BRIGHTNESS_RANGE[0] <= face_brightness <= FACE_BRIGHTNESS_RANGE[1]:
        raise ValueError("face_brightness must be between 0.2 and 1.5")
    if not FACE_PRESENCE_RANGE[0] <= face_presence <= FACE_PRESENCE_RANGE[1]:
        raise ValueError("face_presence must be between 0.3 and 1.0")
    scan_low, scan_high = SCAN_LEVELS_RANGE
    if isinstance(scan_levels, bool) or not isinstance(scan_levels, int):
        raise ValueError("scan_levels must be an integer")
    if not scan_low <= scan_levels <= scan_high:
        raise ValueError(f"scan_levels must be between {scan_low} and {scan_high}")
    if not math.isfinite(ambient_scan_first_seconds) or ambient_scan_first_seconds < 0:
        raise ValueError("ambient scan first delay must not be negative")
    if (
        not math.isfinite(ambient_scan_min_seconds)
        or not math.isfinite(ambient_scan_max_seconds)
        or ambient_scan_min_seconds <= 0
        or ambient_scan_max_seconds < ambient_scan_min_seconds
    ):
        raise ValueError("ambient scan interval must contain positive ordered values")
    if not math.isfinite(ambient_scan_double_chance) or not 0 <= ambient_scan_double_chance <= 1:
        raise ValueError("ambient scan double chance must be between 0 and 1")
    if demo_think:
        demo_face = True

    if asset_dir is None:
        asset_dir = Path(__file__).parent / "assets"
    face_masks = SemanticFaceMasks.from_directory(asset_dir)
    timeline = None
    if demo_wav is not None:
        timeline = analyze_wav(demo_wav)

    event_socket = None
    state_machine = None
    previous_handlers: dict[int, object] = {}
    try:
        if snapshot_path is None:
            # Every long-running display, demo or not, must turn `kiosk.sh stop`
            # (SIGTERM) or a console hangup into the KeyboardInterrupt path so
            # curses, the console palette, KD_GRAPHICS, and the framebuffer are
            # all restored.
            for signum in INTERRUPT_SIGNALS:
                previous_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, _interrupt_display)
        if not demo_face and demo_wav is None and snapshot_path is None:
            if event_socket_path is None:
                raise ValueError("normal display mode requires an event socket path")
            event_socket = HeadEventSocket(
                event_socket_path,
                default_path=event_socket_default,
            ).open()
            state_machine = HeadStateMachine(idle_timeout=idle_timeout)

        if renderer == "fb":
            # numpy and the atlas are only needed here; keep curses mode lean.
            from fb_render import render_snapshot, run_framebuffer_display

            def scene_factory(height: int, width: int, fitted_aspect: float) -> HeadScene:
                return HeadScene(
                    height=height,
                    width=width,
                    preset=preset,
                    fps=fps,
                    seed=seed,
                    face_masks=face_masks,
                    timeline=timeline,
                    cell_aspect=fitted_aspect if cell_aspect is None else cell_aspect,
                    event_socket=event_socket,
                    state_machine=state_machine,
                    demo_thinking=demo_think,
                    face_presence=face_presence,
                    ambient_scan=ambient_scan,
                    ambient_scan_first_seconds=ambient_scan_first_seconds,
                    ambient_scan_min_seconds=ambient_scan_min_seconds,
                    ambient_scan_max_seconds=ambient_scan_max_seconds,
                    ambient_scan_double_chance=ambient_scan_double_chance,
                )

            if snapshot_path is not None:
                render_snapshot(
                    scene_factory,
                    output=snapshot_path,
                    color=color,
                    fps=fps,
                    at_seconds=snapshot_at,
                    font_path=font_path,
                    font_px=font_px,
                    face_brightness=face_brightness,
                    scan_levels=scan_levels,
                )
            else:
                run_framebuffer_display(
                    scene_factory,
                    color=color,
                    fps=fps,
                    framebuffer_path=framebuffer_path,
                    font_path=font_path,
                    font_px=font_px,
                    face_brightness=face_brightness,
                    scan_levels=scan_levels,
                )
            return

        curses.wrapper(
            _run_loop,
            preset=preset,
            fps=fps,
            seed=seed,
            color=color,
            face_masks=face_masks,
            timeline=timeline,
            cell_aspect=cell_aspect,
            event_socket=event_socket,
            state_machine=state_machine,
            demo_think=demo_think,
            face_presence=face_presence,
            # The scan band is framebuffer choreography. Curses has no scan
            # compositor, so do not run its double-pass nudge there by itself.
            ambient_scan=False,
            ambient_scan_first_seconds=ambient_scan_first_seconds,
            ambient_scan_min_seconds=ambient_scan_min_seconds,
            ambient_scan_max_seconds=ambient_scan_max_seconds,
            ambient_scan_double_chance=ambient_scan_double_chance,
        )
    except KeyboardInterrupt:
        # curses.wrapper has already restored echo/cbreak/cursor state.
        return
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)  # type: ignore[arg-type]
        if event_socket is not None:
            event_socket.close()


def _run_loop(
    stdscr: curses.window,
    *,
    preset: str,
    fps: float,
    seed: int | None,
    color: str,
    face_masks: SemanticFaceMasks | None,
    timeline: VisemeTimeline | None,
    cell_aspect: float,
    event_socket: HeadEventSocket | None,
    state_machine: HeadStateMachine | None,
    demo_think: bool = False,
    face_presence: float = DEFAULT_FACE_PRESENCE,
    ambient_scan: bool = False,
    ambient_scan_first_seconds: float = AMBIENT_SCAN_FIRST_SECONDS,
    ambient_scan_min_seconds: float = AMBIENT_SCAN_MIN_SECONDS,
    ambient_scan_max_seconds: float = AMBIENT_SCAN_MAX_SECONDS,
    ambient_scan_double_chance: float = AMBIENT_SCAN_DOUBLE_CHANCE,
) -> None:
    try:
        curses.curs_set(0)
    except curses.error:
        pass

    stdscr.nodelay(True)
    stdscr.keypad(True)
    palette = RainPalette(stdscr, color)

    height, width = stdscr.getmaxyx()
    scene = HeadScene(
        height=height,
        width=width,
        preset=preset,
        fps=fps,
        seed=seed,
        face_masks=face_masks,
        timeline=timeline,
        cell_aspect=cell_aspect,
        event_socket=event_socket,
        state_machine=state_machine,
        demo_thinking=demo_think,
        face_presence=face_presence,
        ambient_scan=ambient_scan,
        ambient_scan_first_seconds=ambient_scan_first_seconds,
        ambient_scan_min_seconds=ambient_scan_min_seconds,
        ambient_scan_max_seconds=ambient_scan_max_seconds,
        ambient_scan_double_chance=ambient_scan_double_chance,
    )
    frame_interval = 1.0 / fps
    last_frame = time.monotonic()

    try:
        while True:
            frame_started = time.monotonic()
            dt = min(max(frame_started - last_frame, 0.0), MAX_FRAME_DT)
            last_frame = frame_started

            current_height, current_width = stdscr.getmaxyx()
            if (current_height, current_width) != (scene.field.height, scene.field.width):
                scene.resize(current_height, current_width)
                palette = RainPalette(stdscr, color)

            scene.step(dt)
            _draw_frame(
                stdscr,
                scene.field,
                palette,
                face_layer=scene.drawn_face_layer,
                face_offset=scene.face_offset,
                face_progress=scene.face_progress,
            )

            key = stdscr.getch()
            if key in (ord("q"), ord("Q"), 27):
                return
            if key == curses.KEY_RESIZE:
                curses.update_lines_cols()

            sleep_for = frame_interval - (time.monotonic() - frame_started)
            if sleep_for > 0:
                time.sleep(sleep_for)
    finally:
        # curses.wrapper restores tty modes, but it does not explicitly undo a
        # successful curs_set(0) on every implementation, and it only resets the
        # console palette slots it changed itself.
        palette.restore()
        try:
            curses.curs_set(1)
        except curses.error:
            pass


def _draw_frame(
    stdscr: curses.window,
    field: RainField,
    palette: RainPalette,
    *,
    face_layer: FaceGlyphLayer | None = None,
    face_offset: tuple[int, int] = (0, 0),
    face_progress: float = 1.0,
) -> None:
    stdscr.erase()
    offset_x, offset_y = face_offset
    face_cells: list[tuple[int, int, FaceGlyphCell]] = []
    covered: set[tuple[int, int]] = set()
    halo: frozenset[tuple[int, int]] = frozenset()
    if face_layer is not None:
        halo = face_layer.halo_at(face_offset)
        for cell in face_layer.visible_cells(face_progress):
            draw_x = cell.x + offset_x
            draw_y = cell.y + offset_y
            if 0 <= draw_x < field.width and 0 <= draw_y < field.height:
                face_cells.append((draw_x, draw_y, cell))
                covered.add((draw_x, draw_y))

    attribute_for = palette.attribute_for
    for cell in field.visible_cells():
        position = (cell.x, cell.y)
        if position in covered:
            continue
        try:
            stdscr.addch(
                cell.y,
                cell.x,
                cell.char,
                attribute_for(cell, dimmed=position in halo),
            )
        except curses.error:
            # Some curses implementations reject the bottom-right cell because
            # writing there would scroll. A resize can race one frame as well.
            continue

    for draw_x, draw_y, cell in face_cells:
        attribute = (
            palette.background if cell.value == 0 else palette.attribute_for_mask(cell.value)
        )
        try:
            stdscr.addch(draw_y, draw_x, cell.char, attribute)
        except curses.error:
            continue
    stdscr.noutrefresh()
    curses.doupdate()


def _fit_face_masks(
    face_masks: SemanticFaceMasks | None,
    field: RainField,
    cell_aspect: float,
) -> FittedFaceMasks | None:
    if face_masks is None:
        return None
    return face_masks.fit(
        field.height,
        field.width,
        cell_aspect=cell_aspect,
    )


def _new_face_layer(
    fitted_faces: FittedFaceMasks | None,
    seed: int | None,
    *,
    blinking: bool = False,
    mouth: MouthShape = MouthShape.REST,
) -> FaceGlyphLayer | None:
    if fitted_faces is None:
        return None
    mouth_anchor = _mouth_anchor(fitted_faces)
    return FaceGlyphLayer(
        fitted_faces.get(blinking=blinking, mouth=mouth.value),
        seed=seed,
        extra_anchors=() if mouth_anchor is None else (mouth_anchor,),
    )


def _mouth_anchor(fitted_faces: FittedFaceMasks) -> tuple[float, float] | None:
    """Centroid of the cells the mouth apertures change; None if they change none.

    The expression masks differ from `rest` only inside the authored mouth
    region, so the diff between `rest` and the open `ae` mouth is the mouth.
    """

    rest = fitted_faces.get(blinking=False, mouth="rest")
    open_mouth = fitted_faces.get(blinking=False, mouth="ae")
    changed = [
        (a.x, a.y)
        for a, b in zip(rest.cells, open_mouth.cells, strict=True)
        if (a.x, a.y) == (b.x, b.y) and a.value != b.value
    ]
    if not changed:
        return None
    return (
        sum(x for x, _y in changed) / len(changed),
        sum(y for _x, y in changed) / len(changed),
    )


def _derived_seed(seed: int | None, salt: int) -> int | None:
    return None if seed is None else seed ^ salt


def _step_toward(current: int, target: int) -> int:
    if current < target:
        return current + 1
    if current > target:
        return current - 1
    return current


def _interrupt_display(_signum: int, _frame: object) -> None:
    """Turn the first stop signal into KeyboardInterrupt and ignore the rest.

    `systemctl stop` signals the whole control group at once, and anything
    sitting between systemd and Python (a `runuser`, a shell trap) may forward
    the same SIGTERM again a moment later. A second KeyboardInterrupt raised
    while the first one is unwinding aborts the console-mode and framebuffer
    restore halfway and leaves the VT black, so after the first signal the
    cleanup runs to completion no matter what else arrives.
    """

    for signum in INTERRUPT_SIGNALS:
        signal.signal(signum, signal.SIG_IGN)
    raise KeyboardInterrupt
