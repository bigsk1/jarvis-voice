"""Regression tests for Gemini Veo/Omni video backend dispatch."""

import base64
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from google import genai


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

import generate_video


class _FakeInteractions:
    def __init__(self, response, captured):
        self.response = response
        self.captured = captured

    def create(self, **kwargs):
        self.captured.update(kwargs)
        return self.response


class _FakeFiles:
    def __init__(self, video_bytes=b"uri-video-bytes"):
        self.video_bytes = video_bytes
        self.get_names = []
        self.download_files = []

    def get(self, *, name):
        self.get_names.append(name)
        return SimpleNamespace(state=SimpleNamespace(name="ACTIVE"))

    def download(self, *, file):
        self.download_files.append(file)
        return self.video_bytes


class _FakeClient:
    def __init__(self, response, captured):
        self.interactions = _FakeInteractions(response, captured)
        self.files = _FakeFiles()


class _FakeVeoModels:
    def __init__(self, response, captured):
        self.response = response
        self.captured = captured

    def generate_videos(self, **kwargs):
        self.captured.update(kwargs)
        return self.response


class _FakeVeoClient:
    def __init__(self, response, captured):
        self.models = _FakeVeoModels(response, captured)
        self.files = _FakeFiles()


def _config_value(key, default=None):
    values = {
        "GEMINI_API_KEY": "test-key",
        "GEMINI_VIDEO_MODEL": "gemini-omni-flash-preview",
    }
    return values.get(key, default)


def _veo_config_value(key, default=None):
    values = {
        "GEMINI_API_KEY": "test-key",
        "GEMINI_VIDEO_MODEL": "veo-3.1-fast-generate-preview",
    }
    return values.get(key, default)


def test_veo_model_stays_on_generate_videos_api_and_does_not_write_temp_files():
    captured = {}
    video = SimpleNamespace(video_bytes=b"veo-video-bytes", uri=None, url=None)
    operation = SimpleNamespace(
        done=True,
        response=SimpleNamespace(generated_videos=[SimpleNamespace(video=video)]),
    )
    fake_client = _FakeVeoClient(operation, captured)

    with patch.object(generate_video, "get_config_value", side_effect=_veo_config_value), patch.object(
        genai, "Client", return_value=fake_client
    ):
        result = generate_video.generate_video_gemini("A Veo clip", duration=5)

    assert captured["model"] == "veo-3.1-fast-generate-preview"
    assert captured["config"].duration_seconds == 4
    assert result["video_bytes"] == b"veo-video-bytes"
    assert result["video_url"] is None
    assert result["duration"] == 4


def test_omni_text_video_uses_interactions_api_and_requested_duration():
    captured = {}
    encoded_video = base64.b64encode(b"inline-video-bytes").decode("ascii")
    response = SimpleNamespace(
        status="completed",
        id="interaction-123",
        output_video=SimpleNamespace(data=encoded_video, uri=None),
    )
    fake_client = _FakeClient(response, captured)

    with patch.object(generate_video, "get_config_value", side_effect=_config_value), patch.object(
        genai, "Client", return_value=fake_client
    ):
        result = generate_video.generate_video_gemini(
            "A single continuous shot",
            duration=5,
            aspect_ratio="9:16",
            resolution="4k",
            negative_prompt="captions",
        )

    assert captured["model"] == "gemini-omni-flash-preview"
    assert captured["input"] == "A single continuous shot\nDo not include: captions"
    assert captured["response_format"] == {
        "type": "video",
        "delivery": "uri",
        "aspect_ratio": "9:16",
        "duration": "5s",
    }
    assert captured["generation_config"] == {"video_config": {"task": "text_to_video"}}
    assert result["video_bytes"] == b"inline-video-bytes"
    assert result["resolution"] == "720p"
    assert result["duration"] == 5
    assert result["interaction_id"] == "interaction-123"


def test_omni_image_video_encodes_image_and_downloads_uri(tmp_path):
    image_path = tmp_path / "reference.jpg"
    image_path.write_bytes(b"reference-image-bytes")
    captured = {}
    video_uri = "https://generativelanguage.googleapis.com/v1beta/files/video-123:download?alt=media"
    response = SimpleNamespace(
        status="completed",
        id="interaction-456",
        output_video=SimpleNamespace(data=None, uri=video_uri),
    )
    fake_client = _FakeClient(response, captured)

    with patch.object(generate_video, "get_config_value", side_effect=_config_value), patch.object(
        generate_video, "_resolve_image_source", return_value=str(image_path)
    ), patch.object(genai, "Client", return_value=fake_client):
        result = generate_video.generate_video_gemini(
            "Animate the subject",
            duration=20,
            image_url="stash://space/file",
        )

    assert captured["generation_config"] == {"video_config": {"task": "image_to_video"}}
    assert captured["response_format"]["duration"] == "10s"
    assert base64.b64decode(captured["input"][0]["data"]) == b"reference-image-bytes"
    assert captured["input"][0]["mime_type"] == "image/jpeg"
    assert captured["input"][1] == {"type": "text", "text": "Animate the subject"}
    assert fake_client.files.get_names == ["files/video-123"]
    assert fake_client.files.download_files == [video_uri]
    assert result["video_bytes"] == b"uri-video-bytes"
    assert result["from_image"] is True


def test_omni_image_load_failure_aborts_before_generation():
    captured = {}
    encoded_video = base64.b64encode(b"unexpected-video").decode("ascii")
    response = SimpleNamespace(
        status="completed",
        id="unexpected-interaction",
        output_video=SimpleNamespace(data=encoded_video, uri=None),
    )
    fake_client = _FakeClient(response, captured)

    with patch.object(generate_video, "get_config_value", side_effect=_config_value), patch.object(
        generate_video, "_resolve_image_source", return_value=None
    ), patch.object(generate_video.requests, "get", side_effect=OSError("download failed")), patch.object(
        genai, "Client", return_value=fake_client
    ):
        with pytest.raises(Exception, match="download failed"):
            generate_video.generate_video_gemini(
                "Animate the subject",
                image_url="https://cdn.example/reference.png",
            )

    assert captured == {}


def test_veo_image_load_failure_aborts_before_generation():
    captured = {}
    operation = SimpleNamespace(done=True, response=SimpleNamespace(generated_videos=[]))
    fake_client = _FakeVeoClient(operation, captured)

    with patch.object(generate_video, "get_config_value", side_effect=_veo_config_value), patch.object(
        generate_video, "_resolve_image_source", return_value=None
    ), patch.object(generate_video.requests, "get", side_effect=OSError("download failed")), patch.object(
        genai, "Client", return_value=fake_client
    ):
        with pytest.raises(Exception, match="download failed"):
            generate_video.generate_video_gemini(
                "Animate the subject",
                image_url="https://cdn.example/reference.png",
            )

    assert captured == {}
