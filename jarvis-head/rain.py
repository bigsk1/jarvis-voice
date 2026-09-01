"""Pure Matrix rain model for the Jarvis Head display.

The column lifecycle is adapted from bigsk1/matrix-crypto at commit
3c0f022e0a7a2f0bd5bc0200715a82869c1a219a:
https://github.com/bigsk1/matrix-crypto/blob/3c0f022e0a7a2f0bd5bc0200715a82869c1a219a/offline-version-no-prices/matrix_crypto.py

Crypto data, logging, argument parsing, and curses rendering intentionally stay
out of this module. Keeping the model pure makes fixed-seed behavior and resize
bounds testable without a terminal.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from dataclasses import dataclass

BACKGROUND_CHARS = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789"
    "!@#$%^&*()_+-=[]{}|;:,.<>?/\\"
)


@dataclass(frozen=True, slots=True)
class RainPreset:
    """Tunable values around the preserved Matrix column lifecycle."""

    name: str
    gap_pattern: tuple[int, ...]
    column_length_range: tuple[float, float]
    fall_speed_range: tuple[float, float]
    change_chance: float = 0.2
    intensity_levels: int = 3
    chars: str = BACKGROUND_CHARS

    def __post_init__(self) -> None:
        if not self.gap_pattern or any(gap < 0 for gap in self.gap_pattern):
            raise ValueError("gap_pattern must contain non-negative integers")
        length_min, length_max = self.column_length_range
        if not 0 < length_min <= length_max <= 1:
            raise ValueError("column_length_range must be within (0, 1]")
        speed_min, speed_max = self.fall_speed_range
        if not 0 < speed_min <= speed_max:
            raise ValueError("fall_speed_range values must be positive")
        if not 0 <= self.change_chance <= 1:
            raise ValueError("change_chance must be between 0 and 1")
        if self.intensity_levels < 1:
            raise ValueError("intensity_levels must be positive")
        if not self.chars:
            raise ValueError("chars must not be empty")


REFERENCE_PRESET = RainPreset(
    name="reference",
    gap_pattern=(1, 2, 3, 2),
    column_length_range=(0.3, 0.7),
    fall_speed_range=(0.06, 0.10),
)

KIOSK_PRESET = RainPreset(
    name="kiosk",
    gap_pattern=(0,),
    column_length_range=(0.72, 1.0),
    fall_speed_range=(0.045, 0.08),
    change_chance=0.16,
)

PRESETS: dict[str, RainPreset] = {
    REFERENCE_PRESET.name: REFERENCE_PRESET,
    KIOSK_PRESET.name: KIOSK_PRESET,
}


@dataclass(frozen=True, slots=True)
class RainCell:
    """One visible terminal cell produced by the rain model."""

    x: int
    y: int
    char: str
    intensity: int
    is_lead: bool


class MatrixColumn:
    """A single falling column, adapted from Matrix Crypto's stable model."""

    def __init__(
        self,
        height: int,
        preset: RainPreset,
        rng: random.Random,
        *,
        randomize_phase: bool = True,
    ) -> None:
        if height < 1:
            raise ValueError("height must be positive")

        self.height = height
        self.preset = preset
        self.rng = rng
        self.length = max(
            1,
            min(
                height,
                int(rng.uniform(*preset.column_length_range) * height),
            ),
        )
        self.chars = [" "] * height
        self.intensities = [1] * height
        self.speed = rng.uniform(*preset.fall_speed_range)
        self.counter = 0.0
        self.top = -self.length
        self._initialize_column()

        # Matrix Crypto starts every stream above the screen. A kiosk is normally
        # already in steady state, so distribute columns across their valid cycle
        # without changing the update/reset mechanics.
        if randomize_phase:
            self.top = rng.randrange(-self.length, self.height)

    def _initialize_column(self) -> None:
        for index in range(self.length):
            self.chars[index] = self.rng.choice(self.preset.chars)
            self.intensities[index] = self.rng.randint(1, self.preset.intensity_levels)

    def update(self, dt: float) -> None:
        """Advance by at most one row, preserving the upstream pacing behavior."""

        if dt < 0:
            raise ValueError("dt must not be negative")

        self.counter += dt
        if self.counter < self.speed:
            return

        self.counter = 0.0
        self.top += 1
        if self.top >= 0:
            self.chars.pop()
            self.intensities.pop()
            self.chars.insert(0, self.rng.choice(self.preset.chars))
            self.intensities.insert(
                0,
                self.rng.randint(1, self.preset.intensity_levels),
            )

        for index in range(min(self.length, self.height)):
            if self.rng.random() < self.preset.change_chance:
                self.chars[index] = self.rng.choice(self.preset.chars)
                self.intensities[index] = self.rng.randint(
                    1,
                    self.preset.intensity_levels,
                )

        if self.top >= self.height:
            self.top = -self.length
            self._initialize_column()

    def visible_cells(self) -> Iterator[tuple[int, str, int, bool]]:
        """Yield ``(y, char, intensity, is_lead)`` for visible nonblank cells."""

        visible_length = min(self.length, self.height - self.top)
        for y in range(self.height):
            source_index = y - self.top
            if not 0 <= source_index < visible_length:
                continue
            is_lead = source_index == visible_length - 1 and y < self.height - 1
            yield (
                y,
                self.chars[source_index],
                self.intensities[source_index],
                is_lead,
            )


class RainField:
    """Terminal-sized collection of columns with deterministic preset spacing."""

    def __init__(
        self,
        height: int,
        width: int,
        preset: str | RainPreset = KIOSK_PRESET,
        *,
        seed: int | None = None,
        rng: random.Random | None = None,
    ) -> None:
        if rng is not None and seed is not None:
            raise ValueError("pass either seed or rng, not both")
        self.preset = resolve_preset(preset)
        self.rng = rng if rng is not None else random.Random(seed)
        self.height = 0
        self.width = 0
        self.columns: list[tuple[int, MatrixColumn]] = []
        self.resize(height, width)

    @property
    def column_positions(self) -> tuple[int, ...]:
        return tuple(x for x, _column in self.columns)

    def resize(self, height: int, width: int) -> None:
        """Rebuild the field for a terminal resize."""

        if height < 1 or width < 1:
            raise ValueError("height and width must be positive")

        self.height = height
        self.width = width
        self.columns = [
            (x, MatrixColumn(height, self.preset, self.rng))
            for x in _column_positions(width, self.preset.gap_pattern)
        ]

    def update(self, dt: float) -> None:
        for _x, column in self.columns:
            column.update(dt)

    def visible_cells(self) -> Iterator[RainCell]:
        for x, column in self.columns:
            for y, char, intensity, is_lead in column.visible_cells():
                yield RainCell(
                    x=x,
                    y=y,
                    char=char,
                    intensity=intensity,
                    is_lead=is_lead,
                )


def resolve_preset(preset: str | RainPreset) -> RainPreset:
    if isinstance(preset, RainPreset):
        return preset
    try:
        return PRESETS[preset]
    except KeyError as exc:
        choices = ", ".join(sorted(PRESETS))
        raise ValueError(f"unknown rain preset {preset!r}; choose from {choices}") from exc


def _column_positions(width: int, gap_pattern: tuple[int, ...]) -> Iterator[int]:
    x = 0
    gap_index = 0
    while x < width:
        yield x
        gap = gap_pattern[gap_index % len(gap_pattern)]
        x += 1 + gap
        gap_index += 1
