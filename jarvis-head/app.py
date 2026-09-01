"""Curses application for the standalone Jarvis Head display."""

from __future__ import annotations

import curses
import random
import signal
import time
from dataclasses import dataclass
from pathlib import Path

from head_socket import HeadEventSocket
from head_state import DEFAULT_IDLE_TIMEOUT, HeadStateMachine
from mask import DEFAULT_CELL_ASPECT, FittedFaceMasks, FittedMask, SemanticFaceMasks
from rain import BACKGROUND_CHARS, PRESETS, RainCell, RainField
from visemes import MouthShape, VisemeTimeline, analyze_wav

DEFAULT_FPS = 30.0
MAX_FRAME_DT = 0.25
FACE_GLYPH_TICK = 0.1
FACE_GLYPH_CHANGE_CHANCE = 0.12
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
    """Explicit black-background attributes for the available terminal colors."""

    def __init__(self, stdscr: curses.window, color: str) -> None:
        self.has_colors = curses.has_colors()
        if self.has_colors:
            curses.start_color()
            foreground = COLOR_NAMES[color]
            curses.init_pair(1, foreground, curses.COLOR_BLACK)
            curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_BLACK)
            self.background = curses.color_pair(1)
            self.levels = (
                curses.color_pair(1) | curses.A_DIM,
                curses.color_pair(1),
                curses.color_pair(1) | curses.A_BOLD,
            )
            self.lead = curses.color_pair(2) | curses.A_BOLD
        else:
            self.background = curses.A_NORMAL
            self.levels = (curses.A_DIM, curses.A_NORMAL, curses.A_BOLD)
            self.lead = curses.A_BOLD

        # An explicit black background keeps terminal transparency settings from
        # exposing whatever window happens to sit behind the kiosk.
        stdscr.bkgd(" ", self.background)

    def attribute_for(self, cell: RainCell) -> int:
        if cell.is_lead:
            return self.lead
        index = min(max(cell.intensity, 1), len(self.levels)) - 1
        return self.levels[index]

    def attribute_for_mask(self, value: int) -> int:
        """Map every semantic face intensity to the selected color planes."""

        if value >= 175:
            return self.levels[2]
        if value >= 90:
            return self.levels[1]
        return self.levels[0]


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
    ) -> None:
        if tick_interval <= 0:
            raise ValueError("tick_interval must be positive")
        if not 0 <= change_chance <= 1:
            raise ValueError("change_chance must be between 0 and 1")

        self.rng = random.Random(seed)
        self.tick_interval = tick_interval
        self.change_chance = change_chance
        self.accumulator = 0.0
        self.cells = [
            FaceGlyphCell(
                x=cell.x,
                y=cell.y,
                value=cell.value,
                char=" " if cell.value == 0 else self.rng.choice(BACKGROUND_CHARS),
            )
            for cell in fitted_mask.cells
        ]
        transition_rng = random.Random(_derived_seed(seed, 0xC0A1))
        self._transition_points = [transition_rng.random() for _cell in self.cells]

    def update(self, dt: float) -> None:
        """Change scattered glyphs on a slower cadence than the rain."""

        if dt < 0:
            raise ValueError("dt must not be negative")
        self.accumulator += dt
        while self.accumulator >= self.tick_interval:
            self.accumulator -= self.tick_interval
            for cell in self.cells:
                if cell.value > 0 and self.rng.random() < self.change_chance:
                    cell.char = self._replacement_char(cell.char)

    def apply_mask(self, fitted_mask: FittedMask) -> None:
        """Change expression intensities without resetting the glyph field."""

        if len(fitted_mask.cells) != len(self.cells):
            raise ValueError("expression masks must have identical coverage")
        for glyph_cell, mask_cell in zip(self.cells, fitted_mask.cells, strict=True):
            if (glyph_cell.x, glyph_cell.y) != (mask_cell.x, mask_cell.y):
                raise ValueError("expression masks must have aligned cells")
            was_dark = glyph_cell.value == 0
            glyph_cell.value = mask_cell.value
            if mask_cell.value == 0:
                glyph_cell.char = " "
            elif was_dark:
                glyph_cell.char = self.rng.choice(BACKGROUND_CHARS)

    def visible_cells(self, progress: float):
        """Yield a deterministic scattered subset for coalescence/dissipation."""

        if not 0 <= progress <= 1:
            raise ValueError("face visibility progress must be between 0 and 1")
        eased = progress * progress * (3.0 - 2.0 * progress)
        for cell, transition_point in zip(
            self.cells,
            self._transition_points,
            strict=True,
        ):
            if transition_point < eased:
                yield cell

    def _replacement_char(self, current: str) -> str:
        replacement = self.rng.choice(BACKGROUND_CHARS)
        if replacement == current:
            index = (BACKGROUND_CHARS.index(replacement) + 1) % len(BACKGROUND_CHARS)
            replacement = BACKGROUND_CHARS[index]
        return replacement


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


