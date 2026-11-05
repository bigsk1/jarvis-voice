"""Web enforces the catalog's image format capabilities before staging work."""

from pathlib import Path

import pytest
from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
load_server_package("jarvis_web_image_options_test", ROOT / "jarvis-web" / "server")

from jarvis_web_image_options_test.services.image_generation_options import (  # noqa: E402
    validate_gif_analysis_frame,
    validate_image_generation_settings,
)


def test_web_accepts_selected_gif_frame_and_animation_controls():
    validate_image_generation_settings({
        "provider": "openai", "model": "gpt-image-2.6-sunburst", "output_format": "gif",
        "complexity": "medium", "frame_count": 9, "frame_duration_ms": 200, "reference_frame": 0,
    }, source_gif=True)


@pytest.mark.parametrize("settings, source_gif", [
    ({"provider": "openai", "model": "gpt-image-2.5-flare", "output_format": "gif"}, False),
    ({"provider": "gemini", "output_format": "gif"}, False),
    ({"provider": "xai"}, True),
    ({"provider": "openai", "model": "gpt-image-2.5-flare"}, True),
    ({"provider": "openai", "model": "gpt-image-2.5-flare", "complexity": "high"}, False),
    ({"provider": "openai", "model": "gpt-image-2.6-flare", "frame_count": 9}, False),
    ({"provider": "openai", "model": "gpt-image-2.6-flare", "output_format": "gif", "frame_count": True}, False),
    ({"provider": "openai", "model": "gpt-image-2.6-flare", "output_format": "gif", "frame_duration_ms": 19}, False),
    ({"provider": "openai", "model": "gpt-image-2.6-flare", "output_format": "gif", "transparent": True}, False),
    ({"reference_frame": -1}, False),
])
def test_web_rejects_unsupported_animation_settings(settings, source_gif):
    with pytest.raises(ValueError):
        validate_image_generation_settings(settings, source_gif=source_gif)


def test_web_rejects_out_of_range_source_frame_before_staging():
    with pytest.raises(ValueError, match="less than the source's 4 frames"):
        validate_image_generation_settings({
            "provider": "openai", "model": "gpt-image-2.6-flare", "reference_frame": 4,
        }, source_gif=True, source_frame_count=4)


@pytest.mark.parametrize('frame', [0, 3])
def test_explicit_gif_analysis_frame_keeps_zero_based_selection(frame):
    assert validate_gif_analysis_frame({'gif_frame': frame}, [
        {'mime_type': 'image/gif', 'source_frame_count': 4},
    ]) == frame


@pytest.mark.parametrize('settings,images', [
    ({'gif_frame': True}, [{'mime_type': 'image/gif', 'source_frame_count': 4}]),
    ({'gif_frame': -1}, [{'mime_type': 'image/gif', 'source_frame_count': 4}]),
    ({'gif_frame': 4}, [{'mime_type': 'image/gif', 'source_frame_count': 4}]),
    ({'gif_frame': 0}, [{'mime_type': 'image/png', 'source_frame_count': 4}]),
    ({'gif_frame': 0}, [{'mime_type': 'image/gif'}]),
    ({'gif_frame': 0}, [{'mime_type': 'image/gif', 'source_frame_count': 4}] * 2),
])
def test_explicit_gif_analysis_frame_rejects_invalid_or_ambiguous_sources(settings, images):
    with pytest.raises(ValueError):
        validate_gif_analysis_frame(settings, images)
