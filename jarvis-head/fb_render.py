"""Framebuffer renderer: the same cell grid as curses, composed with numpy.

The scene still thinks in cells. This module turns a cell grid into pixels by
gathering from a per-brightness packed glyph atlas, so a frame is one fancy
index plus one copy into the device. Rendering into an image instead of the
device gives deterministic snapshots for review and tests.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from fbdev import (
    ConsoleGraphicsMode,
    Framebuffer,
    FramebufferError,
    RawKeyboard,
    controlling_console,
)
from glyphs import GlyphAtlas, resolve_font_path
from palette import (
    BASE_HUES,
    DEFAULT_FACE_BRIGHTNESS,
    FACE_BRIGHTNESS_RANGE,
    build_ramp,
    face_shade_index,
    rain_shade_index,
)
from PIL import Image

LEVELS = 256
# One "shade step" of the 14-shade console ramp, expressed in 256-level units.
HALO_DIM_LEVELS = 18
MAX_FRAME_DT = 0.25
DEFAULT_SNAPSHOT_SIZE = (1920, 1080)
BGRX_OFFSETS = (16, 8, 0)

# Choreography (Phase 8). Everything below is in 256-level ramp units or in
# per-frame decay factors tuned at the default 30 FPS.
#
# Coalesce: a cell's brightness ramps from the rain under it to its face level
# over a window of the eased progress, so the head condenses out of the field
# instead of popping in as scattered glyphs. Eyes have the lowest thresholds.
REVEAL_WIDTH = 0.35
# Whole-face breathing amplitude (the scene supplies a -1..1 sine).
BREATH_LEVELS = 6
# A rain lead crossing the face lights the skin it passes and the glow decays:
# a raindrop on a hologram. Rain leads also leave a phosphor trail in the field.
RIPPLE_LEVELS = 48
SKIN_GLOW_DECAY = 0.78
AFTERGLOW_LEVELS = 36
RAIN_AFTERGLOW_DECAY = 0.55
# THINK: a bright band sweeps down the face once per period.
SCAN_PERIOD_SECONDS = 1.2
SCAN_LEVELS = 72
SCAN_HALF_WIDTH_ROWS = 2.5
# Speech loudness pulses the lower face; the aperture mask still does the mouth.
SPEECH_LEVELS = 40
SPEECH_LOWER_FACE_START = 0.55
SPEECH_RAMP_FRACTION = 0.15


class FaceCellLike(Protocol):
    x: int
    y: int
    value: int
    char: str


class FaceLayerLike(Protocol):
    cells: Sequence[FaceCellLike]
    transition_points: Sequence[float]
    version: int  # increments whenever any cell's value or glyph changes

    def eased_progress(self, progress: float) -> float: ...

    def halo_at(self, offset: tuple[int, int]) -> frozenset[tuple[int, int]]: ...


class SceneLike(Protocol):
    field: object
    face_progress: float
    face_offset: tuple[int, int]
    drawn_face_layer: FaceLayerLike | None
    # Choreography inputs; read with defaults so a bare scene still renders.
    breath: float
    thinking: bool
    elapsed: float
    speech_energy: float

    def step(self, dt: float) -> None: ...


SceneFactory = Callable[[int, int, float], SceneLike]


@dataclass(slots=True)
class _FaceGeometry:
    """Per-layer constants: mask-space positions, reveal thresholds, row bounds."""

    layer: FaceLayerLike
    xs: np.ndarray
    ys: np.ndarray
    points: np.ndarray
    top: int
    height: int
    content_version: int = -1
    values: np.ndarray | None = None
    glyph_ids: np.ndarray | None = None


class FrameComposer:
    """Turn one scene state into a packed ``uint32`` pixel frame."""

    def __init__(
        self,
        atlas: GlyphAtlas,
        *,
        color: str,
        rows: int,
        cols: int,
        channel_offsets: tuple[int, int, int] = BGRX_OFFSETS,
        face_brightness: float = DEFAULT_FACE_BRIGHTNESS,
    ) -> None:
        if rows < 1 or cols < 1:
            raise ValueError("the grid needs at least one row and one column")
        low, high = FACE_BRIGHTNESS_RANGE
        if not low <= face_brightness <= high:
            raise ValueError(f"face_brightness must be between {low} and {high}")
        self.atlas = atlas
        self.rows = rows
        self.cols = cols
        self.channel_offsets = channel_offsets
        self.face_brightness = face_brightness
        self.lut = np.asarray(build_ramp(BASE_HUES[color], LEVELS), dtype=np.uint32)
        self.packed = _pack_atlas(atlas.alphas, self.lut, channel_offsets)
        self.rain_levels = np.asarray(
            [rain_shade_index(level, False, LEVELS) for level in (1, 1, 2, 3)],
            dtype=np.int16,
        )
        self.lead_level = rain_shade_index(3, True, LEVELS)
        # Operator gain scales the face's position above the ramp floor so the
        # darkest skin stays put and highlights move; value 0 stays the hole.
        floor = face_shade_index(0, LEVELS)
        self.face_levels = np.asarray(
            [
                min(
                    LEVELS - 1,
                    round(floor + (face_shade_index(value, LEVELS) - floor) * face_brightness),
                )
                for value in range(256)
            ],
            dtype=np.int16,
        )
        self.glyph_grid = np.zeros((rows, cols), np.int16)
        self.level_grid = np.zeros((rows, cols), np.int16)
        self.lead_grid = np.zeros((rows, cols), bool)
        self.rain_glow = np.zeros((rows, cols), np.float32)
        self.skin_glow = np.zeros((rows, cols), np.float32)
        self._halo_cache: tuple[object, tuple[int, int], np.ndarray, np.ndarray] | None = None
        self._geometry: _FaceGeometry | None = None
        width, height = self.pixel_size
        self._frame = np.zeros((height, width), np.uint32)
        # Same memory viewed as (rows, cell_h, cols, cell_w): assigning the
        # transposed per-cell blocks into it lands pixels in scanline order.
        self._frame_cells = self._frame.reshape(rows, atlas.cell_height, cols, atlas.cell_width)

    @property
    def pixel_size(self) -> tuple[int, int]:
        return self.cols * self.atlas.cell_width, self.rows * self.atlas.cell_height

    def compose(self, scene: SceneLike) -> np.ndarray:
        glyph = self.glyph_grid
        level = self.level_grid
        lead = self.lead_grid
        glyph.fill(0)
        level.fill(0)
        lead.fill(False)

        rain_levels = self.rain_levels
        for x, span in scene.field.visible_spans():  # type: ignore[attr-defined]
            glyph[span.y_start : span.y_end, x] = self.atlas.indices("".join(span.chars))
            level[span.y_start : span.y_end, x] = rain_levels.take(span.intensities, mode="clip")
            if span.lead_y is not None:
                level[span.lead_y, x] = self.lead_level
                lead[span.lead_y, x] = True

        # Phosphor: the cell a lead just left stays hot and decays over a few
        # frames, so streams leave a trail instead of stepping. Whole-array
        # arithmetic; the trail mask is "drawn and not currently a lead".
        glow = self.rain_glow
        glow *= RAIN_AFTERGLOW_DECAY
        glow[lead] = 1.0
        bump = (glow * AFTERGLOW_LEVELS).astype(np.int16)
        bump *= (glyph != 0) & ~lead
        level += bump
        np.minimum(level, LEVELS - 1, out=level)

        self.skin_glow *= SKIN_GLOW_DECAY
        face_layer = scene.drawn_face_layer
        if face_layer is not None:
            self._apply_face(face_layer, scene)

        # Gather one (cell_h, cell_w) block per cell, then scatter the blocks
        # into scanline order. Two index arrays over 17k cells beats a
        # four-array gather over 2M pixels by 3-4x.
        blocks = self.packed[level, glyph]
        self._frame_cells[...] = blocks.transpose(0, 2, 1, 3)
        return self._frame

    def to_image(self, frame: np.ndarray) -> Image.Image:
        red_offset, green_offset, blue_offset = self.channel_offsets
        rgb = np.stack(
            [
                (frame >> red_offset) & 0xFF,
                (frame >> green_offset) & 0xFF,
                (frame >> blue_offset) & 0xFF,
            ],
            axis=-1,
        ).astype(np.uint8)
        return Image.fromarray(rgb, "RGB")

    def _apply_face(self, face_layer: FaceLayerLike, scene: SceneLike) -> None:
        offset_x, offset_y = scene.face_offset
        halo_x, halo_y = self._halo_arrays(face_layer, scene.face_offset)
        if halo_x.size:
            self.level_grid[halo_y, halo_x] = np.maximum(
                self.level_grid[halo_y, halo_x] - HALO_DIM_LEVELS, 0
            )

        geometry = self._face_geometry(face_layer)
        eased = face_layer.eased_progress(scene.face_progress)
        alpha = np.clip((eased * (1.0 + REVEAL_WIDTH) - geometry.points) / REVEAL_WIDTH, 0.0, 1.0)
        xs = geometry.xs + offset_x
        ys = geometry.ys + offset_y
        active = (alpha > 0) & (xs >= 0) & (xs < self.cols) & (ys >= 0) & (ys < self.rows)
        if not active.any():
            return
        values, glyph_ids = self._face_content(face_layer, geometry)

        xs = xs[active]
        ys = ys[active]
        alpha = alpha[active]
        values = values[active]
        glyph_ids = glyph_ids[active]
        mask_rows = geometry.ys[active]
        skin = values > 0

        # Rain passing through skin: a lead under a lit face cell lights it.
        hit = skin & self.lead_grid[ys, xs]
        if hit.any():
            self.skin_glow[ys[hit], xs[hit]] = 1.0

        target = self.face_levels[values].astype(np.float32)
        target += getattr(scene, "breath", 0.0) * BREATH_LEVELS
        target += self.skin_glow[ys, xs] * RIPPLE_LEVELS
        if getattr(scene, "thinking", False):
            phase = (getattr(scene, "elapsed", 0.0) % SCAN_PERIOD_SECONDS) / SCAN_PERIOD_SECONDS
            scan_row = geometry.top - 1 + phase * (geometry.height + 2)
            target += SCAN_LEVELS * np.clip(
                1.0 - np.abs(mask_rows - scan_row) / SCAN_HALF_WIDTH_ROWS, 0.0, 1.0
            )
        energy = getattr(scene, "speech_energy", 0.0)
        if energy > 0:
            lower_start = geometry.top + SPEECH_LOWER_FACE_START * geometry.height
            ramp_rows = max(1.0, SPEECH_RAMP_FRACTION * geometry.height)
            target += (
                energy * SPEECH_LEVELS * np.clip((mask_rows - lower_start) / ramp_rows, 0.0, 1.0)
            )
        target = np.where(skin, np.clip(target, 0, LEVELS - 1), 0.0)

        # Brightness lerps from the rain underneath to the face; the glyph
        # switches to the face's halfway through, or at once where there is no
        # rain glyph to hand over from (nothing pops in at half brightness).
        rain_under = self.level_grid[ys, xs].astype(np.float32)
        mixed = rain_under * (1.0 - alpha) + target * alpha
        self.level_grid[ys, xs] = np.rint(mixed).astype(np.int16)
        take_face_glyph = (alpha >= 0.5) | (self.glyph_grid[ys, xs] == 0)
        self.glyph_grid[ys[take_face_glyph], xs[take_face_glyph]] = glyph_ids[take_face_glyph]

    def _face_content(
        self, face_layer: FaceLayerLike, geometry: _FaceGeometry
    ) -> tuple[np.ndarray, np.ndarray]:
        """Per-cell values and glyph ids, rebuilt only when the layer's version moves.

        Glyph churn ticks every 0.1 s and expressions change rarely, so most
        frames reuse the arrays instead of walking ~5k cells in Python.
        """

        version = face_layer.version
        if geometry.content_version != version or geometry.values is None:
            cells = face_layer.cells
            geometry.values = np.fromiter(
                (cell.value for cell in cells), dtype=np.int16, count=len(cells)
            )
            geometry.glyph_ids = self.atlas.indices("".join(cell.char for cell in cells))
            geometry.content_version = version
        assert geometry.values is not None and geometry.glyph_ids is not None
        return geometry.values, geometry.glyph_ids

    def _face_geometry(self, face_layer: FaceLayerLike) -> _FaceGeometry:
        geometry = self._geometry
        if geometry is not None and geometry.layer is face_layer:
            return geometry
        cells = face_layer.cells
        ys = np.fromiter((cell.y for cell in cells), dtype=np.int64, count=len(cells))
        lit_rows = [cell.y for cell in cells if cell.value > 0] or [0]
        top = min(lit_rows)
        geometry = _FaceGeometry(
            layer=face_layer,
            xs=np.fromiter((cell.x for cell in cells), dtype=np.int64, count=len(cells)),
            ys=ys,
            points=np.asarray(face_layer.transition_points, dtype=np.float32),
            top=top,
            height=max(1, max(lit_rows) - top + 1),
        )
        self._geometry = geometry
        self.skin_glow.fill(0.0)
        return geometry

    def _halo_arrays(
        self,
        face_layer: FaceLayerLike,
        offset: tuple[int, int],
    ) -> tuple[np.ndarray, np.ndarray]:
        cached = self._halo_cache
        if cached is not None and cached[0] is face_layer and cached[1] == offset:
            return cached[2], cached[3]
        cells = [
            (x, y)
            for x, y in face_layer.halo_at(offset)
            if 0 <= x < self.cols and 0 <= y < self.rows
        ]
        halo_x = np.asarray([x for x, _y in cells], dtype=np.intp)
        halo_y = np.asarray([y for _x, y in cells], dtype=np.intp)
        self._halo_cache = (face_layer, offset, halo_x, halo_y)
        return halo_x, halo_y


def _pack_atlas(
    alphas: np.ndarray,
    lut: np.ndarray,
    channel_offsets: tuple[int, int, int],
) -> np.ndarray:
    """Return ``(levels, glyphs, cell_h, cell_w)`` packed pixels for every shade."""

    coverage = alphas.astype(np.uint32)[None, :, :, :]
    packed = np.zeros((lut.shape[0], *alphas.shape), dtype=np.uint32)
    for channel, shift in enumerate(channel_offsets):
        intensity = lut[:, channel][:, None, None, None]
        # Exact 0-255 scaling so full coverage at full intensity stays 255.
        packed |= ((coverage * intensity + 127) // 255) << shift
    return packed


def grid_for(atlas: GlyphAtlas, width: int, height: int) -> tuple[int, int, int, int]:
    """Return ``(rows, cols, x_origin, y_origin)`` for a centered cell grid."""

    cols = max(1, width // atlas.cell_width)
    rows = max(1, height // atlas.cell_height)
    x_origin = (width - cols * atlas.cell_width) // 2
    y_origin = (height - rows * atlas.cell_height) // 2
    return rows, cols, x_origin, y_origin


def render_snapshot(
    scene_factory: SceneFactory,
    *,
    output: str | Path,
    color: str,
    fps: float,
    at_seconds: float,
    font_path: str | Path | None,
    font_px: int,
    face_brightness: float = DEFAULT_FACE_BRIGHTNESS,
    size: tuple[int, int] = DEFAULT_SNAPSHOT_SIZE,
) -> Path:
    """Simulate ``at_seconds`` with a fixed step and write one PNG. No device needed."""

    atlas = GlyphAtlas(resolve_font_path(font_path), font_px)
    width, height = size
    rows, cols, x_origin, y_origin = grid_for(atlas, width, height)
    composer = FrameComposer(
        atlas, color=color, rows=rows, cols=cols, face_brightness=face_brightness
    )
    scene = scene_factory(rows, cols, atlas.cell_aspect)

    dt = 1.0 / fps
    for _ in range(round(at_seconds * fps)):
        scene.step(dt)
    frame = composer.compose(scene)

    canvas = Image.new("RGB", (width, height), (0, 0, 0))
    canvas.paste(composer.to_image(frame), (x_origin, y_origin))
    output_path = Path(output)
    canvas.save(output_path, format="PNG")
    return output_path


def run_framebuffer_display(
    scene_factory: SceneFactory,
    *,
    color: str,
    fps: float,
    framebuffer_path: str | Path,
    font_path: str | Path | None,
    font_px: int,
    face_brightness: float = DEFAULT_FACE_BRIGHTNESS,
) -> None:
    """Drive the scene onto the physical framebuffer until a quit key or signal."""

    console = controlling_console()
    if console is None:
        raise FramebufferError(
            "the framebuffer renderer needs a Linux virtual console; "
            "start it with bin/kiosk.sh, or use --snapshot to render a PNG"
        )
    atlas = GlyphAtlas(resolve_font_path(font_path), font_px)
    framebuffer = Framebuffer(framebuffer_path)
    try:
        info = framebuffer.info
        rows, cols, x_origin, y_origin = grid_for(atlas, info.width, info.height)
        composer = FrameComposer(
            atlas,
            color=color,
            rows=rows,
            cols=cols,
            channel_offsets=(info.red_offset, info.green_offset, info.blue_offset),
            face_brightness=face_brightness,
        )
        scene = scene_factory(rows, cols, atlas.cell_aspect)
        frame_interval = 1.0 / fps
        graphics_mode = ConsoleGraphicsMode(sys.stdin.fileno(), console_path=console)
        with graphics_mode:
            try:
                with RawKeyboard() as keyboard:
                    framebuffer.clear()
                    last_frame = time.monotonic()
                    while True:
                        frame_started = time.monotonic()
                        dt = min(max(frame_started - last_frame, 0.0), MAX_FRAME_DT)
                        last_frame = frame_started

                        scene.step(dt)
                        framebuffer.present(composer.compose(scene), x=x_origin, y=y_origin)

                        if keyboard.quit_requested():
                            return
                        sleep_for = frame_interval - (time.monotonic() - frame_started)
                        if sleep_for > 0:
                            time.sleep(sleep_for)
            finally:
                # Blank while still in KD_GRAPHICS. Leaving graphics mode makes
                # fbcon redraw the text console, and a blank after that would
                # wipe the redraw and leave the panel black until a key is hit.
                framebuffer.clear()
    finally:
        framebuffer.close()