class FaceVisibilityTransition:
    """Time-based face coalescence that reverses cleanly mid-transition."""

    def __init__(
        self,
        *,
        coalesce_seconds: float = FACE_COALESCE_SECONDS,
        dissipate_seconds: float = FACE_DISSIPATE_SECONDS,
    ) -> None:
        if coalesce_seconds <= 0 or dissipate_seconds <= 0:
            raise ValueError("face transition durations must be positive")
        self.coalesce_seconds = coalesce_seconds
        self.dissipate_seconds = dissipate_seconds
        self.progress = 0.0

    def update(self, dt: float, *, target_visible: bool) -> float:
        if dt < 0:
            raise ValueError("dt must not be negative")
        if target_visible:
            self.progress = min(1.0, self.progress + dt / self.coalesce_seconds)
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

    def update(self, dt: float) -> MouthShape:
        if dt < 0:
            raise ValueError("dt must not be negative")
        self.elapsed += dt
        while self.elapsed >= self.timeline.duration:
            self.elapsed -= self.timeline.duration + self.pause
        return self.timeline.shape_at(self.elapsed)


def run_display(
    *,
    preset: str = "kiosk",
    fps: float = DEFAULT_FPS,
    seed: int | None = None,
    color: str = "green",
    demo_face: bool = False,
    demo_wav: str | Path | None = None,
    asset_dir: str | Path | None = None,
    cell_aspect: float = DEFAULT_CELL_ASPECT,
    event_socket_path: str | Path | None = None,
    event_socket_default: bool = False,
    idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
) -> None:
    """Run the standalone display and restore the terminal on every exit path."""

    if preset not in PRESETS:
        raise ValueError(f"unknown preset: {preset}")
    if not 1 <= fps <= 120:
        raise ValueError("fps must be between 1 and 120")
    if color not in COLOR_NAMES:
        raise ValueError(f"unknown color: {color}")
    if not 0.1 <= cell_aspect <= 2.0:
        raise ValueError("cell_aspect must be between 0.1 and 2.0")
    if idle_timeout <= 0:
        raise ValueError("idle timeout must be positive")

    if asset_dir is None:
        asset_dir = Path(__file__).parent / "assets"
    face_masks = SemanticFaceMasks.from_directory(asset_dir)
    timeline = None
    if demo_wav is not None:
        timeline = analyze_wav(demo_wav)

    event_socket = None
    state_machine = None
    previous_sigterm = None
    try:
        if not demo_face and demo_wav is None:
            if event_socket_path is None:
                raise ValueError("normal display mode requires an event socket path")
            previous_sigterm = signal.getsignal(signal.SIGTERM)
            signal.signal(signal.SIGTERM, _interrupt_display)
            event_socket = HeadEventSocket(
                event_socket_path,
                default_path=event_socket_default,
            ).open()
            state_machine = HeadStateMachine(idle_timeout=idle_timeout)

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
        )
    except KeyboardInterrupt:
        # curses.wrapper has already restored echo/cbreak/cursor state.
        return
    finally:
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)
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
) -> None:
    try:
        curses.curs_set(0)
    except curses.error:
        pass

    stdscr.nodelay(True)
    stdscr.keypad(True)
    palette = RainPalette(stdscr, color)

    height, width = stdscr.getmaxyx()
    field = RainField(max(height, 1), max(width, 1), preset, seed=seed)
    fitted_faces = _fit_face_masks(face_masks, field, cell_aspect)
    face_layer = _new_face_layer(fitted_faces, seed)
    motion = IdleFaceMotion(fps=fps, seed=seed) if face_layer is not None else None
    face_transition = FaceVisibilityTransition() if face_layer is not None else None
    timeline_player = DemoTimelinePlayer(timeline) if timeline is not None else None
    mouth_shape = MouthShape.REST
    face_visible = state_machine is None
    current_expression = (False, mouth_shape)
    frame_interval = 1.0 / fps
    last_frame = time.monotonic()

    try:
        while True:
            frame_started = time.monotonic()
            dt = min(max(frame_started - last_frame, 0.0), MAX_FRAME_DT)
            last_frame = frame_started

            current_height, current_width = stdscr.getmaxyx()
            if (current_height, current_width) != (field.height, field.width):
                field.resize(max(current_height, 1), max(current_width, 1))
                fitted_faces = _fit_face_masks(face_masks, field, cell_aspect)
                face_layer = _new_face_layer(
                    fitted_faces,
                    seed,
                    blinking=motion.blinking if motion is not None else False,
                    mouth=mouth_shape,
                )
                current_expression = (
                    motion.blinking if motion is not None else False,
                    mouth_shape,
                )
                palette = RainPalette(stdscr, color)

            field.update(dt)
            if event_socket is not None and state_machine is not None:
                for event in event_socket.poll():
                    state_machine.handle(
                        event,
                        now_wall=time.time(),
                        now_mono=time.monotonic(),
                    )
                state_machine.tick(
                    now_wall=time.time(),
                    now_mono=time.monotonic(),
                )
                mouth_shape = state_machine.mouth_shape(now_wall=time.time())
                face_visible = state_machine.face_visible
            if face_layer is not None:
                face_layer.update(dt)
            if motion is not None:
                motion.update(dt)
            if timeline_player is not None:
                mouth_shape = timeline_player.update(dt)
            face_progress = (
                face_transition.update(dt, target_visible=face_visible)
                if face_transition is not None
                else 0.0
            )

            desired_expression = (
                motion.blinking if motion is not None else False,
                mouth_shape,
            )
            if (
                face_layer is not None
                and fitted_faces is not None
                and desired_expression != current_expression
            ):
                face_layer.apply_mask(
                    fitted_faces.get(
                        blinking=desired_expression[0],
                        mouth=desired_expression[1].value,
                    )
                )
                current_expression = desired_expression

            _draw_frame(
                stdscr,
                field,
                palette,
                face_layer=face_layer if face_progress > 0 else None,
                face_offset=motion.offset if motion is not None else (0, 0),
                face_progress=face_progress,
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
        # successful curs_set(0) on every implementation.
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
    for cell in field.visible_cells():
        try:
            stdscr.addch(
                cell.y,
                cell.x,
                cell.char,
                palette.attribute_for(cell),
            )
        except curses.error:
            # Some curses implementations reject the bottom-right cell because
            # writing there would scroll. A resize can race one frame as well.
            continue

    if face_layer is not None:
        for cell in face_layer.visible_cells(face_progress):
            draw_x = cell.x + face_offset[0]
            draw_y = cell.y + face_offset[1]
            if not 0 <= draw_x < field.width or not 0 <= draw_y < field.height:
                continue
            attribute = (
                palette.background
                if cell.value == 0
                else palette.attribute_for_mask(cell.value)
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
    return FaceGlyphLayer(
        fitted_faces.get(blinking=blinking, mouth=mouth.value),
        seed=seed,
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
    raise KeyboardInterrupt
