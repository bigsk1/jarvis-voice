"""Regression coverage for OpenAI Sora image-to-video source handling."""

import io
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PIL import Image


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

import generate_video


class _Response:
    def __init__(self, content, content_type="image/png"):
        self.content = content
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        return None


class _Videos:
    def __init__(self):
        self.create_calls = []

    async def create_and_poll(self, **kwargs):
        input_reference = kwargs.get("input_reference")
        self.create_calls.append(
            {
                "has_input_reference": input_reference is not None,
                "image_prefix": input_reference.read(2) if input_reference else None,
            }
        )
        return SimpleNamespace(status="completed", id="video-test", error=None)

    async def download_content(self, _video_id):
        return b"video-bytes"


class _AsyncOpenAI:
    def __init__(self, videos):
        self.videos = videos


def _config_value(key, default=None):
    values = {
        "OPENAI_API_KEY": "test-key",
        "OPENAI_VIDEO_MODEL": "sora-2",
    }
    return values.get(key, default)


def _png_bytes():
    output = io.BytesIO()
    Image.new("RGB", (2, 2), color="blue").save(output, format="PNG")
    return output.getvalue()


def test_sora_remote_image_is_downloaded_and_attached():
    videos = _Videos()
    fake_client = _AsyncOpenAI(videos)
    result = None

    with patch.object(generate_video, "get_config_value", side_effect=_config_value), patch.object(
        generate_video.requests, "get", return_value=_Response(_png_bytes())
    ), patch("openai.AsyncOpenAI", return_value=fake_client):
        try:
            result = generate_video.generate_video_openai(
                "Animate the subject",
                image_path="https://cdn.example/reference.png",
            )

            assert videos.create_calls == [
                {"has_input_reference": True, "image_prefix": b"\xff\xd8"}
            ]
            assert result["from_image"] is True
        finally:
            if result and result.get("video_url", "").startswith("file://"):
                Path(result["video_url"].removeprefix("file://")).unlink(missing_ok=True)


def test_sora_remote_image_failure_aborts_before_generation():
    videos = _Videos()
    fake_client = _AsyncOpenAI(videos)

    with patch.object(generate_video, "get_config_value", side_effect=_config_value), patch.object(
        generate_video.requests, "get", side_effect=OSError("download failed")
    ), patch("openai.AsyncOpenAI", return_value=fake_client):
        with pytest.raises(Exception, match="download failed"):
            generate_video.generate_video_openai(
                "Animate the subject",
                image_path="https://cdn.example/reference.png",
            )

    assert videos.create_calls == []
