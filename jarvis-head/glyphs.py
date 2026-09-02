"""Pre-rendered monospace glyph atlas for the framebuffer renderer.

Every character the rain or face can draw is rasterized once into a fixed cell.
Per frame the compositor only gathers from this atlas, so font rendering cost
never appears in the frame loop.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from display_errors import DisplaySetupError
from PIL import Image, ImageDraw, ImageFont
from rain import BACKGROUND_CHARS

# Index 0 is the blank cell so a zeroed glyph grid renders black.
ATLAS_ALPHABET = " " + BACKGROUND_CHARS
MIN_FONT_PX = 6
MAX_FONT_PX = 24
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
)
FONT_INSTALL_HINT = "install a monospace TrueType font (Debian/Ubuntu: fonts-dejavu-core)"


class FontNotFoundError(DisplaySetupError):
    """No usable monospace TrueType font could be located."""


def resolve_font_path(explicit: str | Path | None = None) -> Path:
    """Return the font to rasterize, preferring an explicit path over the candidates."""

    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise FontNotFoundError(f"font file not found: {path}")
        return path
    for candidate in FONT_CANDIDATES:
        path = Path(candidate)
        if path.is_file():
            return path
    raise FontNotFoundError(f"no monospace font found; set JARVIS_HEAD_FONT or {FONT_INSTALL_HINT}")


class GlyphAtlas:
    """Alpha coverage for every atlas glyph at one font size, plus a char lookup."""

    def __init__(self, font_path: str | Path, font_px: int) -> None:
        if not MIN_FONT_PX <= font_px <= MAX_FONT_PX:
            raise ValueError(f"font_px must be between {MIN_FONT_PX} and {MAX_FONT_PX}")
        self.font_path = Path(font_path)
        self.font_px = font_px
        font = ImageFont.truetype(str(self.font_path), font_px)
        ascent, descent = font.getmetrics()
        self.cell_height = max(1, ascent + descent)
        self.cell_width = max(1, math.ceil(font.getlength("M")))

        alphas = np.zeros((len(ATLAS_ALPHABET), self.cell_height, self.cell_width), np.uint8)
        for index, char in enumerate(ATLAS_ALPHABET):
            if char == " ":
                continue
            image = Image.new("L", (self.cell_width, self.cell_height), 0)
            ImageDraw.Draw(image).text((0, 0), char, fill=255, font=font)
            alphas[index] = np.asarray(image)
        self.alphas = alphas

        table = np.zeros(128, np.int16)
        for index, char in enumerate(ATLAS_ALPHABET):
            table[ord(char)] = index
        self._index_table = table

    @property
    def cell_aspect(self) -> float:
        """Width/height of one cell; this is what the mask fitter needs."""

        return self.cell_width / self.cell_height

    @property
    def glyph_count(self) -> int:
        return len(ATLAS_ALPHABET)

    def indices(self, text: str) -> np.ndarray:
        """Map a string of atlas characters to glyph indices in one shot."""

        return self._index_table[np.frombuffer(text.encode("ascii"), np.uint8)]
