"""Phase 1 tests for Jarvis Head semantic-mask fitting."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image, ImageChops

HEAD_ROOT = Path(__file__).resolve().parents[1] / "jarvis-head"
sys.path.insert(0, str(HEAD_ROOT))

from mask import EYE_REGION, MOUTH_NAMES, MOUTH_REGION, SemanticMask, fit_grid_size  # noqa: E402


def test_square_mask_is_aspect_corrected_for_tall_terminal_cells():
    assert fit_grid_size(100, 100, 50, 200, cell_aspect=0.5) == (90, 45)
    assert fit_grid_size(100, 100, 50, 200, cell_aspect=0.75) == (60, 45)


def test_fit_centers_the_authored_head_without_a_bright_rectangle():
    fitted = SemanticMask.from_path(HEAD_ROOT / "assets" / "face.png").fit(
        50,
        200,
        cell_aspect=0.5,
    )

    assert fitted.bounds is not None
    left, top, right, bottom = fitted.bounds
    assert (left + right) // 2 == fitted.width // 2
    assert top > 0
    assert bottom < fitted.height
    assert fitted.value_at(0, 0) == 0
    assert max(cell.value for cell in fitted.cells) >= 240
    assert len(fitted.cells) < (right - left) * (bottom - top)


def test_dark_aperture_inside_the_silhouette_remains_covered():
    image = Image.new("L", (5, 3), color=100)
    image.putpixel((2, 1), 0)

    fitted = SemanticMask(image).fit(3, 5, cell_aspect=1.0, scale=1.0)
    center = next(cell for cell in fitted.cells if (cell.x, cell.y) == (2, 1))

    assert center.value == 0


def test_expression_assets_only_change_their_authored_regions():
    base = Image.open(HEAD_ROOT / "assets" / "face.png")
    variants = {
        "face-blink": EYE_REGION,
        **{f"mouth-{name}": MOUTH_REGION for name in MOUTH_NAMES},
    }

    for name, region in variants.items():
        variant = Image.open(HEAD_ROOT / "assets" / f"{name}.png")
        assert variant.mode == base.mode == "L"
        assert variant.size == base.size == (512, 512)
        difference = ImageChops.difference(base, variant)
        difference.paste(0, region)
        assert difference.getbbox() is None

    assert ImageChops.difference(
        base.crop(EYE_REGION),
        Image.open(HEAD_ROOT / "assets" / "face-blink.png").crop(EYE_REGION),
    ).getbbox()
    assert ImageChops.difference(
        Image.open(HEAD_ROOT / "assets" / "mouth-ae.png").crop(MOUTH_REGION),
        Image.open(HEAD_ROOT / "assets" / "mouth-o.png").crop(MOUTH_REGION),
    ).getbbox()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"terminal_height": 0}, "positive"),
        ({"cell_aspect": 0.0}, "cell_aspect"),
        ({"scale": 1.1}, "scale"),
    ],
)
def test_invalid_fit_parameters_are_rejected(kwargs, message):
    arguments = {
        "source_width": 10,
        "source_height": 10,
        "terminal_height": 10,
        "terminal_width": 10,
    }
    arguments.update(kwargs)

    with pytest.raises(ValueError, match=message):
        fit_grid_size(**arguments)
