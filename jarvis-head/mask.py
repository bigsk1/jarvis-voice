"""Authored semantic-mask fitting for the Jarvis Head terminal renderer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import Image

DEFAULT_CELL_ASPECT = 0.4
DEFAULT_FACE_SCALE = 0.9
BACKGROUND_CUTOFF = 10
EYE_REGION = (126, 163, 387, 276)
MOUTH_REGION = (179, 297, 336, 409)

MouthName = Literal["rest", "closed", "ae", "o"]
MOUTH_NAMES: tuple[MouthName, ...] = ("rest", "closed", "ae", "o")


@dataclass(frozen=True, slots=True)
class MaskCell:
    """One terminal cell covered by the fitted head silhouette."""

    x: int
    y: int
    value: int


@dataclass(frozen=True, slots=True)
class FittedMask:
    """Terminal-sized semantic intensities with a non-rectangular silhouette."""

    width: int
    height: int
    cells: tuple[MaskCell, ...]

    def value_at(self, x: int, y: int) -> int:
        for cell in self.cells:
            if cell.x == x and cell.y == y:
                return cell.value
        return 0

    @property
    def bounds(self) -> tuple[int, int, int, int] | None:
        """Return covered ``(left, top, right, bottom)`` bounds, if any."""

        if not self.cells:
            return None
        xs = [cell.x for cell in self.cells]
        ys = [cell.y for cell in self.cells]
        return min(xs), min(ys), max(xs) + 1, max(ys) + 1


@dataclass(frozen=True, slots=True)
class FittedFaceMasks:
    """Pre-fitted expression combinations for one terminal geometry."""

    width: int
    height: int
    expressions: dict[tuple[bool, MouthName], FittedMask]

    def get(self, *, blinking: bool, mouth: MouthName) -> FittedMask:
        return self.expressions[(blinking, mouth)]


class SemanticMask:
    """A grayscale face control image that can be fitted to terminal cells."""

    def __init__(self, image: Image.Image) -> None:
        grayscale = image.convert("L")
        self._image = grayscale.point(
            tuple(0 if value <= BACKGROUND_CUTOFF else value for value in range(256))
        )

    @classmethod
    def from_path(cls, path: str | Path) -> SemanticMask:
        with Image.open(path) as image:
            return cls(image)

    @property
    def size(self) -> tuple[int, int]:
        return self._image.size

    def with_region_from(
        self,
        other: SemanticMask,
        box: tuple[int, int, int, int],
    ) -> SemanticMask:
        """Return a copy with one aligned semantic region replaced."""

        if self.size != other.size:
            raise ValueError("semantic masks must have identical dimensions")
        left, top, right, bottom = box
        if not (0 <= left < right <= self.size[0] and 0 <= top < bottom <= self.size[1]):
            raise ValueError("replacement region must be inside the semantic mask")

        combined = self._image.copy()
        combined.paste(other._image.crop(box), (left, top))
        return SemanticMask(combined)

    def fit(
        self,
        height: int,
        width: int,
        *,
        cell_aspect: float = DEFAULT_CELL_ASPECT,
        scale: float = DEFAULT_FACE_SCALE,
    ) -> FittedMask:
        """Fit the active mask region without stretching physical cell geometry."""

        if height < 1 or width < 1:
            raise ValueError("terminal dimensions must be positive")
        if not 0.1 <= cell_aspect <= 2.0:
            raise ValueError("cell_aspect must be between 0.1 and 2.0")
        if not 0 < scale <= 1:
            raise ValueError("scale must be within (0, 1]")

        source_bounds = self._image.getbbox()
        if source_bounds is None:
            return FittedMask(width=width, height=height, cells=())

        source = self._image.crop(source_bounds)
        target_width, target_height = fit_grid_size(
            source.width,
            source.height,
            height,
            width,
            cell_aspect=cell_aspect,
            scale=scale,
        )
        fitted = source.resize(
            (target_width, target_height),
            resample=Image.Resampling.LANCZOS,
        ).point(tuple(0 if value <= BACKGROUND_CUTOFF else value for value in range(256)))

        offset_x = (width - target_width) // 2
        offset_y = (height - target_height) // 2
        cells = tuple(_covered_cells(fitted, offset_x=offset_x, offset_y=offset_y))
        return FittedMask(width=width, height=height, cells=cells)


class SemanticFaceMasks:
    """Authored base, blink, and mouth controls combined without full-face resets."""

    def __init__(
        self,
        *,
        base: SemanticMask,
        blink: SemanticMask,
        mouths: dict[MouthName, SemanticMask],
    ) -> None:
        if set(mouths) != set(MOUTH_NAMES):
            raise ValueError("mouth masks must contain rest, closed, ae, and o")
        sizes = {base.size, blink.size, *(mask.size for mask in mouths.values())}
        if len(sizes) != 1:
            raise ValueError("all face masks must have identical dimensions")

        self._expressions: dict[tuple[bool, MouthName], SemanticMask] = {}
        for mouth_name in MOUTH_NAMES:
            open_eyes = base.with_region_from(mouths[mouth_name], MOUTH_REGION)
            self._expressions[(False, mouth_name)] = open_eyes
            self._expressions[(True, mouth_name)] = open_eyes.with_region_from(
                blink,
                EYE_REGION,
            )

    @classmethod
    def from_directory(cls, asset_dir: str | Path) -> SemanticFaceMasks:
        asset_dir = Path(asset_dir)
        return cls(
            base=SemanticMask.from_path(asset_dir / "face.png"),
            blink=SemanticMask.from_path(asset_dir / "face-blink.png"),
            mouths={
                name: SemanticMask.from_path(asset_dir / f"mouth-{name}.png")
                for name in MOUTH_NAMES
            },
        )

    def fit(
        self,
        height: int,
        width: int,
        *,
        cell_aspect: float = DEFAULT_CELL_ASPECT,
        scale: float = DEFAULT_FACE_SCALE,
    ) -> FittedFaceMasks:
        expressions = {
            state: semantic.fit(
                height,
                width,
                cell_aspect=cell_aspect,
                scale=scale,
            )
            for state, semantic in self._expressions.items()
        }
        return FittedFaceMasks(
            width=width,
            height=height,
            expressions=expressions,
        )


def fit_grid_size(
    source_width: int,
    source_height: int,
    terminal_height: int,
    terminal_width: int,
    *,
    cell_aspect: float = DEFAULT_CELL_ASPECT,
    scale: float = DEFAULT_FACE_SCALE,
) -> tuple[int, int]:
    """Return an aspect-correct ``(width, height)`` in terminal cells."""

    if min(source_width, source_height, terminal_height, terminal_width) < 1:
        raise ValueError("source and terminal dimensions must be positive")
    if not 0.1 <= cell_aspect <= 2.0:
        raise ValueError("cell_aspect must be between 0.1 and 2.0")
    if not 0 < scale <= 1:
        raise ValueError("scale must be within (0, 1]")

    max_width = max(1, int(terminal_width * scale))
    max_height = max(1, int(terminal_height * scale))

    # Terminal coordinates describe cells, not square pixels. If a cell is half
    # as wide as it is tall, a physically square mask needs twice as many columns
    # as rows. This ratio keeps the authored face from becoming a tall oval.
    target_cell_ratio = (source_width / source_height) / cell_aspect
    target_width = max_width
    target_height = max(1, round(target_width / target_cell_ratio))
    if target_height > max_height:
        target_height = max_height
        target_width = max(1, round(target_height * target_cell_ratio))

    return min(target_width, terminal_width), min(target_height, terminal_height)


def _covered_cells(
    image: Image.Image,
    *,
    offset_x: int,
    offset_y: int,
) -> list[MaskCell]:
    """Keep each head row contiguous so dark facial features erase rain."""

    cells: list[MaskCell] = []
    pixels = image.load()
    for y in range(image.height):
        active = [x for x in range(image.width) if pixels[x, y] > 0]
        if not active:
            continue
        left, right = active[0], active[-1]
        for x in range(left, right + 1):
            cells.append(
                MaskCell(
                    x=x + offset_x,
                    y=y + offset_y,
                    value=pixels[x, y],
                )
            )
    return cells
